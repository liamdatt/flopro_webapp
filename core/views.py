from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from django.contrib.auth.models import User
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django import forms
import json
import os

from .models import Service, UserWorkflow, BudgetService, Transaction, UserProfile, GoogleCredential
from .google_api import get_gmail_service, get_calendar_service
from google_auth_oauthlib.flow import Flow
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import base64
import uuid
from datetime import datetime
from django.utils import timezone
from django.urls import reverse
from .provisioning import provision_user_workflow, toggle_user_service, get_active_service, provision_user_workflow_with_credentials_map
from .n8n_client import N8nClient
from requests import HTTPError


class CustomUserCreationForm(UserCreationForm):
    """Custom user creation form that includes phone number."""
    phone_number = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Optional phone number'})
    )

    class Meta:
        model = UserCreationForm.Meta.model
        fields = UserCreationForm.Meta.fields + ('phone_number',)

    def clean_phone_number(self):
        """Validate that the phone number is unique."""
        phone = self.cleaned_data.get('phone_number')
        if phone:
            # Normalize the phone number for comparison
            normalized = ''.join(c for c in phone if c.isdigit() or c == '+')
            if normalized.startswith('+'):
                normalized = normalized[1:]

            # Check if this normalized phone number already exists
            if UserProfile.objects.filter(phone_number=normalized).exists():
                raise forms.ValidationError("This phone number is already in use by another account. Please use a different phone number.")

        return phone

    def save(self, commit=True):
        user = super().save(commit=commit)
        # Persist phone number in user.profile
        phone = self.cleaned_data.get('phone_number')
        if phone is not None:
            normalized = ''.join(c for c in phone if c.isdigit() or c == '+')
            if normalized.startswith('+'):
                normalized = normalized[1:]
            user.profile.phone_number = normalized
            user.profile.save(update_fields=['phone_number'])
        return user


def landing_page(request):
    """Landing page view for the Flopro WA application."""
    if request.user.is_authenticated:
        return redirect('core:dashboard')

    services = Service.objects.filter(is_active=True)
    return render(request, 'core/landing_page.html', {'services': services})


def signup_view(request):
    """User signup view."""
    if request.user.is_authenticated:
        return redirect('core:dashboard')

    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Account created successfully! Welcome to Flopro WA.')
            return redirect('core:dashboard')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = CustomUserCreationForm()

    return render(request, 'registration/signup.html', {'form': form})


def login_view(request):
    """Custom login view to ensure proper redirect."""
    if request.user.is_authenticated:
        return redirect('core:dashboard')

    from django.contrib.auth import authenticate, login as auth_login
    from django.contrib.auth.forms import AuthenticationForm

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                auth_login(request, user)
                messages.success(request, f'Welcome back, {user.username}!')
                return redirect('core:dashboard')
            else:
                messages.error(request, 'Invalid username or password.')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = AuthenticationForm()

    return render(request, 'registration/login.html', {'form': form})


def logout_view(request):
    """Custom logout view to ensure proper redirect."""
    from django.contrib.auth import logout
    from django.shortcuts import redirect

    logout(request)
    return redirect('core:landing_page')


@login_required
def dashboard(request):
    """User dashboard showing available services and active workflows."""
    services = Service.objects.filter(is_active=True)
    user_workflows = UserWorkflow.objects.filter(user=request.user).select_related('service')
    active_service = get_active_service(request.user)

    context = {
        'services': services,
        'user_workflows': user_workflows,
        'active_service': active_service,
    }
    return render(request, 'core/dashboard.html', context)


