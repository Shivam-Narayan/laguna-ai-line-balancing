from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from django.core.exceptions import ValidationError

from apps.accounts.api.authentication import CookieJWTAuthentication
from apps.accounts.utils.response_handlers import error_response

from .services.data_ingestion_service import run_styleob_file_upload, run_loading_plan_file_upload, run_loading_plan_file_upload_old, run_emp_fact_file_upload, run_wip_file_upload, run_fetch_emp_attendance_rockhr, run_fetch_emp_details_rockhr, fetch_and_transform_emp_attendance, fetch_and_transform_empdetails, run_fetch_wip_data_api, run_fetch_wip_data, run_uploading_planned_leaves, run_upload_wip_data, run_add_bulk_wip_data, run_upload_active_employees
from .services.manning_engine_service import manning_sheet_generation, run_generate_emp_fact, run_manning_generation, run_dday_generation, run_generate_style_ob
from .services.data_retrieval_service import run_get_manning_data, get_actual_vs_planned_data, get_dday_data, run_get_dday_manning_data, get_unallocated_employees_count, get_dday_actual_vs_planned_data, run_get_attendance_data, run_get_unallocated_employees, run_get_unallocated_employees_dday
from .services.allocation_service import run_update_allocated_employees, run_update_employee_on_hold_individual, run_update_employee_on_hold, run_update_allocated_capacity
from .services.export_service import run_download_manning_data_by_section, run_download_manning_attendance_data, run_download_notification_file
from .services.notification_service import run_get_user_notifications, run_mark_notification_read, run_create_test_notification

NOTIFICATION_DISPLAY_TIME = {
    "dday_8_50": "8:50 AM",
    "dday_12_45": "12:45 PM",
    "dday_5_30": "5:30 PM",
}

