from django.core.exceptions import ValidationError
from django.utils.decorators import method_decorator
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.accounts.authentication import CookieJWTAuthentication
from apps.accounts.utils.response_handlers import error_response
from config.idempotency import idempotent

from .services.allocation_service import (
    run_update_allocated_capacity,
    run_update_allocated_employees,
    run_update_employee_on_hold,
    run_update_employee_on_hold_individual,
)
from .services.data_ingestion_service import (
    run_add_bulk_wip_data,
    run_emp_fact_file_upload,
    run_fetch_emp_attendance_rockhr,
    run_fetch_emp_details_rockhr,
    run_fetch_wip_data_api,
    run_loading_plan_file_upload,
    run_loading_plan_file_upload_old,
    run_styleob_file_upload,
    run_upload_active_employees,
    run_upload_wip_data,
    run_uploading_planned_leaves,
    run_wip_file_upload,
)
from .services.data_retrieval_service import (
    run_get_attendance_data,
    run_get_dday_manning_data,
    run_get_manning_data,
    run_get_unallocated_employees,
    run_get_unallocated_employees_dday,
)
from .services.export_service import (
    run_download_manning_attendance_data,
    run_download_manning_data_by_section,
    run_download_notification_file,
)
from .services.manning_engine_service import (
    run_dday_generation,
    run_generate_emp_fact,
    run_generate_style_ob,
    run_manning_generation,
)
from .services.notification_service import (
    run_create_test_notification,
    run_get_user_notifications,
    run_mark_notification_read,
)

NOTIFICATION_DISPLAY_TIME = {
    "dday_8_50": "8:50 AM",
    "dday_12_45": "12:45 PM",
    "dday_5_30": "5:30 PM",
}

NOTIFICATION_DISPLAY_TITLE = {
    "dday_8_50": "D-Day 8:50 AM Allocation Data",
    "dday_12_45": "D-day 12:45 PM Allocation Data",
    "dday_5_30": "D-Day 5:30 PM Allocation Data",
    "manning_sheet": "Manning Sheet Allocation Data",
    "absenteeism_prediction": "Absenteeism Prediction Data",
}


class BaseManningSheetAPIView(APIView):
    """
    Base class for all Manning Sheet views.
    Centralises authentication and permission configuration in one place,
    eliminating the need for @authentication_classes / @permission_classes
    decorators on every function.
    """
    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]


# ---------------------------------------------------------------------------
# Manning Engine Views
# ---------------------------------------------------------------------------

@method_decorator(idempotent(timeout=300), name="post")
class ManningAllocationAPIView(BaseManningSheetAPIView):
    """POST /manning-sheets/generate/ — Trigger the Manning Sheet algorithm."""

    def post(self, request):
        try:
            try:
                viaAPI = True
                PERIOD = request.query_params.get("period", 60)
                return run_manning_generation(viaAPI, PERIOD)
            except Exception as e:
                return error_response(
                    error=f"Failed in manning sheet generation. {str(e)}",
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
        except ValidationError as ve:
            return error_response(error=f"{str(ve)}", status=status.HTTP_423_LOCKED)


class GenerateEmpFactAPIView(BaseManningSheetAPIView):
    """GET /emp-facts/generate/ — Fetch and populate EMPFact table."""

    def get(self, request):
        try:
            return run_generate_emp_fact()
        except Exception as e:
            return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)


@method_decorator(idempotent(timeout=300), name="post")
class GenerateDdayManningAPIView(BaseManningSheetAPIView):
    """POST /manning-sheets/d-day/generate/ — Run the D-Day intraday allocation."""

    def post(self, request):
        try:
            return run_dday_generation(viaAPI=True)
        except Exception as e:
            return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)


class GenerateStyleObAPIView(BaseManningSheetAPIView):
    """GET /style-obs/generate/ — Rebuild the StyleOB table."""

    def get(self, request):
        try:
            return run_generate_style_ob(viaAPI=True)
        except Exception as e:
            return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Data Retrieval Views
# ---------------------------------------------------------------------------