@login_required
def service_detail(request, service_slug):
    """Show service details and unlock form."""
    service = get_object_or_404(Service, slug=service_slug, is_active=True)

    # Check if user already has this service
    try:
        user_workflow = UserWorkflow.objects.get(user=request.user, service=service)
        return redirect('core:dashboard')  # Already has this service
    except UserWorkflow.DoesNotExist:
        pass

    if request.method == 'POST':
        # Handle credential form submission
        try:
            if service.slug == 'budget-tracker':
                # Ensure phone and budget are provided
                phone = request.POST.get('phone_number') or (getattr(request.user, 'profile', None) and request.user.profile.phone_number)
                budget_raw = request.POST.get('budget_amount')

                # Check if phone is required (only if user doesn't have one in profile)
                user_has_phone = (
                    hasattr(request.user, 'profile') and
                    request.user.profile.phone_number and
                    request.user.profile.phone_number.strip()
                )

                if not phone:
                    if user_has_phone:
                        phone = request.user.profile.phone_number
                    else:
                        messages.error(request, 'Phone number is required.')
                        raise ValueError('Missing phone number')

                if not budget_raw:
                    messages.error(request, 'Budget amount is required.')
                    raise ValueError('Missing budget amount')

                # Normalize and save phone on user if changed
                normalized_phone = ''.join(c for c in phone if c.isdigit() or c == '+')
                if normalized_phone.startswith('+'):
                    normalized_phone = normalized_phone[1:]
                if getattr(request.user, 'profile', None) is not None:
                    if request.user.profile.phone_number != normalized_phone:
                        # Check if the new phone number is already in use by another user
                        existing_profile = UserProfile.objects.filter(phone_number=normalized_phone).exclude(user=request.user).first()
                        if existing_profile:
                            messages.error(request, 'This phone number is already in use by another account. Please use a different phone number.')
                            raise ValueError('Phone number already in use')

                        request.user.profile.phone_number = normalized_phone
                        request.user.profile.save(update_fields=['phone_number'])

                # Upsert BudgetService
                from decimal import Decimal
                try:
                    budget_amount = Decimal(budget_raw)
                except Exception:
                    messages.error(request, 'Invalid budget amount.')
                    raise

                BudgetService.objects.update_or_create(
                    user=request.user,
                    phone_number=normalized_phone,
                    defaults={'budget_amount': budget_amount}
                )

                # Mark service as unlocked without n8n resources
                UserWorkflow.objects.update_or_create(
                    user=request.user,
                    service=service,
                    defaults={
                        'name': f"{service.name} - {request.user.username}",
                        'active': True,
                        'n8n_workflow_id': None,
                        'n8n_credential_id': None,
                    }
                )

                messages.success(request, f"Successfully unlocked {service.name}!")
                return redirect('core:dashboard')

            if service.slug == 'ultimate-personal-assistant':
                # Ensure phone number is available
                phone = request.POST.get('phone_number') or (
                    hasattr(request.user, 'profile') and request.user.profile.phone_number
                )

                if not phone:
                    messages.error(request, 'Phone number is required.')
                    raise ValueError('Missing phone number')

                # Normalize and save phone on user if changed or missing
                normalized_phone = ''.join(c for c in phone if c.isdigit() or c == '+')
                if normalized_phone.startswith('+'):
                    normalized_phone = normalized_phone[1:]

                # Ensure user has a profile
                if not hasattr(request.user, 'profile'):
                    UserProfile.objects.create(user=request.user, phone_number=normalized_phone)
                elif request.user.profile.phone_number != normalized_phone:
                    existing_profile = UserProfile.objects.filter(phone_number=normalized_phone).exclude(user=request.user).first()
                    if existing_profile:
                        messages.error(request, 'This phone number is already in use by another account. Please use a different phone number.')
                        raise ValueError('Phone number already in use')
                    request.user.profile.phone_number = normalized_phone
                    request.user.profile.save(update_fields=['phone_number'])

                # Store service info for post-OAuth callback
                request.session['pending_service_unlock'] = {
                    'service_slug': service.slug,
                    'phone_number': normalized_phone,
                }

                # Redirect to webapp Google OAuth flow
                return redirect('core:google_oauth_start')

            if service.credential_type == 'googleOAuth2':
                # For OAuth2, redirect to n8n for authorization
                return handle_oauth_flow(request, service)
            else:
                # Handle other credential types
                credential_data = extract_credential_data(request.POST, service)
                workflow_id, credential_id = provision_user_workflow(
                    user=request.user,
                    service=service,
                    credential_data=credential_data
                )
                messages.success(request, f"Successfully unlocked {service.name}!")
                return redirect('core:dashboard')

        except Exception as e:
            messages.error(request, f"Failed to unlock service: {str(e)}")

    # Modify schema based on user's phone number status for services that need it
    credential_schema = service.credential_ui_schema.copy() if service.credential_ui_schema else {}
    needs_phone = service.slug in ['budget-tracker', 'ultimate-personal-assistant']

    user_has_phone = False
    if needs_phone:
        user_has_phone = (
            hasattr(request.user, 'profile') and
            request.user.profile.phone_number and
            request.user.profile.phone_number.strip()
        )

        if user_has_phone:
            # Remove phone_number field from schema since user already provided it
            credential_schema.pop('phone_number', None)
        else:
            # Keep phone_number field but make it required
            if 'phone_number' in credential_schema:
                credential_schema['phone_number']['required'] = True

    context = {
        'service': service,
        'credential_schema': credential_schema,
        'user_has_phone': user_has_phone,
        'needs_phone': needs_phone,
    }
    return render(request, 'core/service_detail.html', context)


@login_required
def service_overview(request, service_slug):
    """Overview page for a service; for budget-tracker show metrics and table."""
    service = get_object_or_404(Service, slug=service_slug, is_active=True)
    if service.slug != 'budget-tracker':
        return redirect('core:service_detail', service_slug=service.slug)

    # Ensure user has unlocked
    if not UserWorkflow.objects.filter(user=request.user, service=service).exists():
        messages.error(request, 'Please unlock this service first.')
        return redirect('core:service_detail', service_slug=service.slug)

    # Resolve phone
    phone = None
    if getattr(request.user, 'profile', None):
        phone = request.user.profile.phone_number
    # Fallback: scan BudgetService rows
    if not phone:
        profile = BudgetService.objects.filter(user=request.user).order_by('-updated_at').first()
        phone = profile.phone_number if profile else None

    if not phone:
        messages.error(request, 'Missing phone number. Please reconfigure this service.')
        return redirect('core:service_detail', service_slug=service.slug)

    # Load budget profile
    profile = BudgetService.objects.filter(user=request.user, phone_number=phone).order_by('-updated_at').first()
    from django.db.models import Sum
    spent = Transaction.objects.filter(phone_number=phone).aggregate(s=Sum('total'))['s'] or 0
    remaining = (profile.budget_amount if profile else 0) - spent

    # Transactions list
    transactions = Transaction.objects.filter(phone_number=phone).order_by('-date', '-created_at')

    context = {
        'service': service,
        'phone': phone,
        'budget': profile.budget_amount if profile else 0,
        'spent': spent,
        'remaining': remaining,
        'transactions': transactions,
    }
    return render(request, 'core/budget_overview.html', context)


@login_required
@require_POST
def update_budget(request, service_slug):
    service = get_object_or_404(Service, slug=service_slug, is_active=True)
    if service.slug != 'budget-tracker':
        return redirect('core:service_detail', service_slug=service.slug)

    amount = request.POST.get('budget_amount')
    if not amount:
        messages.error(request, 'Budget amount is required.')
        return redirect('core:service_overview', service_slug=service.slug)

    # Resolve phone
    phone = None
    if getattr(request.user, 'profile', None):
        phone = request.user.profile.phone_number
    profile = BudgetService.objects.filter(user=request.user).order_by('-updated_at').first()
    if not phone and profile:
        phone = profile.phone_number

    if not phone:
        messages.error(request, 'Missing phone number. Please reconfigure this service.')
        return redirect('core:service_overview', service_slug=service.slug)

    from decimal import Decimal
    try:
        val = Decimal(str(amount))
    except Exception:
        messages.error(request, 'Invalid budget amount.')
        return redirect('core:service_overview', service_slug=service.slug)

    BudgetService.objects.update_or_create(
        user=request.user,
        phone_number=phone,
        defaults={'budget_amount': val}
    )
    messages.success(request, 'Budget updated successfully.')
    return redirect('core:service_overview', service_slug=service.slug)


