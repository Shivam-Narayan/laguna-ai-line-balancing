"""
Tests for accounts models: User, PasswordResetToken, MultiSessionToken, EndpointLock.
Run with: python manage.py test apps.accounts.tests.test_models
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import EndpointLock, MultiSessionToken, PasswordResetToken
from apps.accounts.models.locks import LockType

User = get_user_model()


class UserModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="StrongPass123!",
            location="Test City",
            department="Engineering",
            phonenumber="9876543210",
        )

    def test_user_created_successfully(self):
        self.assertEqual(self.user.email, "test@example.com")
        self.assertEqual(self.user.username, "testuser")

    def test_user_str(self):
        self.assertEqual(str(self.user), "testuser")

    def test_password_is_hashed(self):
        self.assertNotEqual(self.user.password, "StrongPass123!")
        self.assertTrue(self.user.check_password("StrongPass123!"))

    def test_default_user_type_is_normal(self):
        self.assertEqual(self.user.user_type, 0)

    def test_default_status_is_active(self):
        self.assertTrue(self.user.status)

    def test_user_is_active_matches_status(self):
        """Test that user.is_active properly reflects user.status"""
        self.user.status = False
        self.assertFalse(self.user.is_active)
        self.user.status = True
        self.assertTrue(self.user.is_active)

    def test_create_superuser_invalid_flags(self):
        """Test that passing is_staff=False to create_superuser throws a ValueError"""
        with self.assertRaises(ValueError):
            User.objects.create_superuser(
                username="fakestaff",
                email="fakestaff@example.com",
                password="pwd",
                is_staff=False
            )

    def test_last_login_update_signal(self):
        """Test that Django's built-in update_last_login signal doesn't crash"""
        from django.contrib.auth.models import update_last_login
        
        try:
            # Manually trigger the signal that runs during standard login
            update_last_login(None, user=self.user)
            # If we get here without a ValueError or AttributeError, the test passes.
        except ValueError:
            self.fail("update_last_login raised a ValueError due to missing last_login field.")

class MultiSessionTokenTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="tokenuser",
            email="token@example.com",
            password="StrongPass123!",
            location="Test City",
            department="Engineering",
            phonenumber="9876543210",
        )

    def test_token_created_for_user(self):
        token = MultiSessionToken.objects.create(user=self.user)
        self.assertEqual(token.user, self.user)
        self.assertFalse(token.is_expired())
        self.assertTrue(len(token.key) > 0)

    def test_refresh_token_extends_expiry(self):
        """Test that calling refresh_token on an active token extends its expiry"""
        token = MultiSessionToken.objects.create(user=self.user)
        original_expiry = token.expiry
        original_key = token.key
        
        # Simulate time passing but not expiring
        token.expiry = timezone.now() + timedelta(days=1)
        token.save()
        
        # Refresh it
        token.refresh_token()
        
        # Verify expiry was pushed forward
        self.assertGreater(token.expiry, original_expiry)
        # Verify key remains the same (Option A)
        self.assertEqual(token.key, original_key)


class PasswordResetTokenTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="resetuser",
            email="reset@example.com",
            password="StrongPass123!",
            location="Test City",
            department="Engineering",
            phonenumber="9876543210",
        )

    def test_token_creation_and_expiration(self):
        token = PasswordResetToken.objects.create(user=self.user, token="sometoken123")
        self.assertEqual(token.user, self.user)
        self.assertEqual(token.token, "sometoken123")
        self.assertFalse(token.is_expired())

        # Simulate expiration
        token.created_at = timezone.now() - timedelta(minutes=15)
        token.save()
        self.assertTrue(token.is_expired())


class EndpointLockTest(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            username="lockuser1",
            email="lock1@example.com",
            password="StrongPass123!",
            location="Test City",
            department="Engineering",
            phonenumber="9876543210",
        )
        self.user2 = User.objects.create_user(
            username="lockuser2",
            email="lock2@example.com",
            password="StrongPass123!",
            location="Test City",
            department="Engineering",
            phonenumber="9876543211",
        )
        self.url_name = "test_endpoint"

    def test_acquire_and_release_lock(self):
        # Acquire lock
        lock = EndpointLock.acquire_lock(
            LockType.DATA_UPDATE, self.user1, self.url_name
        )
        self.assertTrue(lock.is_active)
        self.assertEqual(lock.locked_by, self.user1)

        # Release lock
        count = EndpointLock.release_lock(
            LockType.DATA_UPDATE, self.user1, self.url_name
        )
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

    def test_concurrent_lock_creation_fails(self):
        """Test that the database prevents creating two active locks for the same endpoint (simulating a race condition)"""
        from django.db import IntegrityError
        
        # Create first active lock at the DB level (simulating thread 1)
        EndpointLock.objects.create(
            lock_type=LockType.DATA_UPDATE,
            locked_by=self.user1,
            url_name=self.url_name,
            is_active=True
        )
        
        # Create second active lock at the DB level (simulating thread 2 bypassing acquire_lock due to race condition)
        # This MUST fail with an IntegrityError if the UniqueConstraint is properly configured.
        with self.assertRaises(IntegrityError):
            EndpointLock.objects.create(
                lock_type=LockType.DATA_UPDATE,
                locked_by=self.user2,
                url_name=self.url_name,
                is_active=True
            )
