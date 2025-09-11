from typing import Dict, List, Tuple, Any
from django.utils import timezone
from .n8n_client import N8nClient
from .models import Service, UserWorkflow


def _apply_credentials_to_workflow(
    template_workflow: Dict[str, Any],
    *,
    new_name: str,
    credential_type: str,
    credential_id: int,
    credential_node_types: List[str] | None = None,
) -> Dict[str, Any]:
    """
    Modify a workflow template to use a specific credential.

    Args:
        template_workflow: The n8n workflow JSON from the template
        new_name: Name for the new workflow
        credential_type: The credential type (e.g., 'googleOAuth2')
        credential_id: The n8n credential ID to use

    Returns:
        Modified workflow JSON ready for creation
    """
    # Create a copy of the template, excluding template-specific fields
    workflow = {k: v for k, v in template_workflow.items()
                if k not in {"id", "versionId", "createdAt", "updatedAt"}}

    # Set the new workflow name
    workflow["name"] = new_name

    # Ensure workflow starts inactive
    workflow["active"] = False

    # Update credentials in all nodes that use this credential type
    for node in workflow.get("nodes", []):
        credentials = node.setdefault("credentials", {})
        node_type = node.get("type")

        # Case 1: Node already declares this credential type -> overwrite
        if credential_type in credentials:
            credentials[credential_type] = {"id": credential_id}
            continue

        # Case 2: Node type is listed as requiring this credential -> set
        if credential_node_types and node_type in credential_node_types:
            if credentials:
                # Overwrite all existing credential keys for this node
                for key in list(credentials.keys()):
                    credentials[key] = {"id": credential_id}
            else:
                # Fallback: set under the service credential_type key
                credentials[credential_type] = {"id": credential_id}

    return workflow
def _apply_credentials_map_to_workflow(
    template_workflow: Dict[str, Any],
    *,
    new_name: str,
    node_type_to_credential_id: Dict[str, int],
) -> Dict[str, Any]:
    """Modify a workflow template to use specific credential ids per node type.

    Any node whose `type` key matches a key in node_type_to_credential_id will have
    all existing credential entries overwritten with {"id": that_credential_id}.
    """
    workflow = {k: v for k, v in template_workflow.items()
                if k not in {"id", "versionId", "createdAt", "updatedAt"}}

    workflow["name"] = new_name
    workflow["active"] = False

    for node in workflow.get("nodes", []):
        node_type = node.get("type")
        if not node_type:
            continue
        if node_type not in node_type_to_credential_id:
            continue

        cred_id = node_type_to_credential_id[node_type]
        credentials = node.setdefault("credentials", {})
        if credentials:
            for key in list(credentials.keys()):
                credentials[key] = {"id": cred_id}
        else:
            # Fallback: set a generic credential entry if none exist. Many n8n nodes
            # require the correct key name, so this may be ignored by n8n if absent.
            credentials["default"] = {"id": cred_id}

    return workflow



def provision_user_workflow(
    *,
    user,
    service: Service,
    credential_data: Dict[str, Any]
) -> Tuple[int, int]:
    """
    Provision a new workflow for a user based on a service template.

    Args:
        user: Django User instance
        service: Service instance with template information
        credential_data: User-provided credential data

    Returns:
        Tuple of (workflow_id, credential_id)
    """
    client = N8nClient()

    # Generate unique names for n8n resources
    timestamp = int(timezone.now().timestamp())
    cred_name = f"{service.slug}:{user.id}:{timestamp}"
    workflow_name = f"{service.name} - {user.username} (#{user.id})"

    # Create credential in n8n
    credential = client.create_credential(
        name=cred_name,
        cred_type=service.credential_type,
        data=credential_data,
        node_types=service.credential_node_types
    )
    credential_id = credential["id"]

    # Fetch template workflow
    template = client.get_workflow(service.template_workflow_id)

    # Apply credentials to workflow template
    workflow_payload = _apply_credentials_to_workflow(
        template_workflow=template,
        new_name=workflow_name,
        credential_type=service.credential_type,
        credential_id=credential_id,
        credential_node_types=service.credential_node_types,
    )

    # Create the workflow
    created_workflow = client.create_workflow(workflow_payload)
    workflow_id = created_workflow["id"]

    # Activate the workflow
    client.activate_workflow(workflow_id)

    # Save to database
    UserWorkflow.objects.create(
        user=user,
        service=service,
        n8n_workflow_id=workflow_id,
        n8n_credential_id=credential_id,
        name=workflow_name,
        active=True,
    )

    return workflow_id, credential_id


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
    client = N8nClient()

    try:
        # Get the user's workflow for this service
        user_workflow = UserWorkflow.objects.get(user=user, service=service)
    except UserWorkflow.DoesNotExist:
        return False

    # Deactivate all user's workflows in n8n and database
    for uw in UserWorkflow.objects.filter(user=user, active=True):
        try:
            client.deactivate_workflow(uw.n8n_workflow_id)
        except Exception:
            # Log error but continue - workflow might already be inactive
            pass
        uw.active = False
        uw.save(update_fields=["active"])

    # Activate the selected workflow
    client.activate_workflow(user_workflow.n8n_workflow_id)
    user_workflow.active = True
    user_workflow.save(update_fields=["active"])

    return True


