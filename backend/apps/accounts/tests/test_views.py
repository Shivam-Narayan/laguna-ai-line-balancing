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
            'location': 'Test City',
            'department': 'Engineering',
            'phonenumber': '9876543210',
        }, format='json')
        self.assertIn(response.status_code, [200, 201])

    def test_logout(self):
        login_response = self.client.post(reverse('login'), {
            'email': 'view@example.com',
            'password': 'StrongPass123!',
        }, format='json')
        
        self.client.cookies = login_response.cookies
        response = self.client.post(reverse('logout'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.cookies['access_token'].value, '')
        self.assertEqual(response.cookies['refresh_token'].value, '')

    def test_token_refresh(self):
        login_response = self.client.post(reverse('login'), {
            'email': 'view@example.com',
            'password': 'StrongPass123!',
        }, format='json')
        
        self.client.cookies = login_response.cookies
        response = self.client.post(reverse('token_refresh'), format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('access_token', response.cookies)
        self.assertIn('refresh_token', response.cookies)

    def test_change_password(self):
        login_response = self.client.post(reverse('login'), {
            'email': 'view@example.com',
            'password': 'StrongPass123!',
        }, format='json')
        
        self.client.cookies = login_response.cookies
        response = self.client.post(reverse('change_password'), {
            'current_password': 'StrongPass123!',
            'new_password': 'NewStrongPass123!',
            'confirm_password': 'NewStrongPass123!'
        }, format='json')
        self.assertEqual(response.status_code, 200)

        # Verify login works with the new password
        login_response_new = self.client.post(reverse('login'), {
            'email': 'view@example.com',
            'password': 'NewStrongPass123!',
        }, format='json')
        self.assertEqual(login_response_new.status_code, 200)

    def test_request_password_reset(self):
        response = self.client.post(reverse('request_reset_password'), {
            'email': 'view@example.com'
        }, format='json')
        self.assertEqual(response.status_code, 200)

    def test_get_all_users(self):
        login_response = self.client.post(reverse('login'), {
            'email': 'view@example.com',
            'password': 'StrongPass123!',
        }, format='json')
        self.client.cookies = login_response.cookies

        response = self.client.get(reverse('get_all_users'))
        self.assertEqual(response.status_code, 200)

    def test_get_user_by_id(self):
        login_response = self.client.post(reverse('login'), {
            'email': 'view@example.com',
            'password': 'StrongPass123!',
        }, format='json')
        self.client.cookies = login_response.cookies

        response = self.client.get(reverse('get_user_by_id', kwargs={'user_id': self.user.id}))
        self.assertEqual(response.status_code, 200)

    def test_update_user(self):
        login_response = self.client.post(reverse('login'), {
            'email': 'view@example.com',
            'password': 'StrongPass123!',
        }, format='json')
        self.client.cookies = login_response.cookies

        response = self.client.put(reverse('update_user', kwargs={'user_id': self.user.id}), {
            'department': 'New Department'
        }, format='json')
        self.assertEqual(response.status_code, 200)

    def test_delete_user(self):
        # Create a temp user to delete
        temp_user = User.objects.create_user(
            username='temp', 
            email='temp@example.com', 
            password='pwd', 
            location='Test', 
            department='Test', 
            phonenumber='9999999999'
        )

        login_response = self.client.post(reverse('login'), {
            'email': 'view@example.com',
            'password': 'StrongPass123!',
        }, format='json')
        self.client.cookies = login_response.cookies

        response = self.client.delete(reverse('delete_user', kwargs={'user_id': temp_user.id}))
        self.assertEqual(response.status_code, 200)
