from unittest.mock import patch, MagicMock
from django.test import TestCase

from apps.absenteeism.services.report_service import (
    fetch_absenteeism_report_data,
    absenteeism_report
)

class ReportServiceTests(TestCase):

    @patch("apps.absenteeism.services.report_service.os.path.exists")
    @patch("apps.absenteeism.services.report_service.open")
    @patch("apps.absenteeism.services.report_service.json.load")
    @patch("apps.absenteeism.services.report_service.AttendanceMaster.objects")
    def test_fetch_absenteeism_report_data_handles_unknown_sections(self, mock_objects, mock_load, mock_open, mock_exists):
        # Ensure it doesn't crash if a section is returned that isn't in section_order
        mock_exists.return_value = True
        mock_load.return_value = {"line 1": {}}
        
        # Mock AttendanceMaster response to include an unknown section
        mock_qs = MagicMock()
        mock_qs.exclude.return_value.values.return_value.annotate.return_value = [
            {"section": "Assembly", "present": 10, "absent": 2},
            {"section": "UnknownSection", "present": 5, "absent": 1}, 
        ]
        mock_objects.filter.return_value = mock_qs
        
        # Test
        response = fetch_absenteeism_report_data()
        
        # Should not raise ValueError and should return 200 OK
        self.assertEqual(response.status_code, 200)

    @patch("apps.absenteeism.services.report_service.EmployeeMaster.objects")
    @patch("apps.absenteeism.services.report_service.AbsenteeismPrediction.objects")
    @patch("apps.absenteeism.services.report_service.AttendanceMaster.objects")
    def test_absenteeism_report_handles_unknown_sections(self, mock_attendance, mock_prediction, mock_employee):
        # Mock Employee query
        mock_emp_qs = MagicMock()
        mock_employee.filter.return_value.count.return_value = 100
        mock_employee.filter.return_value.values.return_value.annotate.return_value = [
            {"section": "Assembly", "count": 50},
            {"section": "WeirdSection", "count": 50},
        ]
        
        # Mock Prediction query
        mock_pred_qs = MagicMock()
        mock_prediction.filter.return_value.exclude.return_value.values.return_value.annotate.return_value = [
            {"section": "Assembly", "count": 5},
            {"section": "WeirdSection", "count": 2},
        ]
        
        # Mock Attendance query
        mock_att_qs = MagicMock()
        mock_attendance.filter.return_value.exclude.return_value.values.return_value.annotate.return_value = [
            {"section": "Assembly", "count": 3},
            {"section": "WeirdSection", "count": 4},
        ]
        
        response = absenteeism_report("ALL", "2023-01-01")
        
        # Should not raise ValueError and should return 200 OK
        self.assertEqual(response.status_code, 200)
        
        data = response.data["data"]
        self.assertEqual(data["total_employee_count"]["WeirdSection"], 50)
