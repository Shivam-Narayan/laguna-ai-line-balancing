import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta
from io import BytesIO

import pandas as pd
from django.db.models import Count, FloatField, Func
from django.http import FileResponse, HttpResponse

from apps.data_engine.models import EmployeeMaster

from ..models import (
    ManningGeneralInfo,
    ManningSheetData,
    PushNotification,
)
from ..utils import (
    export_json_to_excel,
    fetch_attendance_data,
    fetch_dday_data,
)

logger = logging.getLogger("general")

CHUNK_SIZE = 1000
os.makedirs("exports", exist_ok=True)


class Round(Func):
    function = "ROUND"
    arity = 2
    output_field = FloatField()


class ExportServiceError(Exception):
    pass


def get_unallocated_employees_count(line_no):
    """Helper: returns the count of unallocated operators from the CSV report."""
    file_path = "exports/unallocated_report_dday.csv"
    if not os.path.exists(file_path):
        return 0
    try:
        df = pd.read_csv(file_path, usecols=["line", "reason", "type"])
        df = df[(df["reason"] != "Employee Absent") & (df["type"] == "Primary")]
        if line_no.lower() != "all":
            return (df["line"] == line_no.title()).sum()
        else:
            return len(df)
    except Exception as e:
        logger.info(f"Error reading unallocated report: {e}")
        return 0


def get_actual_vs_planned_data(line_no, forecast_period, today, section=None):
    """Helper: imported from data_retrieval_service to avoid circular imports."""
    from .data_retrieval_service import get_actual_vs_planned_data as _get
    return _get(line_no=line_no, forecast_period=forecast_period, today=today, section=section)


def get_dday_actual_vs_planned_data(line_no, today):
    """Helper: imported from data_retrieval_service."""
    from .data_retrieval_service import get_dday_actual_vs_planned_data as _get
    return _get(line_no=line_no, today=today)