@login_required
@require_POST
def delete_transaction(request, service_slug, tx_id):
    service = get_object_or_404(Service, slug=service_slug, is_active=True)
    if service.slug != 'budget-tracker':
        return redirect('core:service_detail', service_slug=service.slug)

    # Resolve phone allowed to delete
    phone = None
    if getattr(request.user, 'profile', None):
        phone = request.user.profile.phone_number
    profile = BudgetService.objects.filter(user=request.user).order_by('-updated_at').first()
    if not phone and profile:
        phone = profile.phone_number

    tx = get_object_or_404(Transaction, id=tx_id)
    if phone and tx.phone_number == phone:
        tx.delete()
        messages.success(request, 'Transaction deleted.')
    else:
        messages.error(request, 'Not authorized to delete this transaction.')
    return redirect('core:service_overview', service_slug=service.slug)


@login_required
@require_POST
def toggle_service(request, service_slug=None):
    """Toggle between user services."""
    # Handle AJAX requests with service_slug in POST data
    if request.content_type == 'application/json':
        try:
            import json
            data = json.loads(request.body)
            service_slug = data.get('service_slug')
        except:
            return JsonResponse({'success': False, 'error': 'Invalid JSON data'})

    if not service_slug:
        if request.content_type == 'application/json':
            return JsonResponse({'success': False, 'error': 'Service slug required'})
        messages.error(request, 'Service slug required')
        return redirect('core:dashboard')

    service = get_object_or_404(Service, slug=service_slug, is_active=True)

    if toggle_user_service(user=request.user, service=service):
        if request.content_type == 'application/json':
            return JsonResponse({'success': True, 'message': f"Switched to {service.name}"})
        messages.success(request, f"Switched to {service.name}")
    else:
        if request.content_type == 'application/json':
            return JsonResponse({'success': False, 'error': f"You haven't unlocked {service.name} yet"})
        messages.error(request, f"You haven't unlocked {service.name} yet")

    return redirect('core:dashboard')


@login_required
def delete_account(request):
    """Handle account deletion with confirmation."""
    if request.method == 'POST':
        try:
            # Get user data before deletion for logging
            user_data = {
                'username': request.user.username,
                'email': request.user.email,
                'phone': getattr(request.user.profile, 'phone_number', None) if hasattr(request.user, 'profile') else None,
                'services_count': UserWorkflow.objects.filter(user=request.user).count(),
                'transactions_count': Transaction.objects.filter(phone_number=getattr(request.user.profile, 'phone_number', '') if hasattr(request.user, 'profile') else '').count()
            }

            # Delete all related data
            # Delete UserWorkflows (this handles the relationship to services)
            UserWorkflow.objects.filter(user=request.user).delete()

            # Delete BudgetService entries
            if hasattr(request.user, 'profile') and request.user.profile.phone_number:
                BudgetService.objects.filter(phone_number=request.user.profile.phone_number).delete()

            # Delete transactions associated with this user's phone number
            if hasattr(request.user, 'profile') and request.user.profile.phone_number:
                Transaction.objects.filter(phone_number=request.user.profile.phone_number).delete()

            # Store user reference before logout
            user_to_delete = request.user

            # Delete the user (this will cascade to UserProfile due to OneToOneField)
            user_to_delete.delete()

            # Now logout (this will set request.user to AnonymousUser)
            from django.contrib.auth import logout
            logout(request)

            # Log the deletion (you might want to log this elsewhere)
            print(f"Account deleted: {user_data}")

            messages.success(request, 'Your account has been permanently deleted.')
            return redirect('core:landing_page')

        except Exception as e:
            messages.error(request, f'Error deleting account: {str(e)}')
            return redirect('core:dashboard')

    # GET request - show confirmation page
    context = {
        'user_workflows': UserWorkflow.objects.filter(user=request.user),
        'budget_services': BudgetService.objects.filter(user=request.user) if hasattr(request.user, 'profile') else [],
        'transactions': Transaction.objects.filter(
            phone_number=getattr(request.user.profile, 'phone_number', '')
        ) if hasattr(request.user, 'profile') else [],
        'has_phone': hasattr(request.user, 'profile') and request.user.profile.phone_number,
    }
    return render(request, 'core/delete_account.html', context)


