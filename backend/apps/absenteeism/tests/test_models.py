from datetime import date

from django.test import TestCase

from apps.absenteeism.models import Absenteeism, AbsenteeismPrediction, PredictionData


class AbsenteeismModelTest(TestCase):
    def test_absenteeism_creation(self):
        record = Absenteeism.objects.create(
            date=date.today(),
            empcode="E123",
            name="John Doe",
            department="Sales",
            attendance="P",
            present_days=1,
            absent_days=0,
        )
        self.assertEqual(record.empcode, "E123")
        self.assertEqual(str(record), f"John Doe (E123) - {date.today()}")


class PredictionDataModelTest(TestCase):
    def test_prediction_data_creation(self):
        record = PredictionData.objects.create(
            date=date.today(),
            empcode="E456",
            name="Jane Smith",
            department="IT",
            section="Backend",
            attendance="P",
        )
        self.assertEqual(record.empcode, "E456")
        self.assertEqual(str(record), f"Jane Smith (E456) - {date.today()}")


class AbsenteeismPredictionModelTest(TestCase):
    def test_prediction_creation(self):
        record = AbsenteeismPrediction.objects.create(
            datetime=date.today(),
            day_of_week="Monday",
            predicted_absent_count=5.5,
            line="Line 1",
            section="Assembly",
            forecast_period=7,
            historical_mean=5.0,
            historical_std=1.2,
            deviation_from_mean=0.5,
        )
        self.assertEqual(record.line, "Line 1")
        self.assertEqual(str(record), f"{date.today()} - Line 1 - Assembly")
