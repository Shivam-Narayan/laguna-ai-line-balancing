from unittest.mock import patch, MagicMock
from django.test import TestCase
from rest_framework.response import Response

from apps.absenteeism.services.prediction_orchestrator import (
    run_absenteeism_prediction_trigger,
    run_absenteeism_prediction_data,
    run_get_absenteeism_forecast,
)


class PredictionOrchestratorTests(TestCase):

    @patch("threading.Thread")
    def test_run_absenteeism_prediction_trigger(self, mock_thread):
        mock_instance = MagicMock()
        mock_thread.return_value = mock_instance

        response = run_absenteeism_prediction_trigger()
        
        # Verify thread was created and started
        mock_thread.assert_called_once()
        mock_instance.start.assert_called_once()
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "success")

    def test_run_get_absenteeism_forecast_no_line(self):
        # Test line missing/None
        response = run_get_absenteeism_forecast(7, None)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"], "Line parameter is required")

    @patch("apps.absenteeism.services.prediction_orchestrator.prepare_prediction_data")
    def test_run_absenteeism_prediction_data_error_keyerror(self, mock_prepare):
        # Test the bug where prepare_prediction_data returned an error without 'data' key
        mock_prepare.return_value = Response({"status": "error", "error": "Something went wrong"}, status=400)
        
        response = run_absenteeism_prediction_data("LINE 1", 7, False, is_export=False)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["status"], "error")
        self.assertEqual(response.data["error"], "Something went wrong")

    @patch("apps.absenteeism.services.prediction_orchestrator.prepare_prediction_data")
    @patch("apps.absenteeism.services.prediction_orchestrator.generate_prediction_data")
    def test_run_absenteeism_prediction_data_export_error_keyerror(self, mock_generate, mock_prepare):
        # Test the export branch for the KeyError bug
        mock_prepare.return_value = Response({"status": "error", "error": "Failed to prepare"}, status=400)
        
        response = run_absenteeism_prediction_data("LINE 1", 7, False, is_export=True, export_type="excel")
        
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["status"], "error")
        mock_generate.assert_not_called()