class ManningDataAPIView(BaseManningSheetAPIView):
    """GET /manning-sheets/ — Retrieve manning sheet data. POST — Export to Excel."""

    def get(self, request):
        return self._handle(request, is_export=False)

    def post(self, request):
        return self._handle(request, is_export=True)

    def _handle(self, request, is_export):
        line_no = request.query_params.get("line", "").strip().capitalize()
        section_value = request.query_params.get("section", "").strip().capitalize()
        period = request.query_params.get("forecast_period", "").strip()
        style = request.query_params.get("style", "").strip()
        planned_date = request.query_params.get("planned_date", "").strip()
        return run_get_manning_data(line_no, section_value, period, style, planned_date, is_export)


class DdayManningDataAPIView(BaseManningSheetAPIView):
    """GET /manning-sheets/d-day/ — Retrieve D-Day manning data."""

    def get(self, request):
        line_no = request.query_params.get("line", "").strip().capitalize()
        return run_get_dday_manning_data(line_no)


class AttendanceDataAPIView(BaseManningSheetAPIView):
    """GET /attendance/ — Retrieve attendance data."""

    def get(self, request):
        line_no = request.query_params.get("line", "all").strip().title()
        return run_get_attendance_data(line_no)


class UnallocatedEmployeesAPIView(BaseManningSheetAPIView):
    """GET /employees/unallocated/ — Retrieve. POST — Export to Excel."""

    def get(self, request):
        return self._handle(request, is_export=False)

    def post(self, request):
        return self._handle(request, is_export=True)

    def _handle(self, request, is_export):
        line_no = request.query_params.get("line", "").strip()
        forecast_period = request.query_params.get("forecast_period", "").strip()
        return run_get_unallocated_employees(line_no, forecast_period, is_export)


class UnallocatedEmployeesDdayAPIView(BaseManningSheetAPIView):
    """GET /employees/unallocated/d-day/ — Retrieve. POST — Export."""

    def get(self, request):
        return self._handle(request, is_export=False)

    def post(self, request):
        return self._handle(request, is_export=True)

    def _handle(self, request, is_export):
        line_no = request.query_params.get("line", "all").strip()
        return run_get_unallocated_employees_dday(line_no, is_export)


# ---------------------------------------------------------------------------
# Export Views
# ---------------------------------------------------------------------------

class DownloadManningDataBySectionAPIView(BaseManningSheetAPIView):
    """POST /manning-sheets/export/ — Download per-section manning Excel."""

    def post(self, request):
        line_no = request.query_params.get("line", " ").strip()
        period = request.query_params.get("forecast_period", " ").strip()
        return run_download_manning_data_by_section(line_no, period)


class DownloadManningAttendanceAPIView(BaseManningSheetAPIView):
    """POST /attendance/export/ — Download attendance/D-Day Excel or send email."""

    def post(self, request):
        line_no = request.query_params.get("line", "").strip().title()
        type_of_export = request.query_params.get("type", "").strip().lower()
        email = request.query_params.get("email", "").strip()
        return run_download_manning_attendance_data(line_no, type_of_export, email)


class DownloadNotificationFileAPIView(BaseManningSheetAPIView):
    """POST /notifications/download/ — Download file attached to a notification."""

    def post(self, request):
        notification_id = request.query_params.get("notification_id", None)
        return run_download_notification_file(notification_id, request.user)


# ---------------------------------------------------------------------------
# Notification Views
# ---------------------------------------------------------------------------

class UserNotificationsAPIView(BaseManningSheetAPIView):
    """GET /notifications/ — Get user's recent notifications."""

    def get(self, request):
        unread_only = request.query_params.get("unread_only", "").lower() == "true"
        return run_get_user_notifications(request.user, unread_only)


class MarkNotificationReadAPIView(BaseManningSheetAPIView):
    """POST /notifications/mark-read/ — Mark one or all notifications as read."""

    def post(self, request):
        mark_all = request.data.get("mark_all", False)
        notification_id = request.data.get("notification_id")
        return run_mark_notification_read(request.user, mark_all, notification_id)


class CreateTestNotificationAPIView(BaseManningSheetAPIView):
    """POST /notifications/test/ — Create test notifications."""

    def post(self, request):
        return run_create_test_notification(request.user)


# ---------------------------------------------------------------------------
# Data Ingestion Views
# ---------------------------------------------------------------------------

