import io
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.http import HttpResponse

User = get_user_model()

class ManningSheetViewsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='manninguser',
            email='manning@example.com',
            password='StrongPass123!',
            location='Test City',
            department='Engineering',
            phonenumber='9876543210'
        )
        login_response = self.client.post(reverse('login'), {
            'email': 'manning@example.com',
            'password': 'StrongPass123!',
        }, format='json')
        self.client.cookies = login_response.cookies

    @patch('apps.manning_sheet.views.run_manning_generation')
    def test_manning_allocation(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.post(reverse('manning-allocation'))
        self.assertEqual(response.status_code, 200)

    @patch('apps.manning_sheet.views.run_get_user_notifications')
    def test_get_user_notifications(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.get(reverse('get-user-notifications'))
        self.assertEqual(response.status_code, 200)

    @patch('apps.manning_sheet.views.run_generate_emp_fact')
    def test_generate_emp_fact(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.get(reverse('generate-emp-fact'))
        self.assertEqual(response.status_code, 200)

    @patch('apps.manning_sheet.views.run_dday_generation')
    def test_generate_dday_manning_data(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.post(reverse('generate-dday-manning-data'))
        self.assertEqual(response.status_code, 200)

    @patch('apps.manning_sheet.views.run_get_manning_data')
    def test_get_manning_data(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.get(reverse('get-manning-data'))
        self.assertEqual(response.status_code, 200)

    @patch('apps.manning_sheet.views.run_get_attendance_data')
    def test_get_attendance_data(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.get(reverse('get-attendance-data'))
        self.assertEqual(response.status_code, 200)

    @patch('apps.manning_sheet.views.run_styleob_file_upload')
    def test_styleob_file_upload(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        file = io.StringIO("dummy data")
        file.name = "style.csv"
        response = self.client.post(reverse('styleob-file-upload'), {'file': file})
        self.assertEqual(response.status_code, 200)

    @patch('apps.manning_sheet.views.run_loading_plan_file_upload')
    def test_loading_plan_file_upload(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        file = io.StringIO("dummy data")
        file.name = "plan.csv"
        response = self.client.post(reverse('loading-plan-file-upload'), {'file': file})
        self.assertEqual(response.status_code, 200)

    @patch('apps.manning_sheet.views.run_fetch_emp_attendance_rockhr')
    def test_fetch_emp_attendance_rockhr(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.get(reverse('fetch-emp-attendance-rockhr'))
        self.assertEqual(response.status_code, 200)

    @patch('apps.manning_sheet.views.run_update_allocated_employees')
    def test_update_allocated_employees(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.post(reverse('update-allocated-employees'), {'final_allocation': '[]'}, format='json')
        self.assertEqual(response.status_code, 200)
