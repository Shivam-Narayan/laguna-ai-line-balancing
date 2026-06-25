from . import views
from django.urls import path

urlpatterns = [
    path('holiday-calendars/', views.get_calendar, name='view calendar'),
    path('holiday-calendars/upload/', views.add_local_holiday_calender, name='add_local_holiday_calender'),
    path('historical-weather/upload/', views.upload_historical_weather_data, name='historical-weather-data'),
    path('operators/', views.operators_data, name='operatos-data-from-employee-master'),
    path('operators/export/csv/', views.export_operators_data, name='export-operators-data'),
    path('operators/export/email/', views.export_operators_data_email, name='export-operators-data-email'),
    path('attendance/upload/', views.upload_attendance_file, name='upload attendance file'),
    path('employees/generate/', views.generate_employee_master, name='generate_employee_master'),
    path('payable-working-days/', views.add_payable_working_days, name='add_payable_working_days'),
]


data_engine_endpoints = [
    f"/data/{pattern.pattern}" for pattern in urlpatterns
]