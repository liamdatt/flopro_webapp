from django.db import migrations


def seed_services(apps, schema_editor):
    Service = apps.get_model('core', 'Service')
    defaults = {
        'name': 'Ultimate Personal Assistant',
        'description': 'AI assistant that reads your Gmail and manages Google Calendar events.',
        'icon': 'fas fa-user-astronaut',
        'template_workflow_id': 2,
        'credential_type': 'googleOAuth2',
        'credential_ui_schema': {
            'phone_number': {
                'type': 'text',
                'label': 'Phone Number',
                'placeholder': '+1 555 123 4567',
                'required': True,
                'help_text': 'Used to identify your account for assistant messages',
            },
        },
        'credential_node_types': [
            'n8n-nodes-base.gmail',
            'n8n-nodes-base.googleCalendar',
        ],
        'is_active': True,
    }
    Service.objects.update_or_create(slug='ultimate-personal-assistant', defaults=defaults)


def unseed_services(apps, schema_editor):
    Service = apps.get_model('core', 'Service')
    Service.objects.filter(slug='ultimate-personal-assistant').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_alter_userprofile_phone_number'),
    ]

    operations = [
        migrations.RunPython(seed_services, unseed_services),
    ]
