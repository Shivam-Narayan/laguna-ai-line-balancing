import pandas as pd
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.http import HttpResponse
from rest_framework.response import Response

from apps.absenteeism.services.export_service import (
    run_export_data,
    run_export_absenteeism_data,
    run_send_csv_via_email,
    scheduler_prediction_data_email,
)
from apps.accounts.models import User
from apps.data_engine.models import LocalHolidayCalendar
from apps.absenteeism.models import Absenteeism


class ExportServiceTests(TestCase):
    def setUp(self):
        # Setting up some dummy data
        self.user = User.objects.create(
            username="testuser",
            email="test@example.com",
            send_mail=True,
            status=True,
        )

    @patch("apps.absenteeism.services.export_service.LocalHolidayCalendar.objects.all")
    def test_run_export_data_no_data(self, mock_all):
        mock_all.return_value.values.return_value = []
        response = run_export_data()
        self.assertIsInstance(response, Response)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"], "No data found to export.")

    @patch("apps.absenteeism.services.export_service.LocalHolidayCalendar.objects.all")
    def test_run_export_data_success(self, mock_all):
        mock_all.return_value.values.return_value = [{"id": 1, "date": "2023-01-01", "holiday_name": "New Year"}]
        response = run_export_data()
        self.assertIsInstance(response, HttpResponse)
        self.assertEqual(response["Content-Type"], "text/csv")

    @patch("apps.absenteeism.services.export_service.Absenteeism.objects.all")
    def test_run_export_absenteeism_data_no_data(self, mock_all):
        mock_all.return_value.values.return_value = []
        response = run_export_absenteeism_data()
        self.assertIsInstance(response, Response)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"], "No data found to export.")

    @patch("apps.absenteeism.services.export_service.Absenteeism.objects.all")
    def test_run_export_absenteeism_data_success(self, mock_all):
        mock_all.return_value.values.return_value = [{"id": 1, "emp_id": "123", "line": "LINE 1"}]
        response = run_export_absenteeism_data()
        self.assertIsInstance(response, HttpResponse)
        self.assertEqual(response["Content-Type"], "text/csv")

    @patch("apps.absenteeism.services.export_service.generate_csv")
    @patch("apps.absenteeism.tasks.send_email_task.delay")
    def test_run_send_csv_via_email_success(self, mock_delay, mock_generate_csv):
        mock_csv_data = MagicMock()
        mock_csv_data.getvalue.return_value = b"csv,data"
        mock_generate_csv.return_value = mock_csv_data

        response = run_send_csv_via_email("test@example.com")
        self.assertIsInstance(response, Response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "success")
        mock_delay.assert_called_once()

    def test_run_send_csv_via_email_no_email(self):
        response = run_send_csv_via_email(None)
        self.assertIsInstance(response, Response)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"], "Email address is required.")

    @patch("apps.absenteeism.services.export_service.prepare_prediction_data")
    @patch("apps.absenteeism.services.export_service.generate_prediction_data")
    @patch("apps.absenteeism.services.export_service.is_allowed_working_day")
    @patch("apps.absenteeism.services.export_service.send_email")
    def test_scheduler_prediction_data_email_error_prepare(self, mock_send_email, mock_is_allowed, mock_generate, mock_prepare):
        # Bug test: test when prepare_prediction_data returns an error (which lacks a 'data' key inside its Response.data)
        mock_is_allowed.return_value = (True, "")
        mock_prepare.return_value = Response({"status": "error", "error": "Something went wrong"}, status=400)
        
        response = scheduler_prediction_data_email("LINE 1", 1)
        self.assertIsInstance(response, Response)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["status"], "error")

    @patch("apps.absenteeism.services.export_service.prepare_prediction_data")
    @patch("apps.absenteeism.services.export_service.generate_prediction_data")
    @patch("apps.absenteeism.services.export_service.is_allowed_working_day")
    @patch("apps.absenteeism.services.export_service.send_email")
    def test_scheduler_prediction_data_email_success(self, mock_send_email, mock_is_allowed, mock_generate, mock_prepare):
        mock_is_allowed.return_value = (True, "")
        mock_prepare.return_value = Response({"status": "success", "data": {"some": "data"}}, status=200)
        mock_generate.return_value = b"excel_data"
        mock_send_email.return_value = True

        response = scheduler_prediction_data_email("LINE 1", 1)
        self.assertIsInstance(response, Response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "success")

