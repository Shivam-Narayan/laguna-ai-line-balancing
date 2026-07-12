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

from apps.accounts.api.authentication import CookieJWTAuthentication
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

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def update_allocated_employees(request):
    try:
        final_allocation = request.data.get('final_allocation')
        dday_id = request.data.get('dday_id')

        dday_instance = get_object_or_404(DDayData, pk=dday_id)
        dday_instance.final_allocation = final_allocation
        dday_instance.save()
        return success_response(message='Successully updated the allocation employee.', status=status.HTTP_200_OK)
    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def update_employee_on_hold_individual(request):
    try:
        preferred_employee = request.data.get('preferred_employee')
        employee_name = None
        employee_id = 0
        allocated_capacity = request.data.get('allocated_capacity')
        for emp_id, emp_name in preferred_employee.items():
            employee_id = emp_id
            employee_name = emp_name
        manning_id = request.data.get('manning_id')

        manning_instance = get_object_or_404(ManningSheetData, pk=manning_id)

        try:
            employees_on_hold_instance = EmployeesOnHold.objects.get(
                line=manning_instance.line,
                section=manning_instance.section,
                date=manning_instance.planned_dates
            )

            manning_instance.allocated_emp_id = employee_id
            manning_instance.allocated_emp_name = employee_name
            if allocated_capacity:
                manning_instance.allocated_capacity = allocated_capacity

            preferred_employees = json.loads(employees_on_hold_instance.preferred_employees)
            if preferred_employee in preferred_employees:
                preferred_employees = remove_by_employee_id(preferred_employees, employee_id)
                employees_on_hold_instance.preferred_employees = json.dumps(preferred_employees)
                employees_on_hold_instance.count = len(preferred_employees) if preferred_employees else 0
                manning_instance.save()
                employees_on_hold_instance.save()
                return success_response(message='Successully updated the allocation of an employee.', status=status.HTTP_200_OK)
            else:
                return error_response(error='Employee not found in the preferred employees list.', status=status.HTTP_400_BAD_REQUEST)
        except EmployeesOnHold.DoesNotExist:
            return error_response(error='No EmployeesOnHold instance found for the given line, section, and date.', status=status.HTTP_404_NOT_FOUND)

    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def update_employee_on_hold(request):
    try:
        multiple_ids = request.data.get('multiple_IDs', [])
        if not multiple_ids:
            return error_response(error='No data found in multiple_IDs.', status=status.HTTP_400_BAD_REQUEST)

        for entry in multiple_ids:
            preferred_employee = entry.get('preferred_employee')
            allocated_capacity = entry.get('allocated_capacity')
            manning_id = entry.get('manning_id')

            if not (preferred_employee and manning_id):
                continue  # Skip this entry if essential data is missing

            employee_name = None
            employee_id = 0

            for emp_id, emp_name in preferred_employee.items():
                employee_id = emp_id
                employee_name = emp_name

            manning_instance = get_object_or_404(ManningSheetData, pk=manning_id)

            try:
                employees_on_hold_instance = EmployeesOnHold.objects.get(
                    line=manning_instance.line,
                    section=manning_instance.section,
                    date=manning_instance.planned_dates
                )

                manning_instance.allocated_emp_id = employee_id
                manning_instance.allocated_emp_name = employee_name
                if allocated_capacity:
                    manning_instance.allocated_capacity = allocated_capacity

                preferred_employees = json.loads(employees_on_hold_instance.preferred_employees)

                if any(str(employee_id) == str(eid) for eid in map(str, [list(emp.keys())[0] for emp in preferred_employees])):
                    # preferred_employees = remove_by_employee_id(preferred_employees, employee_id)
                    # employees_on_hold_instance.preferred_employees = json.dumps(preferred_employees)
                    # employees_on_hold_instance.count = len(preferred_employees) if preferred_employees else 0
                    manning_instance.save()
                    # employees_on_hold_instance.save()
                else:
                    return error_response(error=f'Employee {employee_id} not found in preferred employees list for manning_id {manning_id}.',
                                          status=status.HTTP_400_BAD_REQUEST)
            except EmployeesOnHold.DoesNotExist:
                return error_response(error=f'No EmployeesOnHold instance found for manning_id {manning_id}.',
                                      status=status.HTTP_404_NOT_FOUND)

        return success_response(message='Successfully updated the allocation of all employees.', status=status.HTTP_200_OK)

    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def update_allocated_capacity(request):
    try:
        allocated_capacity = request.data.get('allocated_capacity')
        manning_id = request.data.get('manning_id')

        # Validate required fields
        if not allocated_capacity or not manning_id:
            return error_response(error='"allocated_capacity" and "manning_id" are required.', status=status.HTTP_400_BAD_REQUEST)

        manning_instance = get_object_or_404(ManningSheetData, pk=manning_id)

        try:
            manning_instance.allocated_capacity = allocated_capacity
            manning_instance.save()
            return success_response(message='Successully updated the allocated capacity of an employee.', status=status.HTTP_200_OK)
        except EmployeesOnHold.DoesNotExist:
            return error_response(error='Error in allocating capacity to an employee.', status=status.HTTP_404_NOT_FOUND)

    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)
