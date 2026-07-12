"""
Tests for accounts services: auth_service, user_service, location_service.
Run with: python manage.py test apps.accounts.tests.test_services
"""
from django.test import TestCase
from django.contrib.auth import get_user_model

from apps.accounts.services.auth_service import authenticate_user
from apps.accounts.services.user_service import change_user_password, delete_user_account
from apps.accounts.services.location_service import verify_geofence

User = get_user_model()


class AuthServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='authuser',
            email='auth@example.com',
            password='StrongPass123!',
        )

    def test_login_missing_credentials(self):
        _, _, _, error, code = authenticate_user('', '')
        self.assertIsNotNone(error)
        self.assertEqual(code, 400)

    def test_login_wrong_email(self):
        _, _, _, error, code = authenticate_user('wrong@example.com', 'StrongPass123!')
        self.assertEqual(code, 404)

    def test_login_wrong_password(self):
        _, _, _, error, code = authenticate_user('auth@example.com', 'wrongpass')
        self.assertEqual(code, 401)

    def test_login_success(self):
        user_details, access, refresh, error, code = authenticate_user('auth@example.com', 'StrongPass123!')
        self.assertIsNone(error)
        self.assertEqual(code, 200)
        self.assertIsNotNone(access)
        self.assertIsNotNone(refresh)


class UserServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='pwduser',
            email='pwd@example.com',
            password='OldPass123!',
        )

    def test_change_password_missing_fields(self):
        error, code = change_user_password(self.user, '', '', '')
        self.assertIsNotNone(error)
        self.assertEqual(code, 400)

    def test_change_password_wrong_current(self):
        error, code = change_user_password(self.user, 'WrongOld!', 'NewPass123!', 'NewPass123!')
        self.assertIsNotNone(error)
        self.assertEqual(code, 400)

    def test_change_password_mismatch(self):
        error, code = change_user_password(self.user, 'OldPass123!', 'NewPass123!', 'Different123!')
        self.assertIsNotNone(error)
        self.assertEqual(code, 400)

    def test_change_password_success(self):
        error, code = change_user_password(self.user, 'OldPass123!', 'NewPass456!', 'NewPass456!')
        self.assertIsNone(error)
        self.assertEqual(code, 200)

    def test_delete_user_not_found(self):
        import uuid
        _, error, code = delete_user_account(uuid.uuid4())
        self.assertIsNotNone(error)
        self.assertEqual(code, 404)


class LocationServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='locuser',
            email='loc@example.com',
            password='StrongPass123!',
        )
        self.user.latitude = 12.9729
        self.user.longitude = 77.7189
        self.user.save()

    def test_user_missing_coordinates(self):
        self.user.latitude = None
        self.user.longitude = None
        self.user.save()
        within, msg, code = verify_geofence(self.user, 12.9729, 77.7189)
        self.assertFalse(within)

    def test_user_within_geofence(self):
        within, msg, code = verify_geofence(self.user, 12.9729, 77.7189)
        self.assertTrue(within)
        self.assertEqual(code, 200)

    def test_user_outside_geofence(self):
        # Far away coordinates
        within, msg, code = verify_geofence(self.user, 28.6139, 77.2090)
        self.assertFalse(within)
        self.assertEqual(code, 403)
