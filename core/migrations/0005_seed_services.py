from django.db import migrations


def seed_services(apps, schema_editor):
    Service = apps.get_model('core', 'Service')

    # Budget Tracker (no external credentials)
    defaults = {
        'name': 'Budget Tracker',
        'description': 'Track your expenses and monthly budget. No external credentials required.',
        'icon': 'fas fa-calculator',
        'template_workflow_id': 0,
        'credential_type': 'none',
        'credential_ui_schema': {
            'phone_number': {
                'type': 'text',
                'label': 'Phone Number',
                'placeholder': '+1 555 123 4567',
                'required': True,
                'help_text': 'Used to identify your account for transactions',
            },
            'budget_amount': {
                'type': 'number',
                'label': 'Monthly Budget',
                'placeholder': 'Enter your monthly budget',
                'required': True,
                'help_text': 'Your monthly spending limit',
            },
        },
        'credential_node_types': [],
        'is_active': True,
    }

    Service.objects.update_or_create(slug='budget-tracker', defaults=defaults)


def unseed_services(apps, schema_editor):
    Service = apps.get_model('core', 'Service')
    Service.objects.filter(slug='budget-tracker').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_userprofile'),
    ]

    operations = [
        migrations.RunPython(seed_services, unseed_services),
    ]


