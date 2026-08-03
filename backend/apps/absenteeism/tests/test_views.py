import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

User = get_user_model()


class AbsenteeismViewsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="testviewuser",
            email="view@example.com",
            password="StrongPass123!",
            location="Test City",
            department="Engineering",
            phonenumber="9876543210",
        )
        # Login to get cookies
        login_response = self.client.post(
            reverse("login"),
            {
                "email": "view@example.com",
                "password": "StrongPass123!",
            },
            format="json",
        )
        self.client.cookies = login_response.cookies

    @patch("apps.absenteeism.views.run_upload_absenteesim_data")
    def test_upload_absenteeism_data(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        file = io.StringIO("dummy data")
        file.name = "data.csv"
        response = self.client.post(
            reverse("upload-absenteeism-data"),
            {"file": file, "month": "7", "year": "2026"},
        )
        self.assertEqual(response.status_code, 200)

    @patch("apps.absenteeism.views.run_absenteeism_data_preprocessing")
    def test_preprocess_data(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.post(reverse("absenteeism-data-preprocessing"))
        self.assertEqual(response.status_code, 200)

    @patch("apps.absenteeism.views.run_upload_prediction_data")
    def test_upload_prediction_data(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        file = io.StringIO("dummy data")
        file.name = "predict.csv"
        response = self.client.post(reverse("upload-prediction-data"), {"file": file})
        self.assertEqual(response.status_code, 200)

    @patch("apps.absenteeism.views.run_export_data")
    def test_export_data(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.get(reverse("export-data"))
        self.assertEqual(response.status_code, 200)

    @patch("apps.absenteeism.views.run_export_absenteeism_data")
    def test_export_absenteeism_data(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.get(reverse("export-absenteeism-data"))
        self.assertEqual(response.status_code, 200)

    @patch("apps.absenteeism.views.run_send_csv_via_email")
    def test_send_csv_via_email(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.post(
            reverse("export-data-email"), {"email": "test@example.com"}, format="json"
        )
        self.assertEqual(response.status_code, 200)

    @patch("apps.absenteeism.views.run_get_absenteeism_forecast")
    def test_get_absenteeism_forecast(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.get(
            reverse("get-absenteeism-forecast"), {"forecast_period": 7, "line": "L1"}
        )
        self.assertEqual(response.status_code, 200)

    @patch("apps.absenteeism.views.run_absenteeism_prediction_trigger")
    def test_absenteeism_prediction(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.post(reverse("absenteeism-prediction"))
        self.assertEqual(response.status_code, 200)

    @patch("apps.absenteeism.views.run_absenteeism_prediction_data")
    def test_absenteeism_prediction_data(self, mock_run):
        mock_run.return_value = HttpResponse(status=200)
        response = self.client.get(reverse("absenteeism-prediction-data"))
        self.assertEqual(response.status_code, 200)

    @patch("apps.absenteeism.views.run_absenteeism_report")
    def test_get_today_absenteeism_report(self, mock_run):
        mock_run.return_value = (b"excel_bytes", "report.xlsx")
        response = self.client.get(reverse("get-today-absenteeism-report"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Disposition"], 'attachment; filename="report.xlsx"'
        )
