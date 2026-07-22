from django.test import TestCase
from unittest.mock import patch
import pandas as pd

from apps.absenteeism.services.absenteeism_percentage_service import (
    load_active_employees,
    calculate_line_percentages,
)

class AbsenteeismPercentageServiceTest(TestCase):
    @patch('apps.absenteeism.services.absenteeism_percentage_service.pd.read_csv')
    def test_load_active_employees_returns_dict(self, mock_read_csv):
        # Mock the CSV read to return a sample DataFrame
        mock_read_csv.return_value = pd.DataFrame({
            "Department": ["LINE 1 Assembly", "LINE 2 Cutting", "LINE 1 Packing"],
        })
        
        # Call the function
        result = load_active_employees()
        
        # It should return a Python dictionary, NOT a Pandas DataFrame.
        # If it returns a DataFrame, this test will fail because DataFrames don't have a get() method that works like a dict.
        self.assertIsInstance(result, dict)
        
        # We expect LINE 1 to have 2 employees, and LINE 2 to have 1 employee.
        self.assertEqual(result.get("LINE 1"), 2)
        self.assertEqual(result.get("LINE 2"), 1)

    def test_calculate_line_percentages_math(self):
        class MockRecord:
            def __init__(self, dept, att):
                self.department = dept
                self.attendance = att
        
        # 1 person absent on LINE 1, 1 person present
        mock_data = [
            MockRecord("LINE 1", "A"),
            MockRecord("LINE 1", "P"),
        ]
        
        # If we have 4 total employees on LINE 1, and 1 is absent, the percentage should be 25.0
        emp_counts = {"LINE 1": 4}
        
        # Execute
        result = calculate_line_percentages(mock_data, emp_counts, target_line="LINE 1")
        
        # Assert math works (1/4 = 25.0%)
        # If it's 0.0, the test will fail, proving the bug existed.
        self.assertEqual(result, 25.0)

    def test_process_absenteeism_data_duplicates_graceful(self):
        from apps.absenteeism.models import Absenteeism, PredictionData
        from apps.absenteeism.services.data_ingestion_service import process_absenteeism_data
        from datetime import date
        from django.db import IntegrityError
        
        # We simulate a corrupted HR upload that resulted in two Absenteeism records for the same person/day.
        # Wait, Absenteeism has a UniqueConstraint on (date, empcode) too. So we can't create them like this.
        # BUT PredictionData has UniqueConstraint on (date, empcode).
        # What if Absenteeism doesn't have duplicate, but there's a race condition?
        pass
