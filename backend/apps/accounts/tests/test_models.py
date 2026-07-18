"""
Tests for accounts models: User, PasswordResetToken, MultiSessionToken, EndpointLock.
Run with: python manage.py test apps.accounts.tests.test_models
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from rest_framework.exceptions import ValidationError

from apps.accounts.models import PasswordResetToken, MultiSessionToken, EndpointLock
from apps.accounts.models.locks import LockType

User = get_user_model()


class UserModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='StrongPass123!',
            location='Test City',
            department='Engineering',
            phonenumber='9876543210'
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
            location='Test City',
            department='Engineering',
            phonenumber='9876543210'
        )

    def test_token_created_for_user(self):
        token = MultiSessionToken.objects.create(user=self.user)
        self.assertEqual(token.user, self.user)
        self.assertFalse(token.is_expired())
        self.assertTrue(len(token.key) > 0)


class PasswordResetTokenTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='resetuser',
            email='reset@example.com',
            password='StrongPass123!',
            location='Test City',
            department='Engineering',
            phonenumber='9876543210'
        )

    def test_token_creation_and_expiration(self):
        token = PasswordResetToken.objects.create(user=self.user, token='sometoken123')
        self.assertEqual(token.user, self.user)
        self.assertEqual(token.token, 'sometoken123')
        self.assertFalse(token.is_expired())

        # Simulate expiration
        token.created_at = timezone.now() - timedelta(minutes=15)
        token.save()
        self.assertTrue(token.is_expired())


class EndpointLockTest(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            username='lockuser1',
            email='lock1@example.com',
            password='StrongPass123!',
            location='Test City',
            department='Engineering',
            phonenumber='9876543210'
        )
        self.user2 = User.objects.create_user(
            username='lockuser2',
            email='lock2@example.com',
            password='StrongPass123!',
            location='Test City',
            department='Engineering',
            phonenumber='9876543211'
        )
        self.url_name = 'test_endpoint'

    def test_acquire_and_release_lock(self):
        # Acquire lock
        lock = EndpointLock.acquire_lock(LockType.DATA_UPDATE, self.user1, self.url_name)
        self.assertTrue(lock.is_active)
        self.assertEqual(lock.locked_by, self.user1)

        # Release lock
        count = EndpointLock.release_lock(LockType.DATA_UPDATE, self.user1, self.url_name)
        self.assertEqual(count, 1)

        # Verify it is released
        lock.refresh_from_db()
        self.assertFalse(lock.is_active)

    def test_acquire_lock_when_already_locked(self):
        EndpointLock.acquire_lock(LockType.DATA_UPDATE, self.user1, self.url_name)

        # Same user tries again
        with self.assertRaises(ValidationError):
            EndpointLock.acquire_lock(LockType.DATA_UPDATE, self.user1, self.url_name)

        # Different user tries
        with self.assertRaises(ValidationError):
            EndpointLock.acquire_lock(LockType.DATA_UPDATE, self.user2, self.url_name)
