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

from apps.accounts.authentication import MultiSessionTokenAuthentication
from apps.accounts.utils.response_handlers import error_response, success_response

from backend_laguna.utils import truncate_table
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

@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def download_manning_data_by_section(request):
    line_no = request.query_params.get('line', ' ').strip()
    period = request.query_params.get('forecast_period', ' ').strip()
    
    line_no = line_no.capitalize()
    
    try:
        # Validate required fields
        if not line_no or not period:
            return error_response(error='"line" and "forecast_period" are required.', status=status.HTTP_400_BAD_REQUEST)

        valid_lines = [f'Line {i}' for i in range(1, 11)] + ['All']
        valid_periods = ['1', '7', '30', '60']

        if line_no not in valid_lines:
            return error_response(error='Invalid line number. Use "Line X" or "all"', status=status.HTTP_400_BAD_REQUEST)
        if period not in valid_periods:
            return error_response(error='Invalid forecast period. Choose from 1, 7, 30, 60.', status=status.HTTP_400_BAD_REQUEST)

        period = int(period)  # Convert forecast_period to integer

        # nextDay = today + timedelta(days=1)
        today = datetime.today().date()
        date_range = [(today + timedelta(days=i)) for i in range(1, period + 1)] # This list won't include today's date

        # Apply filters dynamically based on conditions
        filters = {'planned_dates__in': date_range}
        employee_master_filters = {'designation': 'machinist'}

        if line_no.lower() != 'all':
            filters['line'] = line_no
            employee_master_filters['line'] = line_no.upper()

        # Query filtered data
        filtered_data_table = ManningSheetData.objects.filter(**filters).distinct()
        filtered_data_info = ManningGeneralInfo.objects.filter(**filters).distinct()

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

        table_data_query = (
            filtered_data_table
            .order_by('planned_dates', 'op_seq')  # Order first by section, then within each section
            .values()
        )

        # Group data by section if section is not passed
        grouped_table_data = {}
        for row in table_data_query:
            section = row['section']
            if section not in grouped_table_data:
                grouped_table_data[section] = []
            
            grouped_table_data[section].append({
                'Date': row['planned_dates'].strftime('%d-%m-%Y') if row['planned_dates'] else row['planned_dates'],
                'Operation': row['operation'],
                'Style': row['style'],
                'Buyer': row['buyer'],
                'Color': row['color'].upper() if row['color'] else row['color'],
                'OC Number': row['oc_no'].upper() if row['oc_no'] else row['oc_no'],
                'Order Number': row['order_no'],
                'Machine Type': row['machine_type'],
                'Operator Name': row['allocated_emp_name'],
                'Operator ID': row['allocated_emp_id'],
                'SAM': row['sam'],
                'Week': row['week'],
                'Planned Quantity': row['planned_qty'],
                'Allocated Capacity': row['allocated_capacity'],
                'Shortage Reason': row['shortage_reason'],
            })

        actual_machinists = list(EmployeeMaster.objects.filter(**employee_master_filters).values('section').annotate(actual_machinists=Count('emp_code')))  # or another unique field like 'emp_code'

        # Step 1: Group data by section and operation with unique (machine_type, operator_name, operator_id)
        grouped_result = defaultdict(lambda: defaultdict(set))

        grouped_data = filtered_data_table.only(
            'section', 'operation', 'machine_type', 'allocated_emp_name', 'allocated_emp_id'
        )

        for row in grouped_data:
            section = row.section or "Unknown"
            operation = row.operation or "Unknown"
            key = (row.machine_type, row.allocated_emp_name or "N/A", row.allocated_emp_id)
            grouped_result[section][operation].add(key)

        # Step 2: Flatten grouped data into required output structure
        grouped_machine_nonMachine_info = {}
        required_machinists = []

        for section, operations in grouped_result.items():
            machine_type_count = defaultdict(int)
            machinist_count = 0

            for entries in operations.values():
                for machine_type, operator_name, operator_id in entries:
                    machine_type_count[machine_type] += 1
                    machinist_count += 1

            # Store machine type counts
            grouped_machine_nonMachine_info[section] = dict(machine_type_count)

            # Store machinist count if needed
            required_machinists.append({
                'section': section,
                'required_machinists': machinist_count
            })

        # Convert lists to dictionaries keyed by 'section'
        actual_dict = {item['section']: item['actual_machinists'] for item in actual_machinists}
        required_dict = {item['section']: item['required_machinists'] for item in required_machinists}

        # Merge into desired format
        grouped_general_info = {}
        for section in set(actual_dict) | set(required_dict):  # union of both keys
            grouped_general_info[section] = {
                'total_required': required_dict.get(section, 0),
                'total_available': actual_dict.get(section, 0)
            }

        # Aggregate info data from filtered_data_table (grouped by section)
        info_query = filtered_data_table.values('section').annotate(
            buyers=Count('buyer', distinct=True)
        )

        # Group buyers info by section
        grouped_info = {}
        for entry in info_query:
            section = entry['section']
            buyers_list = list(filtered_data_table.filter(section=section).values_list('buyer', flat=True).distinct())
            grouped_info[section] = {'buyers': [buyer.upper() for buyer in buyers_list if buyer]}  # Capitalize

        # Aggregate unique styles by section
        unique_styles_query = filtered_data_table.values('section').annotate(
            styles=Count('style', distinct=True)  # Count distinct styles
        )

        # Group unique styles by section
        grouped_unique_styles = {}
        for entry in unique_styles_query:
            section = entry['section']
            styles_list = list(filtered_data_table.filter(section=section).values_list('style', flat=True).distinct())
            grouped_unique_styles[section] = {'unique_styles': [style.upper() for style in styles_list if style]}  # Capitalize

        grouped_prediction_report={}
        for sec in ['Assembly', 'Cuff', 'Front', 'Back', 'Sleeve', 'Collar']:
            prediction_response = get_actual_vs_planned_data(line_no=line_no, forecast_period=period, today=today, section=sec)
            grouped_prediction_report[sec] = prediction_response.data['data']

        # Prepare response data
        response_data = {
            'table_data': grouped_table_data,
            'machinist_nonMachinist_count': grouped_general_info,
            'machinist_nonMachinist_info': grouped_machine_nonMachine_info,
            'info': grouped_info,
            'unique_styles': grouped_unique_styles,
            'prediction_report': grouped_prediction_report,
            'message': 'Success'
        }

        excel_data = export_json_to_excel(response_data)

        response = HttpResponse(
            excel_data.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = f'attachment; filename="{line_no.title()}_ManningSheet__{period}Days.xlsx"'
        return response

    except Exception as e:
        return success_response(message=f"Error: {str(e)}", data=None, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def download_manning_attendance_data(request):
    """
    Retrieve attendance statistics with a single highly optimized database query
    using Django's conditional expressions and fetch dday data and export it as excel or via email
    """
    try:
        # Get and validate line parameter
        line_no = request.query_params.get('line', '').strip().title()
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
        dday_data = fetch_dday_data(line_no)
        attendance_data = fetch_attendance_data(line_no, today, yesterday)
        prediction_response = get_dday_actual_vs_planned_data(line_no=line_no, today=today)
        prediction_data = prediction_response.data['data']['Target data']
        # FIXED: Correct structure based on get_dday_actual_vs_planned_data function
        if line_no == 'All':
            # For "All" lines: {"Target data": {"production_target": x, "predicted_production": y, "line_wise_breakdown": [...]}}
            production_target = prediction_data.get('production_target', 0.0)
            predicted_production = prediction_data.get('predicted_production', 0.0)
        else:
            # For single line: {"Target data": {"line": "Line X", "production_target": x, "predicted_production": y, "style_breakdown": [...]}}
            production_target = prediction_data.get('production_target', 0.0)
            predicted_production = prediction_data.get('predicted_production', 0.0)
        unallocated_emp_data = get_unallocated_employees_count(line_no=line_no)
        type_of_export = request.query_params.get('type', '').strip().lower()
        email = request.query_params.get('email', '').strip()
        df = pd.DataFrame(dday_data["data"]["records"])
        df.drop(columns=['Dday_ID', 'WIP Qty'], inplace=True)
        # Generate Excel file in memory
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name="Sheet1", startrow=9, index=False)
            # Get the worksheet AFTER writing the DataFrame
            worksheet = writer.sheets["Sheet1"]
            workbook = writer.book
            bold_format = workbook.add_format({'bold': True})  # Bold format for headers
            # Write attendance data at the top with proper alignment
            worksheet.write(0, 0, "Line number", bold_format)
            worksheet.write(0, 1, line_no)
            worksheet.write(1, 0, "Planned Attendance", bold_format)
            worksheet.write(1, 1, attendance_data['data']['attendance_data']['Planned Attendance'])
            worksheet.write(2, 0, "Present", bold_format)
            worksheet.write(2, 1, attendance_data['data']['attendance_data']['Present'])
            worksheet.write(3, 0, "Absent", bold_format)
            worksheet.write(3, 1, attendance_data['data']['attendance_data']['Absent'])
            worksheet.write(4, 0, "Unallocated Operators", bold_format)
            worksheet.write(4, 1, unallocated_emp_data)
            worksheet.write(5, 0, "Production Target", bold_format)
            worksheet.write(5, 1, production_target)
            worksheet.write(6, 0, "Predicted Production", bold_format)  # Changed label for clarity
            worksheet.write(6, 1, predicted_production)
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
            for row_num in range(10, 10 + len(df)):  # Since headers are at row 9, data starts at 10
                worksheet.write(row_num, preferred_col_index, df["Preferred Employees"].iloc[row_num - 10], truncate_format)
        output.seek(0)
        if type_of_export == 'email':
            if not email:
                return error_response(error="Email address is required.", status=status.HTTP_400_BAD_REQUEST)
            subject = "Download D-Day Manning Data File"
            file_name = f"Dday_Manning_data_{line_no}.xlsx"
            file_data = output  # Pass the BytesIO object directly
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            # Call the send_email function
            email_body = send_email(email, file_data, subject, content_type, file_name=file_name)
            if not email_body:
                return error_response(
                    error="Error sending email, Invalid email address.",
                    status=status.HTTP_404_NOT_FOUND
                )
            return success_response(
                message=f"Email sent successfully to {email}.",
                data={"message": "File attached to the email."},
                status=status.HTTP_200_OK
            )
        elif type_of_export == 'excel':
            # Return the file as a downloadable response
            response = HttpResponse(
                output.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            response["Content-Disposition"] = f'attachment; filename="Dday_Manning_data_{line_no}.xlsx"'
            return response
        else:
            return error_response(error='Type should be "email" or "excel".', status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return error_response(
            error="An unexpected error occurred. Please try again later.",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def download_notification_file(request):
    """
    Download a file attached to a specific notification for the authenticated user.

    Request Parameters (query):
        - notification_id (int): ID of the notification containing the file.

    Behavior:
        - Verifies the presence of notification_id.
        - Retrieves the corresponding PushNotification for the logged-in user.
        - Checks if the notification contains a 'fileName' in its data field.
        - Checks if the corresponding file exists in the 'exports' directory.
        - Returns the file as a downloadable response if found.

    Returns:
        - 200 OK with the file if everything is valid.
        - 400 if notification_id is missing.
        - 404 if the notification, data, or fileName is not found.
        - 500 on unexpected server error.
    """
    try:
        notification_id = request.query_params.get('notification_id', None)

        if not notification_id:
            return error_response(
                error="Notification ID is required",
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create base filter dictionary
        base_filter = {
            'user': request.user,
            'id': int(notification_id)
        }
        
        # Get notification object using the filter dictionary
        notification = PushNotification.objects.get(**base_filter)

        if not notification:
            return error_response(
                error="Notification not found",
                status=status.HTTP_404_NOT_FOUND
            )

        if not notification.data:
            return error_response(
                error="No data available for this notification",
                status=status.HTTP_404_NOT_FOUND
            )
        
        if "fileName" not in notification.data:
            return error_response(
                error="File name not found in notification data",
                status=status.HTTP_404_NOT_FOUND
            )
        file_name = notification.data["fileName"]
        file_path = os.path.join("exports", file_name)

        # Check if the file exists
        if not os.path.exists(file_path):
            return error_response(
                error="File not found",
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Open the file and return it as a response for download
        response = FileResponse(open(file_path, 'rb'), as_attachment=True, filename=file_name)
        return response

    except Exception as e:
        return error_response(
            error=f"Failed to retrieve notification's data: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
