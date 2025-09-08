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
    path('service/<slug:service_slug>/unlock/', views.unlock_service, name='unlock_service'),
    path('service/<slug:service_slug>/toggle/', views.toggle_service, name='toggle_service'),
    path('webhook/<int:workflow_id>/', views.n8n_webhook, name='n8n_webhook'),
]
