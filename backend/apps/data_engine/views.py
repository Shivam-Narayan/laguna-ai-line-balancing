from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from apps.accounts.api.authentication import CookieJWTAuthentication

from .services.upload_service import run_upload_historical_weather_data, run_upload_attendance_file, run_add_local_holiday_calender, run_add_payable_working_days
from .services.export_service import run_get_calendar, run_export_operators_data, run_export_operators_data_email
from .services.employee_service import run_operators_data, run_generate_employee_master

@api_view(['POST'])
def upload_historical_weather_data(request):
    return run_upload_historical_weather_data(request.FILES.get('file'))

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def upload_attendance_file(request):
    return run_upload_attendance_file(request.FILES.get('file'))

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def add_local_holiday_calender(request):
    return run_add_local_holiday_calender(request.FILES.get('file'))

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def add_payable_working_days(request):
    return run_add_payable_working_days()

@api_view(['GET'])
def get_calendar(request):
    return run_get_calendar()

@api_view(['GET'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def export_operators_data(request):
    line_no = request.query_params.get('line', '').strip()
    return run_export_operators_data(line_no)

@api_view(['GET'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def export_operators_data_email(request):
    recipient_email = request.query_params.get('email', '').strip()
    line_no = request.query_params.get('line', '').strip()
    return run_export_operators_data_email(recipient_email, line_no)

@api_view(['GET'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def operators_data(request):
    line_no = request.query_params.get('line', ' ').strip()
    return run_operators_data(line_no)

@api_view(['GET'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def generate_employee_master(request):
    return run_generate_employee_master()
