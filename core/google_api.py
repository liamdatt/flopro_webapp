from __future__ import annotations

from django.conf import settings
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from .models import GoogleCredential

GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


def get_user_credentials(user) -> Credentials:
    """Return valid google Credentials for the given user, refreshing if needed."""
    cred = GoogleCredential.objects.get(user=user)
    credentials = Credentials(
        token=cred.access_token,
        refresh_token=cred.refresh_token,
        token_uri=GOOGLE_TOKEN_URI,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=cred.scopes.split() if cred.scopes else [],
    )
    if not credentials.valid or credentials.expired:
        credentials.refresh(Request())
        cred.access_token = credentials.token
        cred.token_expiry = credentials.expiry
        cred.save(update_fields=["access_token", "token_expiry"])
    return credentials


def get_gmail_service(user):
    creds = get_user_credentials(user)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def get_calendar_service(user):
    creds = get_user_credentials(user)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)