NOTIFICATION_DISPLAY_TITLE = {
    'dday_8_50': 'D-Day 8:50 AM Allocation Data',
    'dday_12_45': 'D-day 12:45 PM Allocation Data',
    'dday_5_30': 'D-Day 5:30 PM Allocation Data',
    'manning_sheet': 'Manning Sheet Allocation Data',
    'absenteeism_prediction': 'Absenteeism Prediction Data',
}

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated]) 
def manning_allocation(request):
    try:
        try:
            viaAPI = True
            # Extract data strictly in the view layer
            PERIOD = request.query_params.get('period', 60)
            
            # Pass pure python primitives to the service layer
            return run_manning_generation(viaAPI, PERIOD)
        except Exception as e:
            return error_response(error=f"Failed in manning sheet generation. {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except ValidationError as ve:
        return error_response(error=f"{str(ve)}", status=status.HTTP_423_LOCKED)

@api_view(['GET'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_user_notifications(request):
    unread_only = request.query_params.get('unread_only', '').lower() == 'true'
    return run_get_user_notifications(request.user, unread_only)

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def mark_notification_read(request):
    mark_all = request.data.get('mark_all', False)
    notification_id = request.data.get('notification_id')
    return run_mark_notification_read(request.user, mark_all, notification_id)

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def create_test_notification(request):
    return run_create_test_notification(request.user)

@api_view(['GET'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def generate_emp_fact(request):
    try:
        return run_generate_emp_fact()
    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def generate_dday_manning_data(request):
    try:
        viaAPI = True
        return run_dday_generation(viaAPI)
    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def generate_style_ob(request):
    try:
        viaAPI = True
        return run_generate_style_ob(viaAPI)
    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def download_manning_data_by_section(request):
    line_no = request.query_params.get('line', ' ').strip()
    period = request.query_params.get('forecast_period', ' ').strip()
    return run_download_manning_data_by_section(line_no, period)

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def download_manning_attendance_data(request):
    line_no = request.query_params.get('line', '').strip().title()
    type_of_export = request.query_params.get('type', '').strip().lower()
    email = request.query_params.get('email', '').strip()
    return run_download_manning_attendance_data(line_no, type_of_export, email)

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def download_notification_file(request):
    notification_id = request.query_params.get('notification_id', None)
    return run_download_notification_file(notification_id, request.user)

@api_view(['GET', 'POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated]) 
def get_manning_data(request):
    line_no = request.query_params.get('line', '').strip().capitalize()
    section_value = request.query_params.get('section', '').strip().capitalize()
    period = request.query_params.get('forecast_period', '').strip()
    style = request.query_params.get('style', '').strip()
    planned_date = request.query_params.get('planned_date', '').strip()
    is_export = request.method == 'POST'
    return run_get_manning_data(line_no, section_value, period, style, planned_date, is_export)

@api_view(['GET'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_dday_manning_data(request):
    line_no = request.query_params.get('line', '').strip().capitalize()
    return run_get_dday_manning_data(line_no)

@api_view(['GET'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_attendance_data(request):
    line_no = request.query_params.get('line', 'all').strip().title()
    return run_get_attendance_data(line_no)

@api_view(['GET', 'POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_unallocated_employees(request):
    line_no = request.query_params.get('line', '').strip()
    forecast_period = request.query_params.get('forecast_period', '').strip()
    is_export = request.method == 'POST'
    return run_get_unallocated_employees(line_no, forecast_period, is_export)

@api_view(['GET', 'POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_unallocated_employees_dday(request):
    line_no = request.query_params.get('line', 'all').strip()
    is_export = request.method == 'POST'
    return run_get_unallocated_employees_dday(line_no, is_export)

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def styleob_file_upload(request):
    return run_styleob_file_upload(request.FILES.get('file'))

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def loading_plan_file_upload(request):
    return run_loading_plan_file_upload(request.FILES.get('file'))

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def loading_plan_file_upload_old(request):
    max_styles_per_day = request.POST.get('max_styles_per_day')
    custom_line_capacities = request.POST.get("line_capacities")
    return run_loading_plan_file_upload_old(request.FILES.get('file'), max_styles_per_day, custom_line_capacities)

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def emp_fact_file_upload(request):
    return run_emp_fact_file_upload(request.FILES.get('file'))

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def wip_file_upload(request):
    return run_wip_file_upload(request.FILES.get('file'))

@api_view(['GET'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def fetch_emp_attendance_rockhr(request):
    return run_fetch_emp_attendance_rockhr()

@api_view(['GET'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def fetch_emp_details_rockhr(request):
    return run_fetch_emp_details_rockhr()

@api_view(['GET'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def fetch_wip_data_api(request):
    return run_fetch_wip_data_api()

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def uploading_planned_leaves(request):
    return run_uploading_planned_leaves(request.FILES.get('file'))

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def upload_wip_data(request):
    return run_upload_wip_data(request.FILES.get('file'))

@api_view(['GET'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def add_bulk_wip_data(request):
    return run_add_bulk_wip_data(request.data)

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def upload_active_employees(request):
    return run_upload_active_employees(request.FILES.get('file'))

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def update_allocated_employees(request):
    final_allocation = request.data.get('final_allocation')
    dday_id = request.data.get('dday_id')
    return run_update_allocated_employees(final_allocation, dday_id)

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def update_employee_on_hold_individual(request):
    preferred_employee = request.data.get('preferred_employee')
    allocated_capacity = request.data.get('allocated_capacity')
    manning_id = request.data.get('manning_id')
    return run_update_employee_on_hold_individual(preferred_employee, allocated_capacity, manning_id)

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def update_employee_on_hold(request):
    multiple_ids = request.data.get('multiple_IDs', [])
    return run_update_employee_on_hold(multiple_ids)

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def update_allocated_capacity(request):
    allocated_capacity = request.data.get('allocated_capacity')
    manning_id = request.data.get('manning_id')
    return run_update_allocated_capacity(allocated_capacity, manning_id)
