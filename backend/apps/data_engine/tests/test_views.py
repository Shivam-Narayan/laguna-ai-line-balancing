import io
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.http import HttpResponse

User = get_user_model()

class DataEngineViewsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='datauser',
            email='data@example.com',
            password='StrongPass123!',
            location='Test City',
            department='Engineering',
            phonenumber='9876543210'
        )
        login_response = self.client.post(reverse('login'), {
            'email': 'data@example.com',
            'password': 'StrongPass123!',
        }, format='json')
        self.client.cookies = login_response.cookies

    @patch('apps.data_engine.views.run_upload_historical_weather_data')
    def test_upload_historical_weather_data(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        file = io.StringIO("dummy data")
        file.name = "weather.csv"
        response = self.client.post(reverse('upload-historical-weather-data'), {'file': file})
        self.assertEqual(response.status_code, 200)

    @patch('apps.data_engine.views.run_upload_attendance_file')
    def test_upload_attendance_file(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        file = io.StringIO("dummy data")
        file.name = "attendance.csv"
        response = self.client.post(reverse('upload-attendance-file'), {'file': file})
        self.assertEqual(response.status_code, 200)

    @patch('apps.data_engine.views.run_add_local_holiday_calender')
    def test_add_local_holiday_calender(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        file = io.StringIO("dummy data")
        file.name = "holidays.csv"
        response = self.client.post(reverse('add-local-holiday-calender'), {'file': file})
        self.assertEqual(response.status_code, 200)

    @patch('apps.data_engine.views.run_add_payable_working_days')
    def test_add_payable_working_days(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.post(reverse('add-payable-working-days'))
        self.assertEqual(response.status_code, 200)

    @patch('apps.data_engine.views.run_get_calendar')
    def test_get_calendar(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.get(reverse('get-calendar'))
        self.assertEqual(response.status_code, 200)

    @patch('apps.data_engine.views.run_export_operators_data')
    def test_export_operators_data(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.get(reverse('export-operators-data'), {'line': 'L1'})
        self.assertEqual(response.status_code, 200)

    @patch('apps.data_engine.views.run_export_operators_data_email')
    def test_export_operators_data_email(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.get(reverse('export-operators-data-email'), {'email': 'test@example.com', 'line': 'L1'})
        self.assertEqual(response.status_code, 200)

    @patch('apps.data_engine.views.run_operators_data')
    def test_operators_data(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.get(reverse('operators-data'), {'line': 'L1'})
        self.assertEqual(response.status_code, 200)

    @patch('apps.data_engine.views.run_generate_employee_master')
    def test_generate_employee_master(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.get(reverse('generate-employee-master'))
        self.assertEqual(response.status_code, 200)