@login_required
@require_POST
def unlock_service(request, service_slug):
    """AJAX endpoint to unlock a service."""
    try:
        service = get_object_or_404(Service, slug=service_slug, is_active=True)

        # Check if user already has this service
        if UserWorkflow.objects.filter(user=request.user, service=service).exists():
            return JsonResponse({'success': False, 'error': 'Service already unlocked'})

        # Extract credential data from POST
        credential_data = extract_credential_data(request.POST, service)

        # Provision the workflow
        workflow_id, credential_id = provision_user_workflow(
            user=request.user,
            service=service,
            credential_data=credential_data
        )

        return JsonResponse({
            'success': True,
            'message': f'Successfully unlocked {service.name}!',
            'workflow_id': workflow_id,
            'credential_id': credential_id
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


def handle_oauth_flow(request, service):
    """Start OAuth2 via n8n for Google services (Gmail + Calendar)."""
    try:
        # Require Google client config in environment
        client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
        client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise RuntimeError("Missing GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_CLIENT_SECRET")

        client = N8nClient()

        # Create both Gmail and Calendar credentials with appropriate scopes
        timestamp = int(timezone.now().timestamp())
        base_name = f"{service.slug}:{request.user.id}:{timestamp}"

        credentials_created = {}

        # 1. Create Gmail OAuth2 credential
        try:
            gmail_cred = client.create_credential(
                name=f"{base_name}:gmail",
                cred_type="gmailOAuth2",
                data={
                    "clientId": client_id,
                    "clientSecret": client_secret,
                    "sendAdditionalBodyProperties": False,
                    "additionalBodyProperties": {},
                },
                node_types=["n8n-nodes-base.gmailTool"],
            )
            credentials_created["gmailOAuth2"] = gmail_cred["id"]
        except HTTPError as e:
            if getattr(e, 'response', None) and e.response.status_code == 400:
                # Fall back to googleOAuth2 if gmailOAuth2 not supported
                gmail_cred = client.create_credential(
                    name=f"{base_name}:gmail",
                    cred_type="googleOAuth2",
                    data={
                        "clientId": client_id,
                        "clientSecret": client_secret,
                        "sendAdditionalBodyProperties": False,
                        "additionalBodyProperties": {},
                    },
                    node_types=["n8n-nodes-base.gmailTool"],
                )
                credentials_created["gmailOAuth2"] = gmail_cred["id"]
            else:
                raise

        # 2. Create Google Calendar OAuth2 credential
        try:
            calendar_cred = client.create_credential(
                name=f"{base_name}:calendar",
                cred_type="googleCalendarOAuth2Api",
                data={
                    "clientId": client_id,
                    "clientSecret": client_secret,
                    "sendAdditionalBodyProperties": False,
                    "additionalBodyProperties": {},
                },
                node_types=["n8n-nodes-base.googleCalendarTool"],
            )
            credentials_created["googleCalendarOAuth2Api"] = calendar_cred["id"]
        except HTTPError as e:
            if getattr(e, 'response', None) and e.response.status_code == 400:
                # Fall back to googleOAuth2 if googleCalendarOAuth2Api not supported
                calendar_cred = client.create_credential(
                    name=f"{base_name}:calendar",
                    cred_type="googleOAuth2",
                    data={
                        "clientId": client_id,
                        "clientSecret": client_secret,
                        "sendAdditionalBodyProperties": False,
                        "additionalBodyProperties": {},
                    },
                    node_types=["n8n-nodes-base.googleCalendarTool"],
                )
                credentials_created["googleCalendarOAuth2Api"] = calendar_cred["id"]
            else:
                raise

        # Persist pending state for callback finalization
        request.session["oauth_pending"] = {
            "service_slug": service.slug,
            "credentials": credentials_created,
        }

        # For OAuth flow, we'll use the Gmail credential for authorization
        # (since Gmail scope includes basic Google OAuth, and Calendar will be authorized separately)
        primary_cred_id = credentials_created["gmailOAuth2"]

        # Callback after n8n completes Google OAuth
        return_uri = request.build_absolute_uri(
            reverse("core:oauth_callback", kwargs={"service_slug": service.slug})
        )

        # Redirect user to n8n authorize URL for Gmail (which will prompt for both scopes)
        authorize_url = client.build_oauth_authorize_url(primary_cred_id, return_uri)
        return redirect(authorize_url)

    except Exception as e:
        messages.error(request, f"OAuth setup failed: {str(e)}")
        return redirect('core:service_detail', service_slug=service.slug)


@login_required
def oauth_callback(request, service_slug):
    """Finalize OAuth: clone template workflow and attach the authorized credentials."""
    service = get_object_or_404(Service, slug=service_slug, is_active=True)

    state = request.session.get("oauth_pending") or {}
    if state.get("service_slug") != service.slug:
        messages.error(request, "Invalid or missing OAuth session state.")
        return redirect('core:service_detail', service_slug=service.slug)

    credentials = state.get("credentials", {})
    if not credentials:
        messages.error(request, "Missing credentials.")
        return redirect('core:service_detail', service_slug=service.slug)

    try:
        # Create mapping of credential type to credential ID
        credential_type_to_id = {
            "gmailOAuth2": int(credentials["gmailOAuth2"]),
            "googleCalendarOAuth2Api": int(credentials["googleCalendarOAuth2Api"]),
        }

        # Create mapping of node type to credential ID
        node_type_to_credential_id = {
            "n8n-nodes-base.gmailTool": credential_type_to_id["gmailOAuth2"],
            "n8n-nodes-base.googleCalendarTool": credential_type_to_id["googleCalendarOAuth2Api"],
        }

        # Create user-specific workflow wired to these credentials
        provision_user_workflow_with_credentials_map(
            user=request.user,
            service=service,
            node_type_to_credential_id=node_type_to_credential_id,
        )

        # Clear session state
        request.session.pop("oauth_pending", None)

        messages.success(request, f"Successfully unlocked {service.name}!")
        return redirect('core:dashboard')
    except Exception as e:
        messages.error(request, f"Finalization failed: {str(e)}")
        return redirect('core:service_detail', service_slug=service.slug)


def extract_credential_data(post_data, service):
    """Extract credential data from POST data based on service schema."""
    credential_data = {}

    # This is a simple implementation - in production you'd want more validation
    schema = service.credential_ui_schema

    for field_name, field_config in schema.items():
        # Skip phone_number for OAuth services - it's handled separately
        if field_name == 'phone_number' and service.credential_type == 'googleOAuth2':
            continue
        if field_name in post_data:
            credential_data[field_name] = post_data[field_name]

    return credential_data


# API endpoints for n8n webhooks (if needed)
@csrf_exempt
def n8n_webhook(request, workflow_id):
    """Handle webhooks from n8n workflows."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            return JsonResponse({'status': 'received'})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

    return JsonResponse({'error': 'Method not allowed'}, status=405)


def _extract_api_key(request):
    auth_header = request.headers.get('Authorization')
    bearer = None
    if auth_header:
        parts = auth_header.split(' ', 1)
        if len(parts) == 2 and parts[0].lower() == 'bearer':
            bearer = parts[1].strip()
        else:
            bearer = auth_header.strip()
    return request.headers.get('X-API-Key') or bearer or request.GET.get('api_key')


def _require_internal_api_key(request):
    api_key = _extract_api_key(request)
    if not settings.INTERNAL_API_KEY or api_key != settings.INTERNAL_API_KEY:
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    return None


@csrf_exempt
def api_budget_remaining(request):
    """Return remaining budget for a phone number: budget - sum(transactions)."""
    from django.conf import settings
    if request.method not in ('GET', 'POST'):
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    resp = _require_internal_api_key(request)
    if resp:
        return resp

    phone = request.GET.get('phone')
    if request.method == 'POST' and not phone:
        try:
            body = json.loads(request.body or '{}')
        except Exception:
            body = {}
        phone = body.get('phone') or body.get('phone_number') or request.POST.get('phone') or request.POST.get('phone_number')
    if not phone:
        return JsonResponse({'error': 'phone required'}, status=400)

    normalized_phone = ''.join(c for c in phone if c.isdigit() or c == '+')
    if normalized_phone.startswith('+'):
        normalized_phone = normalized_phone[1:]

    # Find budget profile
    profile = BudgetService.objects.filter(phone_number=normalized_phone).order_by('-updated_at').first()
    if not profile:
        return JsonResponse({'error': 'budget not found'}, status=404)

    from django.db.models import Sum
    spent = Transaction.objects.filter(phone_number=normalized_phone).aggregate(s=Sum('total'))['s'] or 0
    remaining = profile.budget_amount - spent
    return JsonResponse({
        'phone': normalized_phone,
        'budget': str(profile.budget_amount),
        'spent': str(spent),
        'remaining': str(remaining),
        'updated_at': profile.updated_at.isoformat(),
    })


@csrf_exempt
def api_add_transaction(request):
    """Add a transaction for a phone number via n8n or internal calls."""
    from django.conf import settings
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    resp = _require_internal_api_key(request)
    if resp:
        return resp

    try:
        payload = json.loads(request.body)
    except Exception:
        return JsonResponse({'error': 'invalid json'}, status=400)

    phone = payload.get('phone')
    name = payload.get('name')
    date = payload.get('date')
    total = payload.get('total')

    if not all([phone, name, date, total]):
        return JsonResponse({'error': 'phone, name, date, total are required'}, status=400)

    normalized_phone = ''.join(c for c in phone if c.isdigit() or c == '+')
    if normalized_phone.startswith('+'):
        normalized_phone = normalized_phone[1:]

    from decimal import Decimal
    from datetime import date as dt_date
    try:
        amt = Decimal(str(total))
        tx_date = dt_date.fromisoformat(date)
    except Exception:
        return JsonResponse({'error': 'invalid date or total'}, status=400)

    Transaction.objects.create(
        phone_number=normalized_phone,
        name=name,
        date=tx_date,
        total=amt,
    )

    return JsonResponse({'status': 'ok'})


@csrf_exempt
def api_phone_allowed(request):
    """Return {'allowed': true|false} based on whether the phone has any unlocked service.

    Accepts GET ?phone=... or POST JSON {'phone': '...'}.
    Requires INTERNAL_API_KEY via Authorization/X-API-Key/ ?api_key.
    """
    from django.conf import settings
    if request.method not in ('GET', 'POST'):
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    resp = _require_internal_api_key(request)
    if resp:
        return resp

    # Phone extraction
    phone = request.GET.get('phone')
    if request.method == 'POST' and not phone:
        try:
            body = json.loads(request.body or '{}')
        except Exception:
            body = {}
        phone = body.get('phone') or body.get('phone_number') or request.POST.get('phone') or request.POST.get('phone_number')
    if not phone:
        return JsonResponse({'error': 'phone required'}, status=400)

    normalized_phone = ''.join(c for c in phone if c.isdigit() or c == '+')
    if normalized_phone.startswith('+'):
        normalized_phone = normalized_phone[1:]

    # Check if any workflow exists for user with this phone (profile)
    exists = UserWorkflow.objects.filter(user__profile__phone_number=normalized_phone).exists()
    return JsonResponse({'allowed': bool(exists)})


@csrf_exempt
def api_get_username(request):
    """Return {'username': username} for a given phone number.

    Accepts GET ?phone=... or POST JSON {'phone': '...'}.
    Requires INTERNAL_API_KEY via Authorization/X-API-Key/ ?api_key.
    """
    from django.conf import settings
    if request.method not in ('GET', 'POST'):
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    resp = _require_internal_api_key(request)
    if resp:
        return resp

    # Phone extraction
    phone = request.GET.get('phone')
    if request.method == 'POST' and not phone:
        try:
            body = json.loads(request.body or '{}')
        except Exception:
            body = {}
        phone = body.get('phone') or body.get('phone_number') or request.POST.get('phone') or request.POST.get('phone_number')
    if not phone:
        return JsonResponse({'error': 'phone required'}, status=400)

    # Normalize phone number
    normalized_phone = ''.join(c for c in phone if c.isdigit() or c == '+')
    if normalized_phone.startswith('+'):
        normalized_phone = normalized_phone[1:]

    # Look up username by phone number
    try:
        profile = UserProfile.objects.select_related('user').get(phone_number=normalized_phone)
        return JsonResponse({'username': profile.user.username})
    except UserProfile.DoesNotExist:
        return JsonResponse({'error': 'No user found with this phone number'}, status=404)


@csrf_exempt
def api_get_active_service(request):
    """Return the active service name for a phone number.

    Accepts POST JSON {'phone': '...'}.
    Requires INTERNAL_API_KEY via Authorization/X-API-Key/ ?api_key.
    Returns {'active_service': 'service_name'} or {'active_service': None} if no active service.
    """
    from django.conf import settings
    if request.method not in ('GET', 'POST'):
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    resp = _require_internal_api_key(request)
    if resp:
        return resp

    # Phone extraction
    phone = request.GET.get('phone')
    if request.method == 'POST' and not phone:
        try:
            body = json.loads(request.body or '{}')
        except Exception:
            body = {}
        phone = body.get('phone') or body.get('phone_number') or request.POST.get('phone') or request.POST.get('phone_number')
    if not phone:
        return JsonResponse({'error': 'phone required'}, status=400)

    # Normalize phone number
    normalized_phone = ''.join(c for c in phone if c.isdigit() or c == '+')
    if normalized_phone.startswith('+'):
        normalized_phone = normalized_phone[1:]

    # Find user by phone number
    try:
        profile = UserProfile.objects.select_related('user').get(phone_number=normalized_phone)
        user = profile.user

        # Get active service for this user
        active_service = get_active_service(user)
        if active_service:
            return JsonResponse({'active_service': active_service.name})
        else:
            return JsonResponse({'active_service': None})

    except UserProfile.DoesNotExist:
        return JsonResponse({'error': 'No user found with this phone number'}, status=404)
    except Exception as e:
        return JsonResponse({'error': f'Error retrieving active service: {str(e)}'}, status=500)


@csrf_exempt
def api_reset_password(request):
    """Reset user password by username.

    Accepts POST JSON {'username': '...', 'password': '...'}.
    Requires INTERNAL_API_KEY via Authorization/X-API-Key/ ?api_key.
    """
    from django.conf import settings
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    resp = _require_internal_api_key(request)
    if resp:
        return resp

    # Extract data from POST
    try:
        if request.content_type == 'application/json':
            body = json.loads(request.body or '{}')
            username = body.get('username')
            password = body.get('password')
        else:
            username = request.POST.get('username')
            password = request.POST.get('password')
    except Exception:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if not username:
        return JsonResponse({'error': 'username required'}, status=400)

    if not password:
        return JsonResponse({'error': 'password required'}, status=400)

    # Validate password strength (basic check)
    if len(password) < 8:
        return JsonResponse({'error': 'Password must be at least 8 characters long'}, status=400)

    # Look up user by username
    try:
        from django.contrib.auth.models import User
        user = User.objects.get(username=username)

        # Set new password (Django automatically hashes it)
        user.set_password(password)
        user.save()

        return JsonResponse({'success': True, 'message': f'Password reset successfully for user {username}'})

    except User.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': f'Password reset failed: {str(e)}'}, status=500)


# ---- Google OAuth and API endpoints ----


@login_required
def google_oauth_start(request):
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [request.build_absolute_uri(reverse('core:google_oauth_callback'))],
            }
        },
        scopes=[
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/calendar",
        ],
    )
    flow.redirect_uri = request.build_absolute_uri(reverse('core:google_oauth_callback'))
    authorization_url, state = flow.authorization_url(access_type='offline', prompt='consent')
    request.session['google_oauth_state'] = state
    return redirect(authorization_url)


def google_oauth_callback(request):
    # Check if user is authenticated
    if not request.user.is_authenticated:
        messages.error(request, "You must be logged in to complete OAuth.")
        return redirect('core:login')

    state = request.session.get('google_oauth_state')
    if not state:
        messages.error(request, "OAuth session expired. Please try again.")
        return redirect('core:dashboard')

    try:
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [request.build_absolute_uri(reverse('core:google_oauth_callback'))],
                }
            },
            scopes=[
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/calendar",
            ],
            state=state,
        )
        flow.redirect_uri = request.build_absolute_uri(reverse('core:google_oauth_callback'))
        authorization_response = request.build_absolute_uri()
        flow.fetch_token(authorization_response=authorization_response)
        creds = flow.credentials

        # Save Google credentials
        GoogleCredential.objects.update_or_create(
            user=request.user,
            defaults={
                'refresh_token': creds.refresh_token,
                'access_token': creds.token,
                'token_expiry': creds.expiry,
                'scopes': ' '.join(creds.scopes or []),
            },
        )

        # Check for pending service unlock
        pending_service = request.session.get('pending_service_unlock')
        if pending_service:
            service_slug = pending_service['service_slug']
            try:
                service = Service.objects.get(slug=service_slug, is_active=True)

                # Check if user already has this service
                if not UserWorkflow.objects.filter(user=request.user, service=service).exists():
                    # Mark service as unlocked without n8n resources (handled by webapp)
                    UserWorkflow.objects.update_or_create(
                        user=request.user,
                        service=service,
                        defaults={
                            'name': f"{service.name} - {request.user.username}",
                            'active': True,
                            'n8n_workflow_id': None,  # No n8n workflow needed
                            'n8n_credential_id': None,  # No n8n credentials needed
                        }
                    )
                    messages.success(request, f"Successfully unlocked {service.name}!")

                # Clear pending service unlock
                request.session.pop('pending_service_unlock', None)

            except Service.DoesNotExist:
                messages.error(request, f"Service {service_slug} not found.")
            except Exception as e:
                messages.error(request, f"Failed to unlock service: {str(e)}")
        else:
            messages.success(request, "Google account connected successfully!")

        # Clear OAuth state
        request.session.pop('google_oauth_state', None)

    except Exception as e:
        messages.error(request, f"OAuth failed: {str(e)}")

    return redirect('core:dashboard')


@csrf_exempt
def api_google_gmail_send(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    resp = _require_internal_api_key(request)
    if resp:
        return resp
    try:
        payload = json.loads(request.body or '{}')
    except Exception:
        return JsonResponse({'error': 'invalid json'}, status=400)
    username = payload.get('external_user_id') or payload.get('username')
    to = payload.get('to')
    subject = payload.get('subject')
    body = payload.get('body')
    content_type = payload.get('content_type')  # optional: 'html' or 'plain'
    if not all([username, to, subject, body]):
        return JsonResponse({'error': 'missing fields'}, status=400)
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return JsonResponse({'error': 'user not found'}, status=404)
    service = get_gmail_service(user)
    # Build message honoring optional content_type
    if content_type == 'html':
        message = MIMEText(body or '', 'html')
    else:
        message = MIMEText(body or '', 'plain')
    message['to'] = to
    message['subject'] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    sent = service.users().messages().send(userId='me', body={'raw': raw}).execute()
    return JsonResponse({'id': sent.get('id')})


@csrf_exempt
def api_google_gmail_messages(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    resp = _require_internal_api_key(request)
    if resp:
        return resp
    username = request.GET.get('external_user_id') or request.GET.get('username')
    if not username:
        return JsonResponse({'error': 'external_user_id required'}, status=400)
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return JsonResponse({'error': 'user not found'}, status=404)
    service = get_gmail_service(user)
    q = request.GET.get('q')
    label_ids = request.GET.getlist('labelIds') or None
    messages = service.users().messages().list(userId='me', q=q, labelIds=label_ids, maxResults=20).execute()
    return JsonResponse(messages)


@csrf_exempt
def api_google_gmail_reply(request):
    """Reply to an email message."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    resp = _require_internal_api_key(request)
    if resp:
        return resp
    try:
        payload = json.loads(request.body or '{}')
    except Exception:
        return JsonResponse({'error': 'invalid json'}, status=400)

    username = payload.get('external_user_id') or payload.get('username')
    message_id = payload.get('message_id') or payload.get('thread_id')
    body = payload.get('body')
    subject = payload.get('subject')
    content_type = payload.get('content_type')  # optional: 'html' or 'plain'

    if not all([username, message_id, body]):
        return JsonResponse({'error': 'username, message_id/thread_id, and body required'}, status=400)

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return JsonResponse({'error': 'user not found'}, status=404)

    service = get_gmail_service(user)

    try:
        # Get the original message
        message = service.users().messages().get(userId='me', id=message_id, format='full').execute()
        thread_id = message['threadId']

        # Create reply message honoring content_type
        if content_type == 'html':
            reply = MIMEText(body or '', 'html')
        else:
            reply = MIMEText(body or '', 'plain')

        # Set reply headers
        reply['to'] = message['payload']['headers'][0]['value']  # Get original sender
        reply['subject'] = subject or f"Re: {message['payload']['headers'][1]['value']}"  # Get original subject
        reply['In-Reply-To'] = message['payload']['headers'][2]['value'] if len(message['payload']['headers']) > 2 else ''
        reply['References'] = message['payload']['headers'][2]['value'] if len(message['payload']['headers']) > 2 else ''

        raw = base64.urlsafe_b64encode(reply.as_bytes()).decode()
        sent = service.users().messages().send(
            userId='me',
            body={
                'raw': raw,
                'threadId': thread_id
            }
        ).execute()
        return JsonResponse({'id': sent.get('id'), 'threadId': thread_id})

    except Exception as e:
        return JsonResponse({'error': f'Failed to send reply: {str(e)}'}, status=500)


@csrf_exempt
def api_google_gmail_draft(request):
    """Create a draft email."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    resp = _require_internal_api_key(request)
    if resp:
        return resp
    try:
        payload = json.loads(request.body or '{}')
    except Exception:
        return JsonResponse({'error': 'invalid json'}, status=400)

    username = payload.get('external_user_id') or payload.get('username')
    to = payload.get('to')
    subject = payload.get('subject')
    body = payload.get('body')
    content_type = payload.get('content_type')  # optional: 'html' or 'plain'

    if not all([username, to, subject, body]):
        return JsonResponse({'error': 'username, to, subject, and body required'}, status=400)

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return JsonResponse({'error': 'user not found'}, status=404)

    service = get_gmail_service(user)

    try:
        if content_type == 'html':
            message = MIMEText(body or '', 'html')
        else:
            message = MIMEText(body or '', 'plain')
        message['to'] = to
        message['subject'] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        draft = service.users().drafts().create(
            userId='me',
            body={'message': {'raw': raw}}
        ).execute()
        return JsonResponse({'id': draft.get('id'), 'message': draft.get('message', {})})

    except Exception as e:
        return JsonResponse({'error': f'Failed to create draft: {str(e)}'}, status=500)


@csrf_exempt
def api_google_gmail_labels(request):
    """Get Gmail labels."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    resp = _require_internal_api_key(request)
    if resp:
        return resp

    username = request.GET.get('external_user_id') or request.GET.get('username')
    if not username:
        return JsonResponse({'error': 'external_user_id required'}, status=400)

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return JsonResponse({'error': 'user not found'}, status=404)

    service = get_gmail_service(user)

    try:
        labels = service.users().labels().list(userId='me').execute()
        return JsonResponse({'labels': labels.get('labels', [])})

    except Exception as e:
        return JsonResponse({'error': f'Failed to get labels: {str(e)}'}, status=500)


@csrf_exempt
def api_google_gmail_modify_labels(request):
    """Add or remove labels from messages."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    resp = _require_internal_api_key(request)
    if resp:
        return resp
    try:
        payload = json.loads(request.body or '{}')
    except Exception:
        return JsonResponse({'error': 'invalid json'}, status=400)

    username = payload.get('external_user_id') or payload.get('username')
    message_ids = payload.get('message_ids', [])
    add_labels = payload.get('add_labels', [])
    remove_labels = payload.get('remove_labels', [])

    if not username:
        return JsonResponse({'error': 'username required'}, status=400)
    if not message_ids:
        return JsonResponse({'error': 'message_ids required'}, status=400)

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return JsonResponse({'error': 'user not found'}, status=404)

    service = get_gmail_service(user)

    try:
        results = []
        for message_id in message_ids:
            body = {}
            if add_labels:
                body['addLabelIds'] = add_labels
            if remove_labels:
                body['removeLabelIds'] = remove_labels

            result = service.users().messages().modify(
                userId='me',
                id=message_id,
                body=body
            ).execute()
            results.append({'message_id': message_id, 'result': result})

        return JsonResponse({'results': results})

    except Exception as e:
        return JsonResponse({'error': f'Failed to modify labels: {str(e)}'}, status=500)


@csrf_exempt
def api_google_calendar_events_delete(request):
    """Delete a calendar event."""
    if request.method != 'DELETE':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    resp = _require_internal_api_key(request)
    if resp:
        return resp

    event_id = request.GET.get('event_id')
    username = request.GET.get('external_user_id') or request.GET.get('username')

    if not username or not event_id:
        return JsonResponse({'error': 'username and event_id required'}, status=400)

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return JsonResponse({'error': 'user not found'}, status=404)

    service = get_calendar_service(user)

    try:
        result = service.events().delete(calendarId='primary', eventId=event_id).execute()
        return JsonResponse({'status': 'deleted', 'event_id': event_id})

    except Exception as e:
        return JsonResponse({'error': f'Failed to delete event: {str(e)}'}, status=500)


@csrf_exempt
def api_google_calendar_events(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    resp = _require_internal_api_key(request)
    if resp:
        return resp
    username = request.GET.get('external_user_id') or request.GET.get('username')
    if not username:
        return JsonResponse({'error': 'external_user_id required'}, status=400)
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return JsonResponse({'error': 'user not found'}, status=404)
    service = get_calendar_service(user)
    time_min = request.GET.get('timeMin')
    time_max = request.GET.get('timeMax')
    events = service.events().list(
        calendarId='primary',
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy='startTime',
    ).execute()
    # Store sync token if provided
    if events.get('nextSyncToken'):
        GoogleCredential.objects.filter(user=user).update(calendar_sync_token=events['nextSyncToken'])
    return JsonResponse({'items': events.get('items', []), 'nextSyncToken': events.get('nextSyncToken')})


@csrf_exempt
def api_google_calendar_events_post(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    resp = _require_internal_api_key(request)
    if resp:
        return resp
    try:
        payload = json.loads(request.body or '{}')
    except Exception:
        return JsonResponse({'error': 'invalid json'}, status=400)
    username = payload.get('external_user_id') or payload.get('username')
    event = payload.get('event')
    if not username or not isinstance(event, dict):
        return JsonResponse({'error': 'external_user_id and event required'}, status=400)
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return JsonResponse({'error': 'user not found'}, status=404)
    service = get_calendar_service(user)
    if event.get('id'):
        result = service.events().update(calendarId='primary', eventId=event['id'], body=event).execute()
    else:
        result = service.events().insert(calendarId='primary', body=event).execute()
    return JsonResponse(result)


@csrf_exempt
def api_google_gmail_watch(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    resp = _require_internal_api_key(request)
    if resp:
        return resp
    try:
        payload = json.loads(request.body or '{}')
    except Exception:
        return JsonResponse({'error': 'invalid json'}, status=400)
    username = payload.get('external_user_id') or payload.get('username')
    topic = payload.get('topicName')
    if not username or not topic:
        return JsonResponse({'error': 'external_user_id and topicName required'}, status=400)
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return JsonResponse({'error': 'user not found'}, status=404)
    service = get_gmail_service(user)
    watch_body = {'topicName': topic}
    watch_resp = service.users().watch(userId='me', body=watch_body).execute()
    GoogleCredential.objects.filter(user=user).update(gmail_history_id=watch_resp.get('historyId'))
    return JsonResponse(watch_resp)


@csrf_exempt
def api_google_calendar_watch(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    resp = _require_internal_api_key(request)
    if resp:
        return resp
    try:
        payload = json.loads(request.body or '{}')
    except Exception:
        return JsonResponse({'error': 'invalid json'}, status=400)
    username = payload.get('external_user_id') or payload.get('username')
    address = payload.get('address')
    if not username or not address:
        return JsonResponse({'error': 'external_user_id and address required'}, status=400)
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return JsonResponse({'error': 'user not found'}, status=404)
    service = get_calendar_service(user)
    channel_id = str(uuid.uuid4())
    body = {'id': channel_id, 'type': 'web_hook', 'address': address}
    watch_resp = service.events().watch(calendarId='primary', body=body).execute()
    expiration = watch_resp.get('expiration')
    exp_dt = (
        datetime.fromtimestamp(int(expiration) / 1000, tz=timezone.utc)
        if expiration
        else None
    )
    GoogleCredential.objects.filter(user=user).update(
        calendar_channel_id=watch_resp.get('id'),
        calendar_resource_id=watch_resp.get('resourceId'),
        calendar_channel_expiration=exp_dt,
    )
    return JsonResponse(watch_resp)


@csrf_exempt
def google_calendar_webhook(request):
    channel_id = request.headers.get('X-Goog-Channel-ID')
    if not channel_id:
        return HttpResponse(status=400)
    try:
        cred = GoogleCredential.objects.get(calendar_channel_id=channel_id)
    except GoogleCredential.DoesNotExist:
        return HttpResponse(status=404)
    # In a full implementation you'd trigger sync logic here.
    return JsonResponse({'status': 'received'})
