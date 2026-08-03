"""
Integration tests for accounts API views.
Run with: python manage.py test apps.accounts.tests.test_views
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

User = get_user_model()


class AuthViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="viewuser",
            email="view@example.com",
            password="StrongPass123!",
        )

    def test_home_returns_200(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)

    def test_login_success(self):
        response = self.client.post(
            reverse("login"),
            {
                "email": "view@example.com",
                "password": "StrongPass123!",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access_token", response.cookies)
        self.assertIn("refresh_token", response.cookies)

    def test_login_invalid_credentials(self):
        response = self.client.post(
            reverse("login"),
            {
                "email": "view@example.com",
                "password": "wrongpass",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 401)

    def test_protected_endpoint_requires_auth(self):
        response = self.client.get(reverse("protected"))
        self.assertEqual(response.status_code, 401)

    def test_register_user(self):
        response = self.client.post(
            reverse("user-register"),
            {
                "username": "newuser",
                "email": "newuser@example.com",
                "password": "StrongPass123!",
                "location": "Test City",
                "department": "Engineering",
                "phonenumber": "9876543210",
            },
            format="json",
        )
        self.assertIn(response.status_code, [200, 201])

    def test_logout(self):
        login_response = self.client.post(
            reverse("login"),
            {
                "email": "view@example.com",
                "password": "StrongPass123!",
            },
            format="json",
        )

        self.client.cookies = login_response.cookies
        response = self.client.post(reverse("logout"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.cookies["access_token"].value, "")
        self.assertEqual(response.cookies["refresh_token"].value, "")

    def test_token_refresh(self):
        login_response = self.client.post(
            reverse("login"),
            {
                "email": "view@example.com",
                "password": "StrongPass123!",
            },
            format="json",
        )

        self.client.cookies = login_response.cookies
        response = self.client.post(reverse("token_refresh"), format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("access_token", response.cookies)
        self.assertIn("refresh_token", response.cookies)

    def test_change_password(self):
        login_response = self.client.post(
            reverse("login"),
            {
                "email": "view@example.com",
                "password": "StrongPass123!",
            },
            format="json",
        )

        self.client.cookies = login_response.cookies
        response = self.client.post(
            reverse("change_password"),
            {
                "current_password": "StrongPass123!",
                "new_password": "NewStrongPass123!",
                "confirm_password": "NewStrongPass123!",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        # Verify login works with the new password
        login_response_new = self.client.post(
            reverse("login"),
            {
                "email": "view@example.com",
                "password": "NewStrongPass123!",
            },
            format="json",
        )
        self.assertEqual(login_response_new.status_code, 200)

    def test_request_password_reset(self):
        response = self.client.post(
            reverse("request_reset_password"),
            {"email": "view@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_get_all_users(self):
        login_response = self.client.post(
            reverse("login"),
            {
                "email": "view@example.com",
                "password": "StrongPass123!",
            },
            format="json",
        )
        self.client.cookies = login_response.cookies

        response = self.client.get(reverse("get_all_users"))
        self.assertEqual(response.status_code, 200)

    def test_get_user_by_id(self):
        login_response = self.client.post(
            reverse("login"),
            {
                "email": "view@example.com",
                "password": "StrongPass123!",
            },
            format="json",
        )
        self.client.cookies = login_response.cookies

        response = self.client.get(
            reverse("get_user_by_id", kwargs={"user_id": self.user.id})
        )
        self.assertEqual(response.status_code, 200)

    def test_update_user(self):
        login_response = self.client.post(
            reverse("login"),
            {
                "email": "view@example.com",
                "password": "StrongPass123!",
            },
            format="json",
        )
        self.client.cookies = login_response.cookies

        response = self.client.put(
            reverse("update_user", kwargs={"user_id": self.user.id}),
            {"department": "New Department"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_delete_user(self):
        # Create a temp user to delete
        temp_user = User.objects.create_user(
            username="temp",
            email="temp@example.com",
            password="pwd",
            location="Test",
            department="Test",
            phonenumber="9999999999",
        )

        login_response = self.client.post(
            reverse("login"),
            {
                "email": "temp@example.com",
                "password": "pwd",
            },
            format="json",
        )
        self.client.cookies = login_response.cookies

        response = self.client.delete(
            reverse("delete_user", kwargs={"user_id": temp_user.id})
        )
        self.assertEqual(response.status_code, 200)

    def test_csrf_enforcement(self):
        """
        Verify that POST/PUT/DELETE requests fail without a CSRF token
        and succeed when a valid CSRF token is provided in the headers.
        """
        # Instantiate a client that actually enforces CSRF (Django Test Client disables it by default)
        csrf_client = APIClient(enforce_csrf_checks=True)
        
        # 1. Login to get the access_token and csrftoken cookies
        login_response = csrf_client.post(
            reverse("login"),
            {
                "email": "view@example.com",
                "password": "StrongPass123!",
            },
            format="json",
        )
        csrf_client.cookies = login_response.cookies
        
        # 2. Attempt a POST request WITHOUT the X-CSRFToken header
        # Django's CSRFCheck will block this with a 403 Forbidden
        response_without_csrf = csrf_client.post(
            reverse("logout"),
            format="json"
        )
        # Without CSRF, cookie auth gracefully falls back to anonymous (401 Unauthorized),
        # rather than hard-blocking with 403. This allows AllowAny endpoints
        # (like SSO login) to proceed while still protecting authenticated views.
        self.assertEqual(response_without_csrf.status_code, 401)
        
        # 3. Attempt a POST request WITH the valid X-CSRFToken header
        csrf_token = login_response.cookies.get('csrftoken').value
        response_with_csrf = csrf_client.post(
            reverse("logout"),
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token
        )
        self.assertEqual(response_with_csrf.status_code, 200)

    def test_update_user_idor_blocked(self):
        # Create a second user
        victim = User.objects.create_user(
            username="victim",
            email="victim@example.com",
            password="pwd",
        )
        login_response = self.client.post(
            reverse("login"),
            {"email": "view@example.com", "password": "StrongPass123!"},
            format="json",
        )
        self.client.cookies = login_response.cookies

        # Try to update the victim's profile as the first user
        response = self.client.put(
            reverse("update_user", kwargs={"user_id": victim.id}),
            {"department": "Hacked"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_fetch_logs_unauthorized(self):
        # Login as a regular user (not superuser)
        login_response = self.client.post(
            reverse("login"),
            {"email": "view@example.com", "password": "StrongPass123!"},
            format="json",
        )
        self.client.cookies = login_response.cookies

        # Try to fetch server logs
        response = self.client.get(reverse("fetch_logs", kwargs={"log_filename": "server"}))
        # Should be forbidden for non-admins
        self.assertEqual(response.status_code, 403)
