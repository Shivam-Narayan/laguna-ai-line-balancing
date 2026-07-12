"""
Integration tests for accounts API views.
Run with: python manage.py test apps.accounts.tests.test_views
"""
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

User = get_user_model()


class AuthViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='viewuser',
            email='view@example.com',
            password='StrongPass123!',
        )

    def test_home_returns_200(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)

    def test_login_success(self):
        response = self.client.post(reverse('login'), {
            'email': 'view@example.com',
            'password': 'StrongPass123!',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('access_token', response.cookies)
        self.assertIn('refresh_token', response.cookies)

    def test_login_invalid_credentials(self):
        response = self.client.post(reverse('login'), {
            'email': 'view@example.com',
            'password': 'wrongpass',
        }, format='json')
        self.assertEqual(response.status_code, 401)

    def test_protected_endpoint_requires_auth(self):
        response = self.client.get(reverse('protected'))
        self.assertEqual(response.status_code, 401)

    def test_register_user(self):
        response = self.client.post(reverse('user-register'), {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password': 'StrongPass123!',
        }, format='json')
        self.assertIn(response.status_code, [200, 201])