def get_active_service(user) -> Service | None:
    """Get the currently active service for a user"""
    try:
        user_workflow = UserWorkflow.objects.get(user=user, active=True)
        return user_workflow.service
    except UserWorkflow.DoesNotExist:
        return None


def cleanup_user_workflows(user) -> None:
    """
    Clean up all n8n resources for a user (workflows and credentials).
    Use with caution - this permanently deletes resources.
    """
    client = N8nClient()

    for user_workflow in UserWorkflow.objects.filter(user=user):
        try:
            # Deactivate and delete workflow
            client.deactivate_workflow(user_workflow.n8n_workflow_id)
            client.delete_workflow(user_workflow.n8n_workflow_id)

            # Delete credential
            client.delete_credential(user_workflow.n8n_credential_id)

        except Exception:
            # Log error but continue cleanup
            pass

    # Remove from database
    UserWorkflow.objects.filter(user=user).delete()


def provision_user_workflow_with_credentials_map(
    *,
    user,
    service: Service,
    node_type_to_credential_id: Dict[str, int],
) -> Tuple[int, int]:
    """Provision a workflow using a mapping of node type -> credential id.

    Returns (workflow_id, primary_credential_id), where primary_credential_id is the
    credential id associated to Gmail if present, otherwise any one of provided ids.
    """
    client = N8nClient()

    workflow_name = f"{service.name} - {user.username} (#{user.id})"
    template = client.get_workflow(service.template_workflow_id)

    workflow_payload = _apply_credentials_map_to_workflow(
        template_workflow=template,
        new_name=workflow_name,
        node_type_to_credential_id=node_type_to_credential_id,
    )

    created_workflow = client.create_workflow(workflow_payload)
    workflow_id = created_workflow["id"]
    client.activate_workflow(workflow_id)

    # Choose a primary credential id to store (prefer Gmail if present)
    primary_cred_id = (
        node_type_to_credential_id.get("n8n-nodes-base.gmailTool")
        or next(iter(node_type_to_credential_id.values()))
    )

    UserWorkflow.objects.update_or_create(
        user=user,
        service=service,
        defaults={
            "n8n_workflow_id": workflow_id,
            "n8n_credential_id": primary_cred_id,
            "name": workflow_name,
            "active": True,
        },
    )

    return workflow_id, primary_cred_id


def provision_user_workflow_with_credential_id(
    *,
    user,
    service: Service,
    credential_id: int,
) -> Tuple[int, int]:
    """Provision a workflow using an existing n8n credential id.

    Creates a copy of the template workflow, wires the provided credential id
    to all relevant nodes, activates it, and stores the mapping.
    """
    client = N8nClient()

    # Generate a workflow name
    timestamp = int(timezone.now().timestamp())
    workflow_name = f"{service.name} - {user.username} (#{user.id})"

    # Fetch template workflow
    template = client.get_workflow(service.template_workflow_id)

    # Apply credentials to workflow template
    workflow_payload = _apply_credentials_to_workflow(
        template_workflow=template,
        new_name=workflow_name,
        credential_type=service.credential_type,
        credential_id=credential_id,
        credential_node_types=service.credential_node_types,
    )

    # Create and activate the workflow
    created_workflow = client.create_workflow(workflow_payload)
    workflow_id = created_workflow["id"]
    client.activate_workflow(workflow_id)

    # Persist
    UserWorkflow.objects.update_or_create(
        user=user,
        service=service,
        defaults={
            "n8n_workflow_id": workflow_id,
            "n8n_credential_id": credential_id,
            "name": workflow_name,
            "active": True,
        },
    )

    return workflow_id, credential_id
