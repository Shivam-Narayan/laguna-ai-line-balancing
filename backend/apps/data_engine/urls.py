from django.urls import path

from . import views

urlpatterns = [
    path("holiday-calendars/", views.CalendarAPIView.as_view(), name="view calendar"),
    path(
        "holiday-calendars/upload/",
        views.LocalHolidayCalendarUploadAPIView.as_view(),
        name="add_local_holiday_calender",
    ),
    path(
        "historical-weather/upload/",
        views.HistoricalWeatherUploadAPIView.as_view(),
        name="historical-weather-data",
    ),
    path(
        "operators/", 
        views.OperatorsDataAPIView.as_view(), 
        name="operatos-data-from-employee-master"
    ),
    path(
        "operators/export/csv/",
        views.ExportOperatorsDataAPIView.as_view(),
        name="export-operators-data",
    ),
    path(
        "operators/export/email/",
        views.ExportOperatorsDataEmailAPIView.as_view(),
        name="export-operators-data-email",
    ),
    path(
        "attendance/upload/",
        views.AttendanceFileUploadAPIView.as_view(),
        name="upload attendance file",
    ),
    path(
        "employees/generate/",
        views.GenerateEmployeeMasterAPIView.as_view(),
        name="generate_employee_master",
    ),
    path(
        "payable-working-days/",
        views.PayableWorkingDaysAPIView.as_view(),
        name="add_payable_working_days",
    ),
]

data_engine_endpoints = [f"/data/{pattern.pattern}" for pattern in urlpatterns]
