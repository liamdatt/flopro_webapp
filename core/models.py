from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class UserProfile(models.Model):
    """Profile data for a Django auth user (e.g., phone number)."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone_number = models.CharField(max_length=20, blank=True, null=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile for {self.user.username}"


class Service(models.Model):
    """Represents a service that users can unlock (e.g., Budget Tracker, CRM, etc.)"""

    slug = models.SlugField(max_length=50, unique=True, help_text="Unique identifier for the service")
    name = models.CharField(max_length=100, help_text="Display name of the service")
    description = models.TextField(help_text="Description of what this service does")
    icon = models.CharField(max_length=50, blank=True, help_text="FontAwesome icon class")

    # Service is now purely informational - all functionality handled by webapp

    # Service status
    is_active = models.BooleanField(default=True, help_text="Whether this service is available to users")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class UserWorkflow(models.Model):
    """Links users to their provisioned n8n workflows and credentials"""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='workflows')
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='user_workflows')

    # n8n resource IDs (optional for services that don't use n8n)
    n8n_workflow_id = models.PositiveIntegerField(help_text="n8n workflow ID", null=True, blank=True)
    n8n_credential_id = models.PositiveIntegerField(help_text="n8n credential ID", null=True, blank=True)

    # Workflow metadata
    name = models.CharField(max_length=200, help_text="Name of the workflow in n8n")
    active = models.BooleanField(default=False, help_text="Whether this workflow is currently active")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.service.name}"

    class Meta:
        unique_together = ['user', 'service']
        ordering = ['-created_at']


class GoogleCredential(models.Model):
    """Stores Google OAuth tokens and sync state for a user."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='google_credential')
    refresh_token = models.TextField(help_text="Long-lived refresh token")
    access_token = models.TextField(blank=True, null=True, help_text="Short-lived access token")
    token_expiry = models.DateTimeField(blank=True, null=True, help_text="Access token expiry")
    scopes = models.TextField(blank=True, help_text="Space-separated OAuth scopes")

    # Gmail incremental sync
    gmail_history_id = models.CharField(max_length=255, blank=True, null=True)

    # Calendar watch channel metadata
    calendar_channel_id = models.CharField(max_length=255, blank=True, null=True)
    calendar_resource_id = models.CharField(max_length=255, blank=True, null=True)
    calendar_channel_expiration = models.DateTimeField(blank=True, null=True)
    calendar_sync_token = models.CharField(max_length=255, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Google creds for {self.user.username}"


class BudgetService(models.Model):
    """Stores per-user budget configuration for the Budget Tracker service."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='budget_profiles')
    phone_number = models.CharField(max_length=20, help_text="Normalized phone number used as identifier")
    budget_amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Monthly budget amount")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['user', 'phone_number']
        ordering = ['-updated_at']

    def __str__(self):
        return f"Budget for {self.user.username} ({self.phone_number})"


class Transaction(models.Model):
    """Stores transactions tied to a phone number for the Budget Tracker service."""

    phone_number = models.CharField(max_length=20, db_index=True)
    name = models.CharField(max_length=255)
    date = models.DateField()
    total = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['phone_number', 'date']),
        ]
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.name} ({self.phone_number}) - {self.total}"
