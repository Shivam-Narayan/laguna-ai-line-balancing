"""
Tests for accounts models: User, PasswordResetToken, MultiSessionToken, EndpointLock.
Run with: python manage.py test apps.accounts.tests.test_models
"""
from django.test import TestCase
from django.contrib.auth import get_user_model

from apps.accounts.models import PasswordResetToken, MultiSessionToken

User = get_user_model()


class UserModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='StrongPass123!',
            location='Test City',
            department='Engineering',
        )

    def test_user_created_successfully(self):
        self.assertEqual(self.user.email, 'test@example.com')
        self.assertEqual(self.user.username, 'testuser')

    def test_user_str(self):
        self.assertEqual(str(self.user), 'testuser')

    def test_password_is_hashed(self):
        self.assertNotEqual(self.user.password, 'StrongPass123!')
        self.assertTrue(self.user.check_password('StrongPass123!'))

    def test_default_user_type_is_normal(self):
        self.assertEqual(self.user.user_type, 0)

    def test_default_status_is_active(self):
        self.assertTrue(self.user.status)


class MultiSessionTokenTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='tokenuser',
            email='token@example.com',
            password='StrongPass123!',
        )

    def test_token_created_for_user(self):
        token = MultiSessionToken.objects.create(user=self.user)
        self.assertEqual(token.user, self.user)
        self.assertFalse(token.is_expired())
