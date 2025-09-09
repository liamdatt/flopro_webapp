from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django import forms
import json

from .models import Service, UserWorkflow, BudgetService, Transaction, UserProfile
from .provisioning import provision_user_workflow, toggle_user_service, get_active_service
from .n8n_client import N8nClient


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
                    getattr(request.user, 'profile', None) and request.user.profile.phone_number
                )

                if not phone:
                    messages.error(request, 'Phone number is required.')
                    raise ValueError('Missing phone number')

                # Normalize and save phone on user if changed or missing
                normalized_phone = ''.join(c for c in phone if c.isdigit() or c == '+')
                if normalized_phone.startswith('+'):
                    normalized_phone = normalized_phone[1:]
                if getattr(request.user, 'profile', None) is not None:
                    if request.user.profile.phone_number != normalized_phone:
                        existing_profile = UserProfile.objects.filter(phone_number=normalized_phone).exclude(user=request.user).first()
                        if existing_profile:
                            messages.error(request, 'This phone number is already in use by another account. Please use a different phone number.')
                            raise ValueError('Phone number already in use')
                        request.user.profile.phone_number = normalized_phone
                        request.user.profile.save(update_fields=['phone_number'])

                # Continue with OAuth provisioning
                return handle_oauth_flow(request, service)

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
def toggle_service(request, service_slug):
    """Toggle between user services."""
    service = get_object_or_404(Service, slug=service_slug, is_active=True)

    if toggle_user_service(user=request.user, service=service):
        messages.success(request, f"Switched to {service.name}")
    else:
        messages.error(request, f"You haven't unlocked {service.name} yet")

    return redirect('dashboard')


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
    """Handle OAuth2 flow for Google services like Gmail and Calendar."""
    # For OAuth2 services, we need to initiate the OAuth flow through n8n
    # This is a simplified implementation - in production you'd want to:
    # 1. Create a temporary credential in n8n with the user's OAuth data
    # 2. Redirect to n8n's OAuth authorization URL
    # 3. Handle the callback and store the final credential ID

    try:
        client = N8nClient()

        # For Google OAuth2, we'll create a credential and let n8n handle the OAuth flow
        # In a real implementation, you'd redirect to n8n's OAuth endpoint
        credential_data = extract_credential_data(request.POST, service)

        # Create the workflow and credential (n8n will handle OAuth completion)
        workflow_id, credential_id = provision_user_workflow(
            user=request.user,
            service=service,
            credential_data=credential_data
        )

        messages.success(request, f"Successfully set up {service.name}! OAuth flow will complete through n8n.")
        return redirect('dashboard')

    except Exception as e:
        messages.error(request, f"OAuth setup failed: {str(e)}")
        return redirect('service_detail', service_slug=service.slug)


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


@csrf_exempt
def api_budget_remaining(request):
    """Return remaining budget for a phone number: budget - sum(transactions)."""
    from django.conf import settings
    if request.method not in ('GET', 'POST'):
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    # Accept X-API-Key, Authorization: Bearer <key>, Authorization: <key>, or ?api_key=
    auth_header = request.headers.get('Authorization')
    bearer = None
    if auth_header:
        parts = auth_header.split(' ', 1)
        if len(parts) == 2 and parts[0].lower() == 'bearer':
            bearer = parts[1].strip()
        else:
            bearer = auth_header.strip()

    api_key = request.headers.get('X-API-Key') or bearer or request.GET.get('api_key')
    if not settings.INTERNAL_API_KEY or api_key != settings.INTERNAL_API_KEY:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

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

    # Accept X-API-Key, Authorization: Bearer <key>, Authorization: <key>, or ?api_key=
    auth_header = request.headers.get('Authorization')
    bearer = None
    if auth_header:
        parts = auth_header.split(' ', 1)
        if len(parts) == 2 and parts[0].lower() == 'bearer':
            bearer = parts[1].strip()
        else:
            bearer = auth_header.strip()

    api_key = request.headers.get('X-API-Key') or bearer or request.GET.get('api_key')
    if not settings.INTERNAL_API_KEY or api_key != settings.INTERNAL_API_KEY:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

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

    # Auth
    auth_header = request.headers.get('Authorization')
    bearer = None
    if auth_header:
        parts = auth_header.split(' ', 1)
        if len(parts) == 2 and parts[0].lower() == 'bearer':
            bearer = parts[1].strip()
        else:
            bearer = auth_header.strip()
    api_key = request.headers.get('X-API-Key') or bearer or request.GET.get('api_key')
    if not settings.INTERNAL_API_KEY or api_key != settings.INTERNAL_API_KEY:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

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

    # Auth
    auth_header = request.headers.get('Authorization')
    bearer = None
    if auth_header:
        parts = auth_header.split(' ', 1)
        if len(parts) == 2 and parts[0].lower() == 'bearer':
            bearer = parts[1].strip()
        else:
            bearer = auth_header.strip()
    api_key = request.headers.get('X-API-Key') or bearer or request.GET.get('api_key')
    if not settings.INTERNAL_API_KEY or api_key != settings.INTERNAL_API_KEY:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

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
def api_reset_password(request):
    """Reset user password by username.

    Accepts POST JSON {'username': '...', 'password': '...'}.
    Requires INTERNAL_API_KEY via Authorization/X-API-Key/ ?api_key.
    """
    from django.conf import settings
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    # Auth
    auth_header = request.headers.get('Authorization')
    bearer = None
    if auth_header:
        parts = auth_header.split(' ', 1)
        if len(parts) == 2 and parts[0].lower() == 'bearer':
            bearer = parts[1].strip()
        else:
            bearer = auth_header.strip()
    api_key = request.headers.get('X-API-Key') or bearer or request.GET.get('api_key')
    if not settings.INTERNAL_API_KEY or api_key != settings.INTERNAL_API_KEY:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

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
