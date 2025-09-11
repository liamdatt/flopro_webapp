from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from .models import GoogleCredential


class GoogleCredentialModelTest(TestCase):
    def test_str_contains_username(self):
        user = User.objects.create_user(username='alice')
        cred = GoogleCredential.objects.create(user=user, refresh_token='r')
        self.assertIn('alice', str(cred))


class GmailApiAuthTest(TestCase):
    def test_send_requires_api_key(self):
        url = reverse('core:api_google_gmail_send')
        resp = self.client.post(url, content_type='application/json', data={})
        self.assertEqual(resp.status_code, 401)
