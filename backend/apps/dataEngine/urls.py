from . import views
from django.urls import path

urlpatterns = [
    path('get-holidaycalendar/', views.get_calendar, name='view calendar'),
    path('add-historicalweatherdata/', views.upload_historical_weather_data, name='historical-weather-data'),
    path('operators-data/', views.operators_data, name='operatos-data-from-employee-master'),
    path('export-operators-data/', views.export_operators_data, name='export-operators-data'),
    path('export-operators-data-email/', views.export_operators_data_email, name='export-operators-data-email'),
    path('upload-attendance-file/', views.upload_attendance_file, name='upload attendance file'),
    path('generate_employee_master/', views.generate_employee_master, name='generate_employee_master'),
    path('add_local_holiday_calender/', views.add_local_holiday_calender, name='add_local_holiday_calender'),
    path('add_payable_working_days/', views.add_payable_working_days, name='add_payable_working_days'),
]


dataEngine_endpoints = [
    f"/data/{pattern.pattern}" for pattern in urlpatterns
]