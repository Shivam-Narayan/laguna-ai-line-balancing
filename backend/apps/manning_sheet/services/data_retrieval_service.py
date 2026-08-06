import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta
from io import BytesIO

import pandas as pd
from django.db.models import FloatField, Func, Sum
from django.http import HttpResponse
from django.core.cache import cache
from rest_framework import status

from apps.accounts.models import User
from apps.accounts.utils.response_handlers import error_response, success_response
from apps.data_engine.models import EmployeeMaster

from ..models import (
    DDayData,
    EmployeesOnHold,
    LoadingPlan,
    ManningGeneralInfo,
    ManningSheetData,
    UnallocatedEmployees,
)
from ..utils import (
    create_bulk_push_notifications,
    export_to_excel,
    fetch_attendance_data,
    fetch_dday_data,
    get_notification_type_by_time,
    remove_duplicate_employee_dicts,
    update_sections,
)

logger = logging.getLogger("general")

CHUNK_SIZE = 1000
os.makedirs("exports", exist_ok=True)
COMPANY_CODE = 843

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


class Round(Func):
    function = "ROUND"
    arity = 2
    output_field = FloatField()


class DataRetrievalServiceError(Exception):
    pass


def get_actual_vs_planned_data(
    line_no,
    forecast_period,
    today,
    summation=False,
    section=None,
    dday=None,
    planned_date=None,
):
    """
    Internal helper: returns a DRF Response with predicted vs target production data.
    Used internally by views and other services - keeps DRF response for now as it
    is used recursively and as a data source internally.
    """
    try:
        filter_date = today if dday else today + timedelta(days=forecast_period)
        filter_date = planned_date if planned_date else filter_date

        manning_sheet_filter = {"planned_dates": filter_date, "machinist": True}
        loading_plan_filter = {"planned_dates": filter_date}
        employee_filter = {}

        if line_no.lower() != "all":
            employee_filter["line"] = line_no.upper()

        if section is not None:
            sections = [section]
            employee_filter["section"] = section
            manning_sheet_filter["section"] = section
        else:
            sections = ["Assembly", "Cuff", "Front", "Back", "Sleeve", "Collar"]

        total_emp_count = EmployeeMaster.objects.filter(**employee_filter).count()
        if total_emp_count == 0:
            return (
                None,
                None,
                error_response(error="No employees found.", status=status.HTTP_404_NOT_FOUND),
            )

        if line_no.lower() != "all":
            loading_plan_filter["line"] = line_no.title()
            manning_sheet_filter["line"] = line_no.title()

        manning_sheet_qs = ManningSheetData.objects.filter(**manning_sheet_filter)
        manning_sheet_target = manning_sheet_qs.values("section", "code", "style").annotate(
            total_planned_qty=Sum("allocated_capacity")
        )

        min_entries = {}
        for item in manning_sheet_target:
            key = (item["section"], item["style"])
            qty = item["total_planned_qty"]
            if key not in min_entries or qty < min_entries[key]["total_planned_qty"]:
                min_entries[key] = item

        min_entries_list = list(min_entries.values())
        section_summary = defaultdict(float)
        for item in min_entries_list:
            section_summary[item["section"]] += item["total_planned_qty"]

        result = [{"section": sec, "total_planned_qty": qty} for sec, qty in section_summary.items()]

        total_planned_qty = (
            LoadingPlan.objects.filter(**loading_plan_filter).aggregate(
                total_planned_qty=Sum("planned_qty")
            )
        )["total_planned_qty"] or 0

        production_target = [
            {"section": section, "total_planned_qty": round(total_planned_qty, 2)}
            for section in sections
        ]

        predicted_production = update_sections(result, sections)

        if line_no.lower() == "all":
            all_line_predictions = {}
            for line_index in range(1, 11):
                individual_line = f"line {line_index}"
                response_data = get_actual_vs_planned_data(
                    line_no=individual_line,
                    forecast_period=forecast_period,
                    today=today,
                    summation=True,
                    section=section,
                    dday=dday,
                )
                response_data = response_data.data

                if isinstance(response_data, tuple):
                    continue
                if "data" in response_data and "Target data" in response_data["data"]:
                    prediction_data = response_data["data"]["Target data"][0]["predicted_production"]
                    all_line_predictions[individual_line] = prediction_data

            section_totals = defaultdict(float)
            for sections_data in all_line_predictions.values():
                for item in sections_data:
                    section_totals[item["section"]] += item["total_planned_qty"]
            predicted_production = [
                {"section": section, "total_planned_qty": qty}
                for section, qty in section_totals.items()
            ]

        if summation == False:
            non_assembly_zero = any(
                item["section"] != "Assembly" and item["total_planned_qty"] == 0.0
                for item in predicted_production
            )
            if non_assembly_zero:
                for item in predicted_production:
                    if item["section"] == "Assembly":
                        item["total_planned_qty"] = 0.0
                        break

        production_data = [
            {"production_target": production_target, "predicted_production": predicted_production}
        ]
        prediction_response = {"Target data": production_data}

        return success_response(
            message="Data fetched successfully",
            data=prediction_response,
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        logger.info(f"Error in prepare_prediction_data: {str(e)}")
        return error_response(
            error=f"Unknown error: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def get_dday_actual_vs_planned_data(line_no, today, section=None, operation=None, operation_code=None):
    """
    Daily target vs predicted production.
    """
    try:
        def get_data_for_line(line: str) -> dict:
            lp_filter = {"planned_dates": today, "line": line}
            total_planned_qty = (
                LoadingPlan.objects.filter(**lp_filter).aggregate(total_planned_qty=Sum("planned_qty"))
            )["total_planned_qty"] or 0

            style_minimums = (
                DDayData.objects.filter(line=line, allocated_capacity__gt=0)
                .values("style", "code")
                .annotate(total_allocated=Sum("allocated_capacity"))
                .order_by("style", "total_allocated")
            )

            style_min_dict = {}
            for item in style_minimums:
                style = item["style"]
                if style not in style_min_dict:
                    style_min_dict[style] = {"code": item["code"], "min_allocated": item["total_allocated"]}

            predicted_production = sum(item["min_allocated"] for item in style_min_dict.values())
            style_breakdown = [
                {"style": style, "code": data["code"], "style_minimum": data["min_allocated"]}
                for style, data in style_min_dict.items()
            ]

            return {
                "line": line,
                "target_planned_qty": float(total_planned_qty),
                "predicted_production": float(predicted_production),
                "style_breakdown": style_breakdown,
            }

        is_all_lines = str(line_no).lower() == "all"

        if is_all_lines:
            unique_lines = (
                ManningSheetData.objects.filter(planned_dates=today)
                .values_list("line", flat=True)
                .distinct()
            )
            total_target = 0
            total_predicted = 0
            all_lines_data = []
            for line in unique_lines:
                data = get_data_for_line(line)
                total_target += data["target_planned_qty"]
                total_predicted += data["predicted_production"]
                all_lines_data.append(data)

            response_data = {
                "Target data": {
                    "production_target": total_target,
                    "predicted_production": total_predicted,
                    "line_wise_breakdown": all_lines_data,
                }
            }
        else:
            line_data = get_data_for_line(line_no)
            response_data = {
                "Target data": {
                    "line": line_data["line"],
                    "production_target": line_data["target_planned_qty"],
                    "predicted_production": line_data["predicted_production"],
                    "style_breakdown": line_data["style_breakdown"],
                }
            }

        return success_response(
            message="Data fetched successfully",
            data=response_data,
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        logger.info(f"[ERROR] get_dday_actual_vs_planned_data: {str(e)}")
        return error_response(
            error=f"Unknown error: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def get_unallocated_employees_count(line_no):
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


def get_dday_data():
    """Scheduler function: sends dday data via email and push notifications."""
    try:
        logger.info("*******************************************************************")
        logger.info(f"Running DDAY Mailing at {str(datetime.now())} hours!")

        today = datetime.now().date()
        yesterday = today - timedelta(days=1)

        dday_data = fetch_dday_data("All")
        attendance_data = fetch_attendance_data("All", today, yesterday)

        df = pd.DataFrame(dday_data["data"]["records"])
        df.drop(columns=["Dday_ID", "WIP Qty"], inplace=True)

        planned_attendance = attendance_data["data"]["attendance_data"]["Planned Attendance"]
        present = attendance_data["data"]["attendance_data"]["Present"]
        absent = attendance_data["data"]["attendance_data"]["Absent"]

        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, sheet_name="Sheet1", startrow=5, index=False)
            worksheet = writer.sheets["Sheet1"]
            workbook = writer.book
            bold_format = workbook.add_format({"bold": True})

            worksheet.write(0, 0, "Line number", bold_format)
            worksheet.write(0, 1, "All")
            worksheet.write(1, 0, "Planned Attendance", bold_format)
            worksheet.write(1, 1, planned_attendance)
            worksheet.write(2, 0, "Present", bold_format)
            worksheet.write(2, 1, present)
            worksheet.write(3, 0, "Absent", bold_format)
            worksheet.write(3, 1, absent)
            worksheet.set_column(0, 0, 25)
            worksheet.set_column(1, 1, 15)

            for i, col in enumerate(df.columns):
                if col != "Factory":
                    max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2
                    worksheet.set_column(i, i, max_len, workbook.add_format({"text_wrap": False}))

            preferred_col_index = list(df.columns).index("Preferred Employees")
            worksheet.set_column(preferred_col_index, preferred_col_index, 30)
            truncate_format = workbook.add_format({"text_wrap": False, "num_format": "@"})

            for row_num in range(6, 6 + len(df)):
                worksheet.write(row_num, preferred_col_index, df["Preferred Employees"].iloc[row_num - 6], truncate_format)

        output.seek(0)

        userEmails = list(User.objects.filter(send_mail=True, status=True).values_list("email", flat=True))

        import base64
        from apps.absenteeism.tasks import send_email_task

        encoded_excel = base64.b64encode(output.getvalue()).decode()
        send_email_task.delay(
            recipient_emails=userEmails,
            encoded_data=encoded_excel,
            subject="Download D-Day Manning Data File",
            file_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_name="Dday_Manning_data_ALL.xlsx",
            test=True,
        )

        notification_type = get_notification_type_by_time()
        time_display = NOTIFICATION_DISPLAY_TIME.get(notification_type, "Unknown")
        notification_title = NOTIFICATION_DISPLAY_TITLE.get(notification_type, "Unknown")

        with open(
            f"exports/Dday_Manning_data_ALL_{today}_{time_display.replace(' ', '_').replace(':', '_')}.xlsx", "wb"
        ) as f:
            f.write(output.getvalue())

        create_bulk_push_notifications(
            notification_type=notification_type,
            title=notification_title,
            message=f"Kindly review the D-Day prediction data provided for {time_display}",
            users=User.objects.filter(status=True),
            data={"fileName": f"Dday_Manning_data_ALL_{today}_{time_display.replace(' ', '_').replace(':', '_')}.xlsx"},
        )
        logger.info(f"Email successfully sent at {str(datetime.now())} hours!")
        logger.info("***************************************************\n")

    except Exception as e:
        logger.error(f"Error in get_dday_8_45_12_45_5_30 function: {e}")
        return success_response(
            message="An unexpected error occurred in get_dday_8_45_12_45_5_30",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return success_response(message="Success", status=status.HTTP_200_OK)


class DataRetrievalService:
    """Handles business logic for reading/querying manning sheet data."""

    @staticmethod
    def get_manning_data(line_no, section_value, period, style, planned_date, is_export=False):
        """
        Retrieve manning sheet data based on query parameters.
        Returns formatted data dict or an HttpResponse (on export).
        Raises ValueError for bad input, DataRetrievalServiceError for system errors.
        """
        try:
            line_no = line_no.strip().capitalize()
            section_value = section_value.strip().capitalize()
            period = period.strip()
            style = style.strip()
            planned_date = planned_date.strip()

            if not line_no or not section_value or not period:
                raise ValueError('"line", "section" and "forecast_period" are required.')

            if not style:
                style = "all"

            valid_lines = [f"Line {i}" for i in range(1, 11)] + ["All"]
            valid_sections = ["Collar", "Assembly", "Front", "Cuff", "Sleeve", "Back"]
            valid_periods = ["1", "7", "30", "60"]

            if line_no not in valid_lines:
                raise ValueError('Invalid line number. Use "Line X" or "all"')
            if section_value not in valid_sections:
                raise ValueError("Invalid section. Choose from valid options.")
            if period not in valid_periods:
                raise ValueError("Invalid forecast period. Choose from 1, 7, 30, 60.")

            period = int(period)
            today = datetime.today().date()
            date_range = [(today + timedelta(days=i)) for i in range(1, period + 1)]

            manning_sheet_filters = {"section": section_value, "planned_dates__in": date_range}
            manning_general_filters = {"section": section_value, "planned_dates__in": date_range}
            employee_master_filters = {"section": section_value, "designation": "machinist"}
            employees_on_hold_filter = {"section": section_value, "date__in": date_range}

            if line_no.lower() != "all":
                manning_sheet_filters["line"] = line_no
                manning_general_filters["line"] = line_no
                employee_master_filters["line"] = line_no.upper()
                employees_on_hold_filter["line"] = line_no

            if style.lower() != "all":
                manning_sheet_filters["style"] = style.lower()
                manning_general_filters["style"] = style.lower()

            parsed_planned_date = None
            if planned_date:
                try:
                    parsed_planned_date = datetime.strptime(planned_date, "%Y-%m-%d").date()
                    manning_sheet_filters["planned_dates"] = parsed_planned_date
                    manning_general_filters["planned_dates"] = parsed_planned_date
                    employees_on_hold_filter["date"] = parsed_planned_date
                except ValueError:
                    raise ValueError("Invalid date format. Use YYYY-MM-DD.")

            employees_on_hold_queryset = EmployeesOnHold.objects.filter(**employees_on_hold_filter)
            filtered_data_table = ManningSheetData.objects.filter(**manning_sheet_filters).distinct()
            filtered_data_info = ManningGeneralInfo.objects.filter(**manning_general_filters).distinct()

            grouped_result = defaultdict(set)
            grouped_data = filtered_data_table.only("operation", "machine_type", "allocated_emp_name", "allocated_emp_id")
            for row in grouped_data:
                key = (row.machine_type, row.allocated_emp_name or "N/A", row.allocated_emp_id)
                grouped_result[row.operation].add(key)

            machine_type_count = defaultdict(int)
            required_machinists = 0
            for entries in grouped_result.values():
                for machine_type, operator_name, operator_id in entries:
                    machine_type_count[machine_type] += 1
                    required_machinists += 1

            machine_type_count_dict = dict(machine_type_count)
            machine_nonMachine_info = [
                {"machine_type": key, "count": value} for key, value in machine_type_count_dict.items()
            ]

            if not filtered_data_table.exists() and not filtered_data_info.exists():
                return {
                    "table_data": [{"Operation": "N/A", "Machine": "N/A", "Operator Name": "N/A", "SMV": "N/A", "Actual Perf%": "N/A"}],
                    "general_info": {"total_machinist_available": 0, "total_non_machinist_available": 0, "machinist_required": 0, "non_machinist_required": 0, "total_required": 0, "total_available": 0},
                    "machine_nonMachine_info": {},
                    "message": "No data to display",
                }, False

            filtered_data_table = filtered_data_table.order_by("planned_dates", "op_seq").values()

            formatted_data = [
                {
                    "Date": row["planned_dates"].strftime("%d-%m-%Y") if row["planned_dates"] else row["planned_dates"],
                    "Operation": row["operation"],
                    "Style": row["raw_style"],
                    "Buyer": row["buyer"],
                    "Color": row["raw_color"].upper() if row["raw_color"] else row["raw_color"],
                    "OC Number": row["raw_oc_no"].upper() if row["raw_oc_no"] else row["raw_oc_no"],
                    "Order Number": row["order_no"],
                    "Machine Type": row["machine_type"],
                    "Operator Name": row["allocated_emp_name"],
                    "Operator ID": row["allocated_emp_id"],
                    "SAM": row["sam"],
                    "Week": row["week"],
                    "Planned Quantity": row["planned_qty"],
                    "Allocated Capacity": row["allocated_capacity"],
                    "Shortage Reason": row["shortage_reason"],
                    "Manning_ID": row["id"],
                    "Code": row["code"],
                }
                for row in filtered_data_table
            ]

            date_to_preferred_employees = {}
            for obj in employees_on_hold_queryset:
                date_str = obj.date.strftime("%d-%m-%Y")
                date_to_preferred_employees[date_str] = (
                    json.loads(obj.preferred_employees) if obj.preferred_employees else []
                )

            for row in formatted_data:
                date_key = row.get("Date")
                operator_id = row.get("Operator ID")
                operator_name = row.get("Operator Name")
                if row.get("Operator ID") == 0:
                    preferred = date_to_preferred_employees.get(date_key, [])
                    unique_preferred_employees = remove_duplicate_employee_dicts(preferred)
                    preferred_emps = [
                        emp for emp in unique_preferred_employees
                        if not (operator_id in emp and emp[operator_id] == operator_name)
                    ]
                    row["Preferred Employees"] = preferred_emps
                else:
                    row["Preferred Employees"] = []

            actual_machinists = EmployeeMaster.objects.filter(**employee_master_filters).count()
            machine_dict = {entry["machine_type"]: entry["count"] for entry in machine_nonMachine_info}

            unique_buyers = ", ".join(
                set(buyer.upper() for buyer in filtered_data_table.values_list("buyer", flat=True) if buyer)
            )
            info = {"buyers": unique_buyers}
            general_info = {"total_required": required_machinists, "total_available": actual_machinists}

            prediction_response = get_actual_vs_planned_data(
                line_no=line_no,
                forecast_period=period,
                today=today,
                section=section_value,
                planned_date=parsed_planned_date,
            )
            resp = prediction_response.data["data"]
            response_data = {
                "table_data": formatted_data,
                "machinist_nonMachinist_count": general_info,
                "machinist_nonMachinist_info": machine_dict,
                "info": info,
                "message": "Success",
                "Target data": resp["Target data"],
            }

            if style.lower() == "all":
                unique_styles = filtered_data_table.values_list("style", flat=True).distinct()
                response_data["unique_styles"] = list({s.upper() for s in unique_styles if s})

            if is_export:
                sanitized_data = [{k: v for k, v in row.items() if k not in ["Manning_ID", "Code"]} for row in formatted_data]
                response_data["table_data"] = sanitized_data
                excel_data = export_to_excel(response_data, style)
                response = HttpResponse(
                    excel_data.getvalue(),
                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                response["Content-Disposition"] = (
                    f'attachment; filename="{line_no.title()}_ManningSheet__{section_value.title()}_{style}_{period}Days.xlsx"'
                )
                return response, True

            return response_data, False

        except ValueError as e:
            raise e
        except Exception as e:
            raise DataRetrievalServiceError(str(e))

    @staticmethod
    def get_dday_manning_data(line_no):
        """Fetch D-Day manning data with Redis caching."""
        line_no = line_no.strip().capitalize()

        if not line_no:
            raise ValueError('"line" is required.')

        valid_lines = [f"Line {i}" for i in range(1, 11)] + ["All"]
        if line_no not in valid_lines:
            raise ValueError('Enter a valid line number (Valid Formats: "Line 1" or "line 3" or "LINE 5" or "all")')

        cache_key = f"dday_manning_data_{line_no.replace(' ', '_')}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            logger.info(f"CACHE HIT: Returning D-Day data for {line_no} from Redis")
            return cached_data

        logger.info(f"CACHE MISS: Querying the database for D-Day data for {line_no}")
        dday_data = fetch_dday_data(line_no)
        today = datetime.today().date()
        prediction_response = get_dday_actual_vs_planned_data(line_no=line_no, today=today)
        dday_data["data"]["prediction_data"] = prediction_response.data["data"]
        unallocated_emp_data = get_unallocated_employees_count(line_no=line_no)
        dday_data["data"]["unallocated_emp_data"] = unallocated_emp_data

        cache.set(cache_key, dday_data, timeout=43200)
        return dday_data

    @staticmethod
    def get_attendance_data(line_no):
        """Retrieve attendance data for a given line."""
        line_no = line_no.strip().title()
        if not line_no:
            raise ValueError('"line" is required.')
        if line_no not in {f"Line {i}" for i in range(1, 11)} | {"All"}:
            raise ValueError('Enter a valid line number (Valid Formats: "Line 1" or "line 3" or "LINE 5" or "all")')

        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        return fetch_attendance_data(line_no, today, yesterday)

    @staticmethod
    def get_unallocated_employees(line_no, forecast_period, is_export=False):
        """Get unallocated employees for a manning forecast period."""
        line_no = line_no.strip()
        if not line_no or not forecast_period:
            raise ValueError('"line" and "forecast_period" are required.')

        try:
            forecast_period = int(forecast_period)
        except ValueError:
            raise ValueError('"forecast_period" must be an integer.')

        today = datetime.today().date()
        date_range = [(today + timedelta(days=i)) for i in range(1, forecast_period + 1)]
        query_filter = {"line": line_no.capitalize(), "date__in": date_range}
        queryset = UnallocatedEmployees.objects.filter(**query_filter)

        if is_export:
            df_unallocated_employees = pd.DataFrame(list(queryset.values()))
            df_unallocated_employees["period"] = forecast_period
            df_unallocated_employees.drop(columns={"id"}, inplace=True)
            df_unallocated_employees.columns = (
                df_unallocated_employees.columns.str.replace("_", " ").str.upper()
            )
            for col in df_unallocated_employees.select_dtypes(include=["datetimetz"]).columns:
                df_unallocated_employees[col] = df_unallocated_employees[col].dt.tz_localize(None)

            output = BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df_unallocated_employees.to_excel(writer, index=False, sheet_name="Unallocated Employees")
                worksheet = writer.sheets["Unallocated Employees"]
                for i, col in enumerate(df_unallocated_employees.columns):
                    max_len = max(df_unallocated_employees[col].astype(str).map(len).max(), len(col)) + 2
                    worksheet.set_column(i, i, max_len)

            output.seek(0)
            response = HttpResponse(output.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            response["Content-Disposition"] = "attachment; filename=unallocated_employees.xlsx"
            return response, True

        return list(queryset.values()), False

    @staticmethod
    def get_unallocated_employees_dday(line_no, is_export=False):
        """Get D-Day unallocated employees from CSV report."""
        line_no = line_no.strip()
        file_path = "exports/unallocated_report_dday.csv"

        if not os.path.exists(file_path):
            raise LookupError("D-Day unallocated report has not been generated yet. Please run D-Day generation first.")

        df_unallocated_employees = pd.read_csv(file_path)
        df_unallocated_employees = df_unallocated_employees[
            (df_unallocated_employees["reason"] != "Employee Absent")
            & (df_unallocated_employees["type"] == "Primary")
        ]

        file_name = "Unallocated_Employees_DDay"
        if line_no.lower() != "all":
            df_unallocated_employees = df_unallocated_employees[
                df_unallocated_employees["line"] == line_no.title()
            ]
            file_name = f"Unallocated_Employees_DDay_{line_no.replace(' ', '_').title()}"

        if is_export:
            df_unallocated_employees.columns = (
                df_unallocated_employees.columns.str.replace("_", " ").str.upper()
            )
            for col in df_unallocated_employees.select_dtypes(include=["datetimetz"]).columns:
                df_unallocated_employees[col] = df_unallocated_employees[col].dt.tz_localize(None)

            output = BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df_unallocated_employees.to_excel(writer, index=False, sheet_name="Unallocated Employees")
                worksheet = writer.sheets["Unallocated Employees"]
                for i, col in enumerate(df_unallocated_employees.columns):
                    max_len = max(df_unallocated_employees[col].astype(str).map(len).max(), len(col)) + 2
                    worksheet.set_column(i, i, max_len)

            output.seek(0)
            response = HttpResponse(output.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            response["Content-Disposition"] = f"attachment; filename={file_name}.xlsx"
            return response, True

        return df_unallocated_employees.to_dict("records"), False


# --- Backward Compatibility Wrappers ---
def run_get_manning_data(line_no, section_value, period, style, planned_date, is_export=False):
    try:
        result, exported = DataRetrievalService.get_manning_data(line_no, section_value, period, style, planned_date, is_export)
        if exported:
            return result
        if isinstance(result, dict) and result.get("message") == "No data to display":
            return success_response(message="No data to display", data=result, status=status.HTTP_200_OK)
        return success_response(message="Success", data=result, status=status.HTTP_200_OK)
    except ValueError as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
    except DataRetrievalServiceError as e:
        return success_response(message=f"Error: {str(e)}", data=None, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def run_get_dday_manning_data(line_no):
    try:
        dday_data = DataRetrievalService.get_dday_manning_data(line_no)
        return success_response(data=dday_data["data"], message=dday_data["message"], status=dday_data["status"])
    except ValueError as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return error_response(error=f"An unexpected error occurred: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def run_get_attendance_data(line_no):
    try:
        attendance_data = DataRetrievalService.get_attendance_data(line_no)
        return success_response(data=attendance_data["data"], message=attendance_data["message"], status=attendance_data["status"])
    except ValueError as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
    except Exception:
        return error_response(error="An unexpected error occurred. Please try again later.", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def run_get_unallocated_employees(line_no, forecast_period, is_export=False):
    try:
        result, exported = DataRetrievalService.get_unallocated_employees(line_no, forecast_period, is_export)
        if exported:
            return result
        return success_response(data=result, message="Success", status=status.HTTP_200_OK)
    except ValueError as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)


def run_get_unallocated_employees_dday(line_no, is_export=False):
    try:
        result, exported = DataRetrievalService.get_unallocated_employees_dday(line_no, is_export)
        if exported:
            return result
        return success_response(data=result, message="Success", status=status.HTTP_200_OK)
    except LookupError as e:
        return error_response(error=str(e), status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