class ExportService:
    """Handles Excel export and file download business logic."""

    @staticmethod
    def download_manning_data_by_section(line_no, period):
        """Returns an HttpResponse with the manning sheet Excel file."""
        line_no = line_no.capitalize()

        if not line_no or not period:
            raise ValueError('"line" and "forecast_period" are required.')

        valid_lines = [f"Line {i}" for i in range(1, 11)] + ["All"]
        valid_periods = ["1", "7", "30", "60"]

        if line_no not in valid_lines:
            raise ValueError('Invalid line number. Use "Line X" or "all"')
        if period not in valid_periods:
            raise ValueError("Invalid forecast period. Choose from 1, 7, 30, 60.")

        period = int(period)
        today = datetime.today().date()
        date_range = [(today + timedelta(days=i)) for i in range(1, period + 1)]
        filters = {"planned_dates__in": date_range}
        employee_master_filters = {"designation": "machinist"}

        if line_no.lower() != "all":
            filters["line"] = line_no
            employee_master_filters["line"] = line_no.upper()

        filtered_data_table = ManningSheetData.objects.filter(**filters).distinct()
        filtered_data_info = ManningGeneralInfo.objects.filter(**filters).distinct()

        if not filtered_data_table.exists() and not filtered_data_info.exists():
            empty_data = {
                "table_data": {},
                "machinist_nonMachinist_count": {},
                "machinist_nonMachinist_info": {},
                "info": {},
                "unique_styles": {},
                "prediction_report": {},
                "message": "No data to display",
            }
            excel_data = export_json_to_excel(empty_data)
            response = HttpResponse(
                excel_data.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = (
                f'attachment; filename="{line_no.title()}_ManningSheet__{period}Days.xlsx"'
            )
            return response

        table_data_query = filtered_data_table.order_by("planned_dates", "op_seq").values()

        grouped_table_data = {}
        for row in table_data_query:
            section = row["section"]
            if section not in grouped_table_data:
                grouped_table_data[section] = []
            grouped_table_data[section].append(
                {
                    "Date": row["planned_dates"].strftime("%d-%m-%Y") if row["planned_dates"] else row["planned_dates"],
                    "Operation": row["operation"],
                    "Style": row["style"],
                    "Buyer": row["buyer"],
                    "Color": row["color"].upper() if row["color"] else row["color"],
                    "OC Number": row["oc_no"].upper() if row["oc_no"] else row["oc_no"],
                    "Order Number": row["order_no"],
                    "Machine Type": row["machine_type"],
                    "Operator Name": row["allocated_emp_name"],
                    "Operator ID": row["allocated_emp_id"],
                    "SAM": row["sam"],
                    "Week": row["week"],
                    "Planned Quantity": row["planned_qty"],
                    "Allocated Capacity": row["allocated_capacity"],
                    "Shortage Reason": row["shortage_reason"],
                }
            )

        actual_machinists = list(
            EmployeeMaster.objects.filter(**employee_master_filters)
            .values("section")
            .annotate(actual_machinists=Count("emp_code"))
        )

        grouped_result = defaultdict(lambda: defaultdict(set))
        grouped_data = filtered_data_table.only("section", "operation", "machine_type", "allocated_emp_name", "allocated_emp_id")

        for row in grouped_data:
            section = row.section or "Unknown"
            operation = row.operation or "Unknown"
            key = (row.machine_type, row.allocated_emp_name or "N/A", row.allocated_emp_id)
            grouped_result[section][operation].add(key)

        grouped_machine_nonMachine_info = {}
        required_machinists = []

        for section, operations in grouped_result.items():
            machine_type_count = defaultdict(int)
            machinist_count = 0
            for entries in operations.values():
                for machine_type, operator_name, operator_id in entries:
                    machine_type_count[machine_type] += 1
                    machinist_count += 1
            grouped_machine_nonMachine_info[section] = dict(machine_type_count)
            required_machinists.append({"section": section, "required_machinists": machinist_count})

        actual_dict = {item["section"]: item["actual_machinists"] for item in actual_machinists}
        required_dict = {item["section"]: item["required_machinists"] for item in required_machinists}

        grouped_general_info = {}
        for section in set(actual_dict) | set(required_dict):
            grouped_general_info[section] = {
                "total_required": required_dict.get(section, 0),
                "total_available": actual_dict.get(section, 0),
            }

        grouped_info = {}
        info_query = filtered_data_table.values("section").annotate(buyers=Count("buyer", distinct=True))
        for entry in info_query:
            section = entry["section"]
            buyers_list = list(filtered_data_table.filter(section=section).values_list("buyer", flat=True).distinct())
            grouped_info[section] = {"buyers": [buyer.upper() for buyer in buyers_list if buyer]}

        grouped_unique_styles = {}
        for entry in filtered_data_table.values("section").annotate(styles=Count("style", distinct=True)):
            section = entry["section"]
            styles_list = list(filtered_data_table.filter(section=section).values_list("style", flat=True).distinct())
            grouped_unique_styles[section] = {"unique_styles": [style.upper() for style in styles_list if style]}

        grouped_prediction_report = {}
        for sec in ["Assembly", "Cuff", "Front", "Back", "Sleeve", "Collar"]:
            prediction_response = get_actual_vs_planned_data(line_no=line_no, forecast_period=period, today=today, section=sec)
            grouped_prediction_report[sec] = prediction_response.data["data"]

        response_data = {
            "table_data": grouped_table_data,
            "machinist_nonMachinist_count": grouped_general_info,
            "machinist_nonMachinist_info": grouped_machine_nonMachine_info,
            "info": grouped_info,
            "unique_styles": grouped_unique_styles,
            "prediction_report": grouped_prediction_report,
            "message": "Success",
        }

        excel_data = export_json_to_excel(response_data)
        response = HttpResponse(
            excel_data.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="{line_no.title()}_ManningSheet__{period}Days.xlsx"'
        )
        return response

    @staticmethod
    def download_manning_attendance_data(line_no, type_of_export, email):
        """Returns an HttpResponse (excel download) or sends an email with the attendance export."""
        if not line_no:
            raise ValueError('"line" is required.')
        if line_no not in {f"Line {i}" for i in range(1, 11)} | {"All"}:
            raise ValueError('Enter a valid line number (Valid Formats: "Line 1" or "line 3" or "LINE 5" or "all")')

        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        dday_data = fetch_dday_data(line_no)
        attendance_data = fetch_attendance_data(line_no, today, yesterday)
        prediction_response = get_dday_actual_vs_planned_data(line_no=line_no, today=today)
        prediction_data = prediction_response.data["data"]["Target data"]

        production_target = prediction_data.get("production_target", 0.0)
        predicted_production = prediction_data.get("predicted_production", 0.0)
        unallocated_emp_data = get_unallocated_employees_count(line_no=line_no)

        df = pd.DataFrame(dday_data["data"]["records"])
        df.drop(columns=["Dday_ID", "WIP Qty"], inplace=True)

        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, sheet_name="Sheet1", startrow=9, index=False)
            worksheet = writer.sheets["Sheet1"]
            workbook = writer.book
            bold_format = workbook.add_format({"bold": True})
            worksheet.write(0, 0, "Line number", bold_format)
            worksheet.write(0, 1, line_no)
            worksheet.write(1, 0, "Planned Attendance", bold_format)
            worksheet.write(1, 1, attendance_data["data"]["attendance_data"]["Planned Attendance"])
            worksheet.write(2, 0, "Present", bold_format)
            worksheet.write(2, 1, attendance_data["data"]["attendance_data"]["Present"])
            worksheet.write(3, 0, "Absent", bold_format)
            worksheet.write(3, 1, attendance_data["data"]["attendance_data"]["Absent"])
            worksheet.write(4, 0, "Unallocated Operators", bold_format)
            worksheet.write(4, 1, unallocated_emp_data)
            worksheet.write(5, 0, "Production Target", bold_format)
            worksheet.write(5, 1, production_target)
            worksheet.write(6, 0, "Predicted Production", bold_format)
            worksheet.write(6, 1, predicted_production)
            worksheet.set_column(0, 0, 25)
            worksheet.set_column(1, 1, 15)
            for i, col in enumerate(df.columns):
                if col != "Factory":
                    max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2
                    worksheet.set_column(i, i, max_len, workbook.add_format({"text_wrap": False}))
            preferred_col_index = list(df.columns).index("Preferred Employees")
            worksheet.set_column(preferred_col_index, preferred_col_index, 30)
            truncate_format = workbook.add_format({"text_wrap": False, "num_format": "@"})
            for row_num in range(10, 10 + len(df)):
                worksheet.write(row_num, preferred_col_index, df["Preferred Employees"].iloc[row_num - 10], truncate_format)
        output.seek(0)

        if type_of_export == "email":
            if not email:
                raise ValueError("Email address is required.")
            import base64
            from apps.absenteeism.tasks import send_email_task
            encoded_excel = base64.b64encode(output.getvalue()).decode()
            send_email_task.delay(
                recipient_emails=email,
                encoded_data=encoded_excel,
                subject="Download D-Day Manning Data File",
                file_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                file_name=f"Dday_Manning_data_{line_no}.xlsx",
            )
            return None, f"Email is being sent to {email} in the background."
        elif type_of_export == "excel":
            response = HttpResponse(
                output.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = f'attachment; filename="Dday_Manning_data_{line_no}.xlsx"'
            return response, None
        else:
            raise ValueError('Type should be "email" or "excel".')

    @staticmethod
    def download_notification_file(notification_id, user):
        """Returns a FileResponse for the file attached to a notification."""
        if not notification_id:
            raise ValueError("Notification ID is required")

        base_filter = {"user": user, "id": notification_id}
        try:
            notification = PushNotification.objects.get(**base_filter)
        except PushNotification.DoesNotExist:
            raise LookupError("Notification not found")

        if not notification.data:
            raise LookupError("No data available for this notification")
        if "fileName" not in notification.data:
            raise LookupError("File name not found in notification data")

        file_name = notification.data["fileName"]
        file_path = os.path.join("exports", file_name)

        if not os.path.exists(file_path):
            raise LookupError("File not found")

        return FileResponse(open(file_path, "rb"), as_attachment=True, filename=file_name)


# --- Backward Compatibility Wrappers ---
def run_download_manning_data_by_section(line_no, period):
    from rest_framework import status
    from apps.accounts.utils.response_handlers import error_response, success_response
    try:
        return ExportService.download_manning_data_by_section(line_no, period)
    except ValueError as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def run_download_manning_attendance_data(line_no, type_of_export, email):
    from rest_framework import status
    from apps.accounts.utils.response_handlers import error_response, success_response
    try:
        result, msg = ExportService.download_manning_attendance_data(line_no, type_of_export, email)
        if result is None:
            return success_response(message=msg, data={"message": "File attached to the email."}, status=status.HTTP_200_OK)
        return result
    except ValueError as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
    except Exception:
        return error_response(error="An unexpected error occurred. Please try again later.", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def run_download_notification_file(notification_id, user):
    from rest_framework import status
    from apps.accounts.utils.response_handlers import error_response
    try:
        return ExportService.download_notification_file(notification_id, user)
    except ValueError as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
    except LookupError as e:
        return error_response(error=str(e), status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return error_response(error=f"Failed to retrieve notification's data: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
