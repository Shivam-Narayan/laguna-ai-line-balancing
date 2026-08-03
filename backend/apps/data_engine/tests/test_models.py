from datetime import date

from django.test import TestCase
from django.utils import timezone

from apps.data_engine.models import (
    AttendanceMaster,
    EmployeeMaster,
    EmployeeStatus,
    HistoricalWeather,
    LocalHolidayCalendar,
    PayableWorkingDays,
)


class LocalHolidayCalendarModelTest(TestCase):
    def test_creation(self):
        record = LocalHolidayCalendar.objects.create(
            date=date.today(),
            month=7,
            year=2026,
            day=18,
            week=29,
            event="Test Holiday",
            leave_type="full",
        )
        self.assertEqual(record.event, "Test Holiday")


class HistoricalWeatherModelTest(TestCase):
    def test_creation(self):
        record = HistoricalWeather.objects.create(
            name="Test City",
            datetime=date.today(),
            tempmax=30.0,
            tempmin=20.0,
            temp=25.0,
            feelslikemax=32.0,
            feelslikemin=22.0,
            feelslike=27.0,
            dew=15.0,
            humidity=50.0,
            precip=0.0,
            precipprob=0.0,
            windgust=10.0,
            windspeed=5.0,
            winddir=180.0,
            sealevelpressure=1013.0,
            cloudcover=10.0,
            visibility=10.0,
            solarradiation=200.0,
            solarenergy=10.0,
            uvindex=5,
            severerisk=10,
            sunrise=timezone.now(),
            sunset=timezone.now(),
            moonphase=0.5,
            conditions="Clear",
            description="Clear sky",
            icon="clear-day",
            stations="ST1",
        )
        self.assertEqual(record.name, "Test City")


class EmployeeMasterModelTest(TestCase):
    def test_creation(self):
        record = EmployeeMaster.objects.create(
            emp_code=1001,
            emp_name="Alice Smith",
            date_of_joining=date.today(),
            designation="Engineer",
            status=EmployeeStatus.ACTIVE,
        )
        self.assertEqual(record.emp_code, 1001)


class AttendanceMasterModelTest(TestCase):
    def test_creation(self):
        record = AttendanceMaster.objects.create(
            employee_id=1001,
            employee_name="Alice Smith",
            line="L1",
            factory="F1",
            floor="FL1",
            section="S1",
            attendance_date=date.today(),
            last_updated=timezone.now().time(),
            status="P",
            type="Primary",
            early_departure=False,
        )
        self.assertEqual(record.employee_id, 1001)
        self.assertEqual(str(record), f"Alice Smith - {date.today()}")


class PayableWorkingDaysModelTest(TestCase):
    def test_creation(self):
        record = PayableWorkingDays.objects.create(
            date=date.today(), month=7, year=2026, day=18, week=29
        )
        self.assertEqual(record.month, 7)
