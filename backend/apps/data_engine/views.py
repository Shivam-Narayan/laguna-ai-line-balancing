from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from apps.accounts.authentication import CookieJWTAuthentication
from apps.accounts.utils.response_handlers import error_response, success_response
from config.idempotency import idempotent

from .services.employee_service import EmployeeMasterGenerator, EmployeeService, EmployeeServiceError
from .services.export_service import (
    run_export_operators_data,
    run_export_operators_data_email,
    run_get_calendar,
)
from .services.upload_service import (
    run_add_local_holiday_calender,
    run_add_payable_working_days,
    run_upload_attendance_file,
    run_upload_historical_weather_data,
)


def run_operators_data(line_no: str):
    return EmployeeService.get_operators_data(line_no)


def run_generate_employee_master():
    generator = EmployeeMasterGenerator()
    generator.generate()
    return success_response(
        message="Employee Master data is generated successfully.",
        status=status.HTTP_200_OK,
    )


class HistoricalWeatherUploadAPIView(APIView):
    def post(self, request):
        return run_upload_historical_weather_data(request.FILES.get("file"))


class AttendanceFileUploadAPIView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return run_upload_attendance_file(request.FILES.get("file"))


class LocalHolidayCalendarUploadAPIView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return run_add_local_holiday_calender(request.FILES.get("file"))


class PayableWorkingDaysAPIView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    @idempotent(timeout=300)
    def post(self, request):
        return run_add_payable_working_days()


class CalendarAPIView(APIView):
    def get(self, request):
        return run_get_calendar()


class ExportOperatorsDataAPIView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        line_no = request.query_params.get("line", "").strip()
        return run_export_operators_data(line_no)


class ExportOperatorsDataEmailAPIView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        recipient_email = request.query_params.get("email", "").strip()
        line_no = request.query_params.get("line", "").strip()
        return run_export_operators_data_email(recipient_email, line_no)


class OperatorsDataAPIView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        line_no = request.query_params.get("line", " ").strip()
        try:
            result = run_operators_data(line_no)
            if isinstance(result, (HttpResponse,)):
                return result
            if not result:
                return error_response(
                    error=f"No data found for {line_no}", status=status.HTTP_200_OK
                )
            return success_response(
                message=f"Data for {line_no} fetched successfully.",
                data=result,
                status=status.HTTP_200_OK,
            )
        except ValueError as e:
            return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
        except EmployeeServiceError as e:
            return error_response(error=str(e), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class GenerateEmployeeMasterAPIView(APIView):
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            result = run_generate_employee_master()
            if isinstance(result, HttpResponse):
                return result
            return result
        except ValueError as e:
            return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
        except EmployeeServiceError as e:
            return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
