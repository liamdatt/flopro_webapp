from django.contrib import admin
from .models import Service, UserWorkflow


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'credential_type', 'is_active', 'created_at']
    list_filter = ['is_active', 'credential_type', 'created_at']
    search_fields = ['name', 'slug', 'description']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Basic Information', {
            'fields': ('slug', 'name', 'description', 'icon')
        }),
        ('n8n Configuration', {
            'fields': ('template_workflow_id', 'credential_type', 'credential_ui_schema', 'credential_node_types'),
            'classes': ('collapse',)
        }),
        ('Settings', {
            'fields': ('is_active',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )


@admin.register(UserWorkflow)
class UserWorkflowAdmin(admin.ModelAdmin):
    list_display = ['user', 'service', 'name', 'active', 'created_at']
    list_filter = ['active', 'service', 'created_at']
    search_fields = ['user__username', 'service__name', 'name']
    readonly_fields = ['created_at', 'updated_at', 'n8n_workflow_id', 'n8n_credential_id']
    fieldsets = (
        ('User & Service', {
            'fields': ('user', 'service')
        }),
        ('n8n Resources', {
            'fields': ('n8n_workflow_id', 'n8n_credential_id', 'name'),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('active',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
