"""
Tests for accounts services: auth_service, user_service, location_service.
Run with: python manage.py test apps.accounts.tests.test_services
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.services.auth_service import authenticate_user
from apps.accounts.services.location_service import verify_geofence
from apps.accounts.services.user_service import (
    change_user_password,
    delete_user_account,
)

User = get_user_model()


class AuthServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="authuser",
            email="auth@example.com",
            password="StrongPass123!",
            location="Test City",
            department="Engineering",
            phonenumber="9876543210",
        )

    def test_login_missing_credentials(self):
        _, _, _, error, code = authenticate_user("", "")
        self.assertIsNotNone(error)
        self.assertEqual(code, 400)

    def test_login_wrong_email(self):
        _, _, _, error, code = authenticate_user("wrong@example.com", "StrongPass123!")
        self.assertEqual(code, 404)

    def test_login_wrong_password(self):
        _, _, _, error, code = authenticate_user("auth@example.com", "wrongpass")
        self.assertEqual(code, 401)

    def test_login_success(self):
        user_details, access, refresh, error, code = authenticate_user(
            "auth@example.com", "StrongPass123!"
        )
        self.assertIsNone(error)
        self.assertEqual(code, 200)
        self.assertIsNotNone(access)
        self.assertIsNotNone(refresh)


class UserServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="pwduser",
            email="pwd@example.com",
            password="OldPass123!",
            location="Test City",
            department="Engineering",
            phonenumber="9876543210",
        )

    def test_change_password_missing_fields(self):
        error, code = change_user_password(self.user, "", "", "")
        self.assertIsNotNone(error)
        self.assertEqual(code, 400)

    def test_change_password_wrong_current(self):
        error, code = change_user_password(
            self.user, "WrongOld!", "NewPass123!", "NewPass123!"
        )
        self.assertIsNotNone(error)
        self.assertEqual(code, 400)

    def test_change_password_mismatch(self):
        error, code = change_user_password(
            self.user, "OldPass123!", "NewPass123!", "Different123!"
        )
        self.assertIsNotNone(error)
        self.assertEqual(code, 400)

    def test_change_password_success(self):
        error, code = change_user_password(
            self.user, "OldPass123!", "NewPass456!", "NewPass456!"
        )
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
            username="locuser",
            email="loc@example.com",
            password="StrongPass123!",
            location="Test City",
            department="Engineering",
            phonenumber="9876543210",
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

    def test_logout_user(self):
        from apps.accounts.services.auth_service import logout_user

        # Mismatch email
        msg, code = logout_user(self.user, "wrong@example.com")
        self.assertEqual(code, 400)

        # Valid logout
        msg, code = logout_user(self.user, self.user.email)
        self.assertEqual(code, 200)

    def test_get_all_users(self):
        from apps.accounts.services.user_service import get_all_users

        data, err, code = get_all_users()
        self.assertEqual(code, 200)
        self.assertIsInstance(data, list)

    def test_get_user_by_id(self):
        from apps.accounts.services.user_service import get_user_by_id

        data, err, code = get_user_by_id(self.user.id)
        self.assertEqual(code, 200)
        self.assertEqual(data["email"], self.user.email)

        # Invalid ID
        data, err, code = get_user_by_id(9999)
        self.assertEqual(code, 404)

    def test_update_user_details(self):
        from apps.accounts.services.user_service import update_user_details

        data, err, code = update_user_details(self.user.id, {"department": "NewDept"})
        self.assertEqual(code, 200)
        self.assertEqual(data["department"], "NewDept")


from apps.accounts.services.log_service import _get_validated_log_path


class LogServiceTest(TestCase):
    def setUp(self):
        # Ensure we don't accidentally wipe real logs by using a mock
        pass

    def test_log_path_validation_invalid(self):
        # Test path traversal prevention
        path, err, code = _get_validated_log_path("../../../etc/passwd")
        self.assertEqual(
            code, 404
        )  # Not found because it prepends to LOGS_DIR but strips directories using pathlib.Path.name
