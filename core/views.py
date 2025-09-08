from django.shortcuts import render

def landing_page(request):
    """Landing page view for the Flopro WA application."""
    return render(request, 'core/landing_page.html')