class StyleObFileUploadAPIView(BaseManningSheetAPIView):
    """POST /style-obs/upload/ — Upload Style OB Excel file."""

    def post(self, request):
        return run_styleob_file_upload(request.FILES.get("file"))


class LoadingPlanFileUploadAPIView(BaseManningSheetAPIView):
    """POST /loading-plans/upload/ — Upload Loading Plan Excel file (new format)."""

    def post(self, request):
        return run_loading_plan_file_upload(request.FILES.get("file"))


class LoadingPlanFileUploadOldAPIView(BaseManningSheetAPIView):
    """POST /loading-plans/upload-old/ — Upload Loading Plan Excel file (old format)."""

    def post(self, request):
        max_styles_per_day = request.POST.get("max_styles_per_day")
        custom_line_capacities = request.POST.get("line_capacities")
        return run_loading_plan_file_upload_old(
            request.FILES.get("file"), max_styles_per_day, custom_line_capacities
        )


class EmpFactFileUploadAPIView(BaseManningSheetAPIView):
    """POST /emp-facts/upload/ — Upload Employee Fact Excel file."""

    def post(self, request):
        return run_emp_fact_file_upload(request.FILES.get("file"))


class WipFileUploadAPIView(BaseManningSheetAPIView):
    """POST /wips/upload-file/ — Upload WIP Excel file."""

    def post(self, request):
        return run_wip_file_upload(request.FILES.get("file"))


class FetchEmpAttendanceRockHRAPIView(BaseManningSheetAPIView):
    """GET /attendance/rockhr/ — Fetch attendance from RockHR API."""

    def get(self, request):
        return run_fetch_emp_attendance_rockhr()


class FetchEmpDetailsRockHRAPIView(BaseManningSheetAPIView):
    """GET /employees/rockhr/ — Fetch employee details from RockHR API."""

    def get(self, request):
        return run_fetch_emp_details_rockhr()


class FetchWipDataAPIView(BaseManningSheetAPIView):
    """GET /wips/ — Fetch WIP data from external API."""

    def get(self, request):
        return run_fetch_wip_data_api()


class UploadingPlannedLeavesAPIView(BaseManningSheetAPIView):
    """POST /planned-leaves/upload/ — Upload planned leaves Excel file."""

    def post(self, request):
        return run_uploading_planned_leaves(request.FILES.get("file"))


class UploadWipDataAPIView(BaseManningSheetAPIView):
    """POST /wips/upload/ — Upload WIP data from Excel file."""

    def post(self, request):
        return run_upload_wip_data(request.FILES.get("file"))


class AddBulkWipDataAPIView(BaseManningSheetAPIView):
    """GET /wips/bulk/ — Bulk add WIP data from request payload."""

    def get(self, request):
        return run_add_bulk_wip_data(request.data)


class UploadActiveEmployeesAPIView(BaseManningSheetAPIView):
    """POST /employees/upload/ — Upload Active Employees Excel file."""

    def post(self, request):
        return run_upload_active_employees(request.FILES.get("file"))


# ---------------------------------------------------------------------------
# Allocation Management Views
# ---------------------------------------------------------------------------

@method_decorator(idempotent(timeout=300), name="post")
class UpdateAllocatedEmployeesAPIView(BaseManningSheetAPIView):
    """POST /employees/allocated/ — Update the final employee allocation."""

    def post(self, request):
        final_allocation = request.data.get("final_allocation")
        dday_id = request.data.get("dday_id")
        return run_update_allocated_employees(final_allocation, dday_id)


@method_decorator(idempotent(timeout=300), name="post")
class UpdateEmployeeOnHoldAPIView(BaseManningSheetAPIView):
    """POST /employees/on-hold/ — Bulk update employees on hold."""

    def post(self, request):
        multiple_ids = request.data.get("multiple_IDs", [])
        return run_update_employee_on_hold(multiple_ids)


@method_decorator(idempotent(timeout=300), name="post")
class UpdateAllocatedCapacityAPIView(BaseManningSheetAPIView):
    """POST /employees/capacity/ — Update allocated capacity for a manning row."""

    def post(self, request):
        allocated_capacity = request.data.get("allocated_capacity")
        manning_id = request.data.get("manning_id")
        return run_update_allocated_capacity(allocated_capacity, manning_id)
