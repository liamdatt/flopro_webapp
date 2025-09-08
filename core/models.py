from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


# Extend the User model to add phone number
User.add_to_class('phone_number', models.CharField(max_length=20, blank=True, null=True))


class Service(models.Model):
    """Represents a service that users can unlock (e.g., Budget Tracker, CRM, etc.)"""

    slug = models.SlugField(max_length=50, unique=True, help_text="Unique identifier for the service")
    name = models.CharField(max_length=100, help_text="Display name of the service")
    description = models.TextField(help_text="Description of what this service does")
    icon = models.CharField(max_length=50, blank=True, help_text="FontAwesome icon class")

    # n8n-specific fields
    template_workflow_id = models.PositiveIntegerField(help_text="n8n workflow ID of the template")
    credential_type = models.CharField(max_length=50, help_text="n8n credential type (e.g., 'googleOAuth2', 'httpBasicAuth')")
    credential_ui_schema = models.JSONField(help_text="JSON schema for credential input form fields")
    credential_node_types = models.JSONField(help_text="List of n8n node types that use this credential")

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

    # n8n resource IDs
    n8n_workflow_id = models.PositiveIntegerField(help_text="n8n workflow ID")
    n8n_credential_id = models.PositiveIntegerField(help_text="n8n credential ID")

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
