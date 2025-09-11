from django.contrib import admin
from .models import Service, UserWorkflow, BudgetService, Transaction


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'slug', 'description']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Basic Information', {
            'fields': ('slug', 'name', 'description', 'icon')
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


@admin.register(BudgetService)
class BudgetServiceAdmin(admin.ModelAdmin):
    list_display = ['user', 'phone_number', 'budget_amount', 'updated_at']
    list_filter = ['updated_at']
    search_fields = ['user__username', 'phone_number']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['phone_number', 'name', 'date', 'total', 'created_at']
    list_filter = ['date', 'created_at']
    search_fields = ['phone_number', 'name']
    date_hierarchy = 'date'
