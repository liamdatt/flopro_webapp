from typing import Optional
from .models import Service, UserWorkflow


def unlock_service_for_user(*, user, service: Service) -> bool:
    """
    Unlock a service for a user without n8n integration.

    Args:
        user: Django User instance
        service: Service instance to unlock

    Returns:
        True if successful, False if service is already unlocked
    """
    # Check if user already has this service
    if UserWorkflow.objects.filter(user=user, service=service).exists():
        return False

    # Check if user has any active services - if not, make this one active
    has_active_service = UserWorkflow.objects.filter(user=user, active=True).exists()
    is_first_service = not UserWorkflow.objects.filter(user=user).exists()

    # Create UserWorkflow record
    UserWorkflow.objects.create(
        user=user,
        service=service,
        name=f"{service.name} - {user.username}",
        active=is_first_service or not has_active_service,  # Active if first service or no active services
        # n8n fields remain None since we're not using n8n
        n8n_workflow_id=None,
        n8n_credential_id=None,
    )

    return True


def toggle_user_service(*, user, service: Service) -> bool:
    """
    Toggle a service's active status for a user.

    This deactivates all other workflows and activates the specified service's workflow.

    Args:
        user: Django User instance
        service: Service to activate

    Returns:
        True if successful, False if the user doesn't have this service
    """
    try:
        # Get the user's workflow for this service
        user_workflow = UserWorkflow.objects.get(user=user, service=service)
    except UserWorkflow.DoesNotExist:
        return False

    # Deactivate all user's workflows in database
    UserWorkflow.objects.filter(user=user, active=True).update(active=False)

    # Activate the selected workflow
    user_workflow.active = True
    user_workflow.save(update_fields=["active"])

    return True


def get_active_service(user) -> Optional[Service]:
    """Get the currently active service for a user"""
    try:
        user_workflow = UserWorkflow.objects.get(user=user, active=True)
        return user_workflow.service
    except UserWorkflow.DoesNotExist:
        return None


def cleanup_user_workflows(user) -> None:
    """
    Clean up all user workflows.
    """
    # Remove from database
    UserWorkflow.objects.filter(user=user).delete()
