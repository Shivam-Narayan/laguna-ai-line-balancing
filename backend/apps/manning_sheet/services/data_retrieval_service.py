import os
import gzip
import pytz
import json
import logging
import requests
import numpy as np
import pandas as pd
import xml.etree.ElementTree as ET

from django.utils import timezone
from django.db import transaction
from collections import defaultdict
from django.utils.encoding import smart_bytes
from django.shortcuts import get_object_or_404
from django.http import HttpResponse, FileResponse
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError, DatabaseError
from django.db.models import Func, FloatField, Count, Sum, Case, When, Q

from io import BytesIO
from rest_framework import status
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, date, time
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes, authentication_classes

from apps.accounts.authentication import CookieJWTAuthentication
from apps.accounts.utils.response_handlers import error_response, success_response

from config.utils import truncate_table
from ..loading_plan_optimization import process_df
from ..loading_plan import redistribute_production_plan
from apps.absenteeism.utils import send_email, is_allowed_working_day, convert_number
from ..manning_generation_multiprocessing import run_manning_allocation, filter_by_date_ranges, process_grouped_results, map_factory_floor_for_results, create_manning_dataframes, process_general_info, map_factory_floor
from ..dday_generation import get_ist_time, run_intraday_allocation_enhanced, generate_reallocation_report, analyze_unallocated_patterns, print_unallocated_summary, generate_unallocated_report_safe, analyze_allocation_gaps, perform_final_allocation_pass
from ..utils import fetch_skill_matrix, fetch_operations, merge_dataframe, export_to_excel, export_json_to_excel, fetch_style_ob, merge_machine_sam, process_styles, renaming_columns_style_ob, fetch_wip, custom_round, create_bulk_push_notifications, get_notification_type_by_time, fetch_dday_data, fetch_attendance_data, remove_by_employee_id, transform_unallocated_to_on_hold_from_dict, update_sections, remove_duplicate_employee_dicts, fetchMaxQtyDday

from ..models import PushNotification
from apps.accounts.models import EndpointLock, User
from apps.absenteeism.models import PredictionData, AbsenteeismPrediction
from apps.data_engine.models import AttendanceMaster, EmployeeMaster, LocalHolidayCalendar, PayableWorkingDays
from ..models import StyleOB, LoadingPlan, EMPFact, ManningSheetData, DDayData, ManningGeneralInfo, WIPData, ActiveEmployees, UnallocatedEmployees, EmployeesOnHold

logger = logging.getLogger('general')

CHUNK_SIZE = 1000

os.makedirs("exports", exist_ok=True)
COMPANY_CODE = 843

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

class Round(Func):
    function = 'ROUND'
    arity = 2
    output_field = FloatField()

