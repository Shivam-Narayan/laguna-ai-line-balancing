from django.urls import path

from . import views

urlpatterns = [
    path("holiday-calendars/", views.CalendarAPIView.as_view(), name="get-calendar"),
    path(
        "holiday-calendars/upload/",
        views.LocalHolidayCalendarUploadAPIView.as_view(),
        name="add-local-holiday-calender",
    ),
    path(
        "historical-weather/upload/",
        views.HistoricalWeatherUploadAPIView.as_view(),
        name="upload-historical-weather-data",
    ),
    path(
        "operators/", 
        views.OperatorsDataAPIView.as_view(), 
        name="operators-data"
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
        name="upload-attendance-file",
    ),
    path(
        "employees/generate/",
        views.GenerateEmployeeMasterAPIView.as_view(),
        name="generate-employee-master",
    ),
    path(
        "payable-working-days/",
        views.PayableWorkingDaysAPIView.as_view(),
        name="add-payable-working-days",
    ),
]

data_engine_endpoints = [f"/data/{pattern.pattern}" for pattern in urlpatterns]
