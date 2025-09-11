from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.landing_page, name='landing_page'),
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('service/<slug:service_slug>/', views.service_detail, name='service_detail'),
    path('service/<slug:service_slug>/overview/', views.service_overview, name='service_overview'),
    path('service/<slug:service_slug>/budget/update/', views.update_budget, name='update_budget'),
    path('service/<slug:service_slug>/transactions/<int:tx_id>/delete/', views.delete_transaction, name='delete_transaction'),
    path('service/<slug:service_slug>/unlock/', views.unlock_service, name='unlock_service'),
    path('service/<slug:service_slug>/toggle/', views.toggle_service, name='toggle_service'),
    path('oauth/callback/<slug:service_slug>/', views.oauth_callback, name='oauth_callback'),
    path('webhook/<int:workflow_id>/', views.n8n_webhook, name='n8n_webhook'),
    # Internal APIs for Budget Tracker (called by n8n)
    path('api/budget/remaining/', views.api_budget_remaining, name='api_budget_remaining'),
    path('api/budget/transactions/add/', views.api_add_transaction, name='api_add_transaction'),
    path('api/phone/allowed/', views.api_phone_allowed, name='api_phone_allowed'),
    path('api/phone/username/', views.api_get_username, name='api_get_username'),
    path('api/user/reset-password/', views.api_reset_password, name='api_reset_password'),
    path('account/delete/', views.delete_account, name='delete_account'),
    # Google OAuth
    path('google/oauth/start/', views.google_oauth_start, name='google_oauth_start'),
    path('google/oauth/callback/', views.google_oauth_callback, name='google_oauth_callback'),
    # Google API endpoints for n8n
    path('api/google/gmail/send', views.api_google_gmail_send, name='api_google_gmail_send'),
    path('api/google/gmail/reply', views.api_google_gmail_reply, name='api_google_gmail_reply'),
    path('api/google/gmail/draft', views.api_google_gmail_draft, name='api_google_gmail_draft'),
    path('api/google/gmail/labels', views.api_google_gmail_labels, name='api_google_gmail_labels'),
    path('api/google/gmail/modify-labels', views.api_google_gmail_modify_labels, name='api_google_gmail_modify_labels'),
    path('api/google/gmail/messages', views.api_google_gmail_messages, name='api_google_gmail_messages'),
    path('api/google/calendar/events', views.api_google_calendar_events, name='api_google_calendar_events'),
    path('api/google/calendar/events/post', views.api_google_calendar_events_post, name='api_google_calendar_events_post'),
    path('api/google/calendar/events/delete', views.api_google_calendar_events_delete, name='api_google_calendar_events_delete'),
    path('api/google/gmail/watch', views.api_google_gmail_watch, name='api_google_gmail_watch'),
    path('api/google/calendar/watch', views.api_google_calendar_watch, name='api_google_calendar_watch'),
    path('webhooks/google/calendar', views.google_calendar_webhook, name='google_calendar_webhook'),
]
