from django.apps import AppConfig
from django.db.utils import OperationalError, ProgrammingError


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        """Register signals and ensure default services exist."""
        # Register signals
        from . import signals  # noqa

        # Ensure the Ultimate Personal Assistant service is seeded for existing databases
        try:
            from .models import Service

            Service.objects.get_or_create(
                slug="ultimate-personal-assistant",
                defaults={
                    "name": "Ultimate Personal Assistant",
                    "description": "AI assistant that reads your Gmail and manages Google Calendar events.",
                    "icon": "fas fa-user-astronaut",
                    "template_workflow_id": 2,
                    "credential_type": "googleOAuth2",
                    "credential_ui_schema": {
                        "phone_number": {
                            "type": "text",
                            "label": "Phone Number",
                            "placeholder": "+1 555 123 4567",
                            "required": True,
                            "help_text": "Used to identify your account for assistant messages",
                        }
                    },
                    "credential_node_types": [
                        "n8n-nodes-base.gmail",
                        "n8n-nodes-base.googleCalendar",
                    ],
                    "is_active": True,
                },
            )
        except (OperationalError, ProgrammingError):
            # Database not ready (migrations haven't run yet)
            pass