def run_get_manning_data(line_no, section_value, period, style, planned_date, is_export=False):
    """
    Retrieve manning sheet data based on query parameters.
    """
    try:
        line_no = line_no.strip().capitalize()
        section_value = section_value.strip().capitalize()
        period = period.strip()
        style = style.strip()
        planned_date = planned_date.strip()

        # Validate required fields
        if not line_no or not section_value or not period:
            return error_response(error='"line", "section" and "forecast_period" are required.', status=status.HTTP_400_BAD_REQUEST)

        if not style:
            style = "all"

        valid_lines = [f'Line {i}' for i in range(1, 11)] + ['All']
        valid_sections = ['Collar', 'Assembly', 'Front', 'Cuff', 'Sleeve', 'Back']
        valid_periods = ['1', '7', '30', '60']
        
        if line_no not in valid_lines:
            return error_response(error='Invalid line number. Use "Line X" or "all"', status=status.HTTP_400_BAD_REQUEST)
        if section_value not in valid_sections:
            return error_response(error='Invalid section. Choose from valid options.', status=status.HTTP_400_BAD_REQUEST)
        if period not in valid_periods:
            return error_response(error='Invalid forecast period. Choose from 1, 7, 30, 60.', status=status.HTTP_400_BAD_REQUEST)
        
        period = int(period)  # Convert forecast_period to integer

        today = datetime.today().date()
        date_range = [(today + timedelta(days=i)) for i in range(1, period + 1)] # This list won't include today's date

        # Apply filters dynamically based on conditions
        manning_sheet_filters = {'section': section_value, 'planned_dates__in': date_range}
        manning_general_filters = {'section': section_value, 'planned_dates__in': date_range}
        employee_master_filters = {'section': section_value, 'designation': 'machinist'}
        employees_on_hold_filter = {'section': section_value, 'date__in': date_range}

        if line_no.lower() != 'all':
            manning_sheet_filters['line'] = line_no
            manning_general_filters['line'] = line_no
            employee_master_filters['line'] = line_no.upper()
            employees_on_hold_filter['line'] = line_no

        if style.lower() != 'all':
            manning_sheet_filters['style'] = style.lower()
            manning_general_filters['style'] = style.lower()
        
        if planned_date:
            try:
                planned_date = datetime.strptime(planned_date, '%Y-%m-%d').date()
                manning_sheet_filters['planned_dates'] = planned_date
                manning_general_filters['planned_dates'] = planned_date
                employees_on_hold_filter['date'] = planned_date
            except ValueError:
                return error_response(error='Invalid date format. Use YYYY-MM-DD.', status=status.HTTP_400_BAD_REQUEST)

        employees_on_hold_queryset = EmployeesOnHold.objects.filter(**employees_on_hold_filter)
        
        # Query filtered data
        filtered_data_table = ManningSheetData.objects.filter(**manning_sheet_filters).distinct()
        filtered_data_info = ManningGeneralInfo.objects.filter(**manning_general_filters).distinct()

        # Step 1: Group data by operation with unique (machine_type, operator_name, operator_id)
        grouped_result = defaultdict(set)

        grouped_data = filtered_data_table.only(
            'operation', 'machine_type', 'allocated_emp_name', 'allocated_emp_id'
        )

        for row in grouped_data:
            key = (row.machine_type, row.allocated_emp_name or "N/A", row.allocated_emp_id)
            grouped_result[row.operation].add(key)

        # Step 2: Flatten grouped data and count machine_type occurrences & operator counts
        machine_type_count = defaultdict(int)
        required_machinists = 0

        for entries in grouped_result.values():
            for machine_type, operator_name, operator_id in entries:
                machine_type_count[machine_type] += 1
                required_machinists += 1

        # Convert defaultdicts to normal dicts if needed
        machine_type_count_dict = dict(machine_type_count)

        machine_nonMachine_info = [
            {'machine_type': key, 'count': value}
            for key, value in machine_type_count_dict.items()
        ]
        
        if not filtered_data_table.exists() and not filtered_data_info.exists():
            return success_response(message='No data to display', data={
                'table_data': [{
                    'Operation': 'N/A', 'Machine': 'N/A', 'Operator Name': 'N/A', 'SMV': 'N/A', 'Actual Perf%': 'N/A'
                }],
                'general_info': {
                    'total_machinist_available': 0,
                    'total_non_machinist_available': 0,
                    'machinist_required': 0,
                    'non_machinist_required': 0,
                    'total_required': 0,
                    'total_available': 0
                },
                'machine_nonMachine_info': {},
                'message': 'No data to display'
            }, status=status.HTTP_200_OK)

        filtered_data_table = (
            filtered_data_table
            .order_by('planned_dates', 'op_seq')  # Order first by section, then within each section
            .values()
        )

        formatted_data = [
            {   
                'Date': row['planned_dates'].strftime('%d-%m-%Y') if row['planned_dates'] else row['planned_dates'],
                'Operation': row['operation'],
                'Style': row['raw_style'],
                'Buyer': row['buyer'],
                'Color': row['raw_color'].upper() if row['raw_color'] else row['raw_color'],
                'OC Number': row['raw_oc_no'].upper() if row['raw_oc_no'] else row['raw_oc_no'],
                'Order Number': row['order_no'],
                'Machine Type': row['machine_type'],
                'Operator Name': row['allocated_emp_name'],
                'Operator ID': row['allocated_emp_id'],
                'SAM': row['sam'],
                'Week': row['week'],
                'Planned Quantity': row['planned_qty'],
                'Allocated Capacity': row['allocated_capacity'],
                'Shortage Reason': row['shortage_reason'],
                'Manning_ID': row['id'],
                'Code': row['code']
            }
            for row in filtered_data_table
        ]

        # Create a dict mapping date strings in '%d-%m-%Y' format to preferred_employees JSON string
        date_to_preferred_employees = {}

        for obj in employees_on_hold_queryset:
            date_str = obj.date.strftime('%d-%m-%Y')
            date_to_preferred_employees[date_str] = json.loads(obj.preferred_employees) if obj.preferred_employees else []


        for row in formatted_data:
            date_key = row.get('Date')
            operator_id = row.get('Operator ID')
            operator_name = row.get('Operator Name')
            if row.get('Operator ID') == 0:
                preferred = date_to_preferred_employees.get(date_key, [])
                unique_preferred_employees = remove_duplicate_employee_dicts(preferred)
                preferred_emps = [
                    emp for emp in unique_preferred_employees
                    if not (operator_id in emp and emp[operator_id] == operator_name)
                ]
                row['Preferred Employees'] = preferred_emps
            else:
                row['Preferred Employees'] = []

        actual_machinists = EmployeeMaster.objects.filter(**employee_master_filters).count()
        machine_dict = {entry['machine_type']: entry['count'] for entry in machine_nonMachine_info}

        unique_buyers = ', '.join(set(buyer.upper() for buyer in filtered_data_table.values_list('buyer', flat=True) if buyer))
        info = {'buyers': unique_buyers}
        general_info = {'total_required': required_machinists, 'total_available': actual_machinists}

        prediction_response = get_actual_vs_planned_data(line_no=line_no, forecast_period=period, today=today, section=section_value, planned_date=planned_date)
        resp = prediction_response.data['data']
        response_data = {
            'table_data': formatted_data,
            'machinist_nonMachinist_count': general_info,
            'machinist_nonMachinist_info': machine_dict,
            'info': info,
            'message': 'Success',
            'Target data': resp['Target data']
        }

        # Add unique styles if style == 'all'
        if style.lower() == 'all':
            unique_styles = filtered_data_table.values_list('style', flat=True).distinct()
            response_data['unique_styles'] = list({s.upper() for s in unique_styles if s})
        
        if is_export:
            # Create a new list with 'Manning_ID' and 'Code' removed
            sanitized_data = [
                {k: v for k, v in row.items() if k not in ['Manning_ID', 'Code']}
                for row in formatted_data
            ]
            # Replace in response_data
            response_data['table_data'] = sanitized_data

            excel_data = export_to_excel(response_data, style)
            response = HttpResponse(
                excel_data.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            response["Content-Disposition"] = f'attachment; filename="{line_no.title()}_ManningSheet__{section_value.title()}_{style}_{period}Days.xlsx"'
            return response

        return success_response(message='Success', data=response_data, status=status.HTTP_200_OK)
    except Exception as e:
        return success_response(message=f"Error: {str(e)}", data=None, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def get_actual_vs_planned_data(line_no, forecast_period, today, summation=False, section=None, dday=None, planned_date=None):
    try:
        filter_date = today if dday else today + timedelta(days=forecast_period)
        filter_date = planned_date if planned_date else filter_date

        manning_sheet_filter = {'planned_dates': filter_date, 'machinist': True}
        loading_plan_filter = {'planned_dates': filter_date}
        employee_filter={}

        if line_no.lower() != 'all':
            employee_filter['line']=line_no.upper()
    
        if section is not None:
            sections = [section]
            employee_filter['section'] = section
            manning_sheet_filter['section']=section
        else:
            sections = ['Assembly', 'Cuff', 'Front', 'Back', 'Sleeve', 'Collar']

        total_emp_count = EmployeeMaster.objects.filter(**employee_filter).count()
        if total_emp_count == 0:
            return None, None, error_response(error='No employees found.', status=status.HTTP_404_NOT_FOUND)

        if line_no.lower() != 'all':
            loading_plan_filter['line'] = line_no.title()
            manning_sheet_filter['line'] = line_no.title()

        manning_sheet_qs = ManningSheetData.objects.filter(**manning_sheet_filter)
        manning_sheet_target = (
            manning_sheet_qs
            .values('section', 'code', 'style')
            .annotate(total_planned_qty=Sum('allocated_capacity'))
        )

        min_entries = {}

        for item in manning_sheet_target:
            key = (item['section'], item['style'])  # tuple as key
            qty = item['total_planned_qty']
            
            if key not in min_entries or qty < min_entries[key]['total_planned_qty']:
                min_entries[key] = item  # Keep only one item with min qty

        # Convert result to list
        min_entries_list = list(min_entries.values())

        # Aggregate total_planned_qty per section
        section_summary = defaultdict(float)

        for item in min_entries_list:
            section_summary[item['section']] += item['total_planned_qty']

        # Convert to list of dicts if needed
        result = [{'section': sec, 'total_planned_qty': qty} for sec, qty in section_summary.items()]

        total_planned_qty = (
            LoadingPlan.objects
            .filter(**loading_plan_filter)
            .aggregate(total_planned_qty=Sum('planned_qty'))
        )['total_planned_qty'] or 0

        production_target = [
            {'section': section, 'total_planned_qty': round(total_planned_qty, 2)}
            for section in sections
        ]

        predicted_production = update_sections(result, sections)

        # Special handling for "all" lines case
        if line_no.lower() == "all":
            # First calculate individual line predictions
            all_line_predictions = {}
            for line_index in range(1, 11):
                individual_line = f"line {line_index}"
                # Call recursively but don't return, just store results
                response_data = get_actual_vs_planned_data(line_no=individual_line, forecast_period=forecast_period, today=today, summation=True, section=section, dday=dday)
                response_data = response_data.data
                
                # If the response is valid, extract the prediction data
                if isinstance(response_data, tuple):
                    continue  # Skip invalid responses
                
                if 'data' in response_data and 'Target data' in response_data['data']:
                    prediction_data = response_data['data']['Target data'][0]['predicted_production']
                    # Store by line number for aggregation
                    all_line_predictions[individual_line] = prediction_data

            # 1. Accumulate totals per section
            section_totals = defaultdict(float)

            for sections in all_line_predictions.values():
                for item in sections:
                    section_totals[item["section"]] += item["total_planned_qty"]

            # 2. Convert to desired list-of-dict format
            predicted_production = [{"section": section, "total_planned_qty": qty} for section, qty in section_totals.items()]

        if summation==False:
            # First, find if any non-Assembly section has zero quantity
            non_assembly_zero = any(
                item['section'] != 'Assembly' and item['total_planned_qty'] == 0.0
                for item in predicted_production
            )
            # If condition met, directly update Assembly section in same loop
            if non_assembly_zero:
                for item in predicted_production:
                    if item['section'] == 'Assembly':
                        item['total_planned_qty'] = 0.0
                        break

        production_data = [{
            "production_target": production_target,
            "predicted_production": predicted_production,
        }]

        prediction_response = {
            'Target data': production_data
        }

        return success_response(message='Data fetched successfully', data=prediction_response, status=status.HTTP_200_OK)

    except Exception as e:
        logger.info(f"Error in prepare_prediction_data: {str(e)}")
        return error_response(error=f"Unknown error: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def get_dday_data():
    try:
        logger.info(f"*******************************************************************")
        logger.info(f"Running DDAY Mailing at {str(datetime.now())} hours!")

        # Calculate dates
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)

        dday_data = fetch_dday_data('All')
        attendance_data = fetch_attendance_data('All', today, yesterday)

        df = pd.DataFrame(dday_data["data"]["records"])
        df.drop(columns=['Dday_ID', 'WIP Qty'], inplace=True)

        planned_attendance = attendance_data['data']['attendance_data']['Planned Attendance']
        present = attendance_data['data']['attendance_data']['Present']
        absent = attendance_data['data']['attendance_data']['Absent']

        # Generate Excel file in memory
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name="Sheet1", startrow=5, index=False)

            # Get the worksheet AFTER writing the DataFrame
            worksheet = writer.sheets["Sheet1"]
            workbook = writer.book
            bold_format = workbook.add_format({'bold': True})  # Bold format for headers

            # Write attendance data at the top with proper alignment
            worksheet.write(0, 0, "Line number", bold_format)
            worksheet.write(0, 1, "All")

            worksheet.write(1, 0, "Planned Attendance", bold_format)
            worksheet.write(1, 1, planned_attendance)

            worksheet.write(2, 0, "Present", bold_format)
            worksheet.write(2, 1, present)

            worksheet.write(3, 0, "Absent", bold_format)
            worksheet.write(3, 1, absent)

            # Adjust column width for A and B (0 and 1)
            worksheet.set_column(0, 0, 25)  # Column A (Labels)
            worksheet.set_column(1, 1, 15)  # Column B (Values)

            # Adjust column widths dynamically based on data
            for i, col in enumerate(df.columns):
                if col != 'Factory':
                    max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2  # Adjust width
                    worksheet.set_column(i, i, max_len, workbook.add_format({'text_wrap': False}))  # Disable text wrapping

            # Handle "Preferred Employees" column formatting
            preferred_col_index = list(df.columns).index("Preferred Employees")
            worksheet.set_column(preferred_col_index, preferred_col_index, 30)  # Fixed width

            # Create a custom format to prevent text overflow in "Preferred Employees"
            truncate_format = workbook.add_format({
                'text_wrap': False,
                'num_format': '@'  # Text format
            })

            # Apply format to all rows in "Preferred Employees" column
            for row_num in range(6, 6 + len(df)):  # Data starts from row 6
                worksheet.write(row_num, preferred_col_index, df["Preferred Employees"].iloc[row_num - 6], truncate_format)

        output.seek(0)

        userEmails = list(User.objects.filter(send_mail=True, status=True).values_list('email', flat=True))

        subject = "Download D-Day Manning Data File"
        file_name = "Dday_Manning_data_ALL.xlsx"
        file_data = output  # Pass the BytesIO object directly
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        # Call the send_email_task function
        import base64
        from apps.absenteeism.tasks import send_email_task
        encoded_excel = base64.b64encode(file_data.getvalue()).decode()
        
        send_email_task.delay(
            recipient_emails=userEmails,
            encoded_data=encoded_excel,
            subject=subject,
            file_type=content_type,
            file_name=file_name,
            test=True
        )
        # Send push notifications to all users regardless of status
        notification_type = get_notification_type_by_time()
        time_display = NOTIFICATION_DISPLAY_TIME.get(notification_type, "Unknown")
        notification_title = NOTIFICATION_DISPLAY_TITLE.get(notification_type, "Unknown")

        with open(f"exports/Dday_Manning_data_ALL_{today}_{time_display.replace(' ', '_').replace(':', '_')}.xlsx", "wb") as f:
            f.write(output.getvalue())

        create_bulk_push_notifications(
            notification_type=notification_type,
            title=notification_title,
            message=f"Kindly review the D-Day prediction data provided for {time_display}",
            users=User.objects.filter(status=True),  # only active users
            data={"fileName": f"Dday_Manning_data_ALL_{today}_{time_display.replace(' ', '_').replace(':', '_')}.xlsx"}
        )
        logger.info(f"Email successfully sent at {str(datetime.now())} hours!")
        logger.info(f"***************************************************\n")

    except Exception as e:
        logger.error(f"Error in get_dday_8_45_12_45_5_30 function: {e}")
        return success_response(message="An unexpected error occurred in get_dday_8_45_12_45_5_30", status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return success_response(message="Success", status=status.HTTP_200_OK)


def run_get_dday_manning_data(line_no):
    try:
        # Get line parameter from either GET or POST
        line_no = line_no.strip().capitalize()

        if not line_no:
            return error_response(error='"line" is required.', status=status.HTTP_400_BAD_REQUEST)
        
        # Define valid line options
        valid_lines = [f'Line {i}' for i in range(1, 11)] + ['All']

        if line_no not in valid_lines:
            return error_response(error='Enter a valid line number (Valid Formats: "Line 1" or "line 3" or "LINE 5" or "all")', 
                                  status=status.HTTP_400_BAD_REQUEST)

        dday_data = fetch_dday_data(line_no)
        today = datetime.today().date()
        prediction_response = get_dday_actual_vs_planned_data(line_no=line_no, today=today)
        dday_data["data"]["prediction_data"] = prediction_response.data['data']
        unallocated_emp_data = get_unallocated_employees_count(line_no=line_no)
        dday_data["data"]["unallocated_emp_data"] = unallocated_emp_data

        return success_response(
            data=dday_data["data"], 
            message=dday_data["message"], 
            status=dday_data["status"]
        )
    except Exception as e:
        return error_response(error=f"An unexpected error occurred: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def get_unallocated_employees_count(line_no):
    file_path = 'exports/unallocated_report_dday.csv'

    if not os.path.exists(file_path):
        return 0
    try:
        df = pd.read_csv(file_path, usecols=['line', 'reason', 'type'])
        
        # Apply the same filtering as in the export function
        df = df[(df['reason'] != 'Employee Absent') & (df['type'] == 'Primary')]

        if line_no.lower() != 'all':
            return (df['line'] == line_no.title()).sum()
        else:
            return len(df)
    except Exception as e:
        logger.info(f"Error reading unallocated report: {e}")
        return 0  # In case of read/parsing error


def get_dday_actual_vs_planned_data(line_no, today, section=None, operation=None, operation_code=None):
    """
    Daily target vs predicted production.
 
    - target_planned_qty = SUM(planned_qty) for the line & date
    - predicted_production = SUM of minimum allocated capacity per style
    """
    try:
        def get_data_for_line(line: str) -> dict:
            """Fetch target and predicted data for a single line."""
 
            # --- 1. Target planned qty ---
            lp_filter = {'planned_dates': today, 'line': line}
            total_planned_qty = (
                LoadingPlan.objects
                .filter(**lp_filter)
                .aggregate(total_planned_qty=Sum('planned_qty'))
            )['total_planned_qty'] or 0
 
            # --- 2. Predicted production - NEW LOGIC ---
            # Get minimum allocated capacity per style along with operation code
            style_minimums = (
                DDayData.objects
                .filter(line=line, allocated_capacity__gt=0)
                .values('style', 'code')  # Group by style and code
                .annotate(total_allocated=Sum('allocated_capacity'))
                .order_by('style', 'total_allocated')
            )
           
            # For each style, get the minimum allocated capacity (first record after ordering)
            style_min_dict = {}
            for item in style_minimums:
                style = item['style']
                # Only keep the minimum for each style (first occurrence due to ordering)
                if style not in style_min_dict:
                    style_min_dict[style] = {
                        'code': item['code'],
                        'min_allocated': item['total_allocated']
                    }
           
            # Sum all the style minimums to get total predicted production
            predicted_production = sum(item['min_allocated'] for item in style_min_dict.values())
           
            # Prepare style-wise breakdown for debugging/information
            style_breakdown = [
                {
                    'style': style,
                    'code': data['code'],
                    'style_minimum': data['min_allocated']
                }
                for style, data in style_min_dict.items()
            ]
 
            return {
                'line': line,
                'target_planned_qty': float(total_planned_qty),
                'predicted_production': float(predicted_production),
                'style_breakdown': style_breakdown  # Optional: include breakdown in response
            }
 
        is_all_lines = str(line_no).lower() == 'all'
 
        if is_all_lines:
            # --- Collect all lines ---
            unique_lines = (
                ManningSheetData.objects
                .filter(planned_dates=today)
                .values_list('line', flat=True)
                .distinct()
            )
 
            # Calculate totals across all lines
            total_target = 0
            total_predicted = 0
            all_lines_data = []
 
            for line in unique_lines:
                data = get_data_for_line(line)
                total_target += data['target_planned_qty']
                total_predicted += data['predicted_production']
                all_lines_data.append(data)
 
            response_data = {
               "Target data": {
                    "production_target": total_target,
                    "predicted_production": total_predicted,
                    "line_wise_breakdown": all_lines_data  # Optional: include detailed breakdown
                }
            }
 
        else:
            # --- Just this line ---
            line_data = get_data_for_line(line_no)
            response_data = {
                "Target data": {
                    "line": line_data['line'],
                    "production_target": line_data['target_planned_qty'],
                    "predicted_production": line_data['predicted_production'],
                    "style_breakdown": line_data['style_breakdown']  # Include style breakdown
                }
            }
 
        return success_response(
            message="Data fetched successfully",
            data=response_data,
            status=status.HTTP_200_OK
        )
 
    except Exception as e:
        logger.info(f"[ERROR] get_dday_actual_vs_planned_data: {str(e)}")
        return error_response(
            error=f"Unknown error: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def run_get_attendance_data(line_no):
    """
    Retrieve simplified attendance statistics using conditional aggregation
    to match output exactly with the complex logic but using single DB hit
    """
    try:
        # Get and validate line parameter
        line_no = line_no.strip().title()
        
        if not line_no:
            return error_response(error='"line" is required.', status=status.HTTP_400_BAD_REQUEST)
        
        # Fast validation with set lookup
        if line_no not in {f'Line {i}' for i in range(1, 11)} | {'All'}:
            return error_response(
                error='Enter a valid line number (Valid Formats: "Line 1" or "line 3" or "LINE 5" or "all")',
                status=status.HTTP_400_BAD_REQUEST
            )

        # Calculate dates
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)

        attendance_data = fetch_attendance_data(line_no, today, yesterday)

        return success_response(
            data=attendance_data["data"], 
            message=attendance_data["message"], 
            status=attendance_data["status"]
        )

    except Exception as e:
        return error_response(
            error="An unexpected error occurred. Please try again later.",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def run_get_unallocated_employees(line_no, forecast_period, is_export=False):
    try:
        line_no = line_no.strip()
        
        if not line_no or not forecast_period:
            return error_response(error='"line" and "forecast_period" are required.', status=status.HTTP_400_BAD_REQUEST)

        try:
            forecast_period = int(forecast_period)
        except ValueError:
            return error_response(error='"forecast_period" must be an integer.', status=status.HTTP_400_BAD_REQUEST)

        today = datetime.today().date()
        date_range = [(today + timedelta(days=i)) for i in range(1, forecast_period + 1)] # This list won't include today's date

        query_filter = {
            'line': line_no.capitalize(),
            'date__in': date_range  
        }
        queryset = UnallocatedEmployees.objects.filter(**query_filter)

        if is_export:
            df_unallocated_employees = pd.DataFrame(list(queryset.values()))
            df_unallocated_employees['period'] = forecast_period
            df_unallocated_employees.drop(columns={'id'}, inplace=True)
            df_unallocated_employees.columns = df_unallocated_employees.columns.str.replace('_', ' ').str.upper()
            # Convert timezone-aware datetimes to timezone-naive
            for col in df_unallocated_employees.select_dtypes(include=['datetimetz']).columns:
                df_unallocated_employees[col] = df_unallocated_employees[col].dt.tz_localize(None)
            # Generate Excel file in memory
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_unallocated_employees.to_excel(writer, index=False, sheet_name='Unallocated Employees')

                # Get the workbook and worksheet objects
                worksheet = writer.sheets['Unallocated Employees']

                # Auto-adjust column widths
                for i, col in enumerate(df_unallocated_employees.columns):
                    # Get max length of values in column (including column name)
                    max_len = max(
                        df_unallocated_employees[col].astype(str).map(len).max(),
                        len(col)
                    ) + 2  # Add padding
                    worksheet.set_column(i, i, max_len)

            output.seek(0)
            response = HttpResponse(output.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = 'attachment; filename=unallocated_employees.xlsx'
            return response
    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)


def run_get_unallocated_employees_dday(line_no, is_export=False):
    try:
        import os
        line_no = line_no.strip()
        
        file_path = 'exports/unallocated_report_dday.csv'
        if not os.path.exists(file_path):
            return error_response(error="D-Day unallocated report has not been generated yet. Please run D-Day generation first.", status=status.HTTP_404_NOT_FOUND)
            
        df_unallocated_employees = pd.read_csv(file_path)
        df_unallocated_employees = df_unallocated_employees[(df_unallocated_employees['reason'] != 'Employee Absent') & (df_unallocated_employees['type'] == 'Primary')]

        file_name = f"Unallocated_Employees_DDay"

        if line_no.lower() != 'all':
            df_unallocated_employees = df_unallocated_employees[df_unallocated_employees['line'] == line_no.title()]
            file_name =  f"Unallocated_Employees_DDay_{line_no.replace(' ', '_').title()}"

        if is_export:
            df_unallocated_employees.columns = df_unallocated_employees.columns.str.replace('_', ' ').str.upper()
            # Convert timezone-aware datetimes to timezone-naive
            for col in df_unallocated_employees.select_dtypes(include=['datetimetz']).columns:
                df_unallocated_employees[col] = df_unallocated_employees[col].dt.tz_localize(None)
            # Generate Excel file in memory
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_unallocated_employees.to_excel(writer, index=False, sheet_name='Unallocated Employees')

                # Get the workbook and worksheet objects
                # workbook  = writer.book
                worksheet = writer.sheets['Unallocated Employees']

                # Auto-adjust column widths
                for i, col in enumerate(df_unallocated_employees.columns):
                    # Get max length of values in column (including column name)
                    max_len = max(
                        df_unallocated_employees[col].astype(str).map(len).max(),
                        len(col)
                    ) + 2  # Add padding
                    worksheet.set_column(i, i, max_len)

            output.seek(0)
            response = HttpResponse(output.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = f"attachment; filename={file_name}.xlsx"
            return response
    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
