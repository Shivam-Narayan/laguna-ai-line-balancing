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

def run_get_user_notifications(user, unread_only):
    """
    Get all notifications for the authenticated user from the last 7 days.
    Notifications are ordered by creation time (newest first).
    Optional query parameter 'unread_only=true' to get only unread notifications.
    """
    try:        
        # Calculate date 7 days ago
        seven_days_ago = datetime.now() - timedelta(days=7)
        
        # Create base filter dictionary
        base_filter = {
            'user': user,
            'created_at__gte': seven_days_ago
        }
        
        # Add unread filter if requested
        if unread_only:
            base_filter['is_read'] = False
        
        # Get notifications using the filter dictionary
        notifications = PushNotification.objects.filter(**base_filter).order_by('-created_at')
        
        # Convert to list of dictionaries
        notification_list = []
        for notification in notifications:
            # Convert created_at to IST
            created_at_ist = timezone.localtime(notification.created_at, pytz.timezone('Asia/Kolkata'))
            created_at_ist = created_at_ist.strftime('%B %d, %Y %I:%M %p')
            
            notification_list.append({
                'id': notification.id,
                'type': notification.get_notification_type_display(),
                'title': notification.title,
                'message': notification.message,
                'created_at': created_at_ist,
                'is_read': notification.is_read,
                'data': notification.data
            })
        
        return success_response(
            message="Notifications retrieved successfully",
            data={'notifications': notification_list},
            status=status.HTTP_200_OK
        )
    
    except Exception as e:
        return error_response(
            error=f"Failed to retrieve notifications: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def run_mark_notification_read(user, mark_all, notification_id):
    """
    Mark a notification as read.
    Requires 'notification_id' in the request body to mark a specific notification as read.
    Optional 'mark_all=true' to mark all user's notifications as read.

    provide any one of the above in the request body.
    """
    try:
        if mark_all:
            # Create filter for marking all unread notifications
            unread_filter = {
                'user': user,
                'is_read': False
            }
            
            # Mark all notifications for this user as read
            with transaction.atomic():
                PushNotification.objects.filter(**unread_filter).update(is_read=True)
            
            return success_response(
                message="All notifications marked as read",
                status=status.HTTP_200_OK
            )
        
        
        
        if not notification_id:
            return error_response(
                error="notification_id is required",
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create filter for specific notification
        notification_filter = {
            'id': notification_id,
            'user': user
        }
        
        # Update notification in a single database call
        updated_count = PushNotification.objects.filter(**notification_filter).update(is_read=True)
        
        if updated_count == 0:
            return error_response(
                error="Notification not found",
                status=status.HTTP_404_NOT_FOUND
            )
        
        return success_response(
            message="Notification marked as read",
            status=status.HTTP_200_OK
        )
    
    except Exception as e:
        return error_response(
            error=f"Failed to mark notification as read: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def run_create_test_notification(user):
    """
    Create test notifications with different dates to test the 7-day filter.
    Creates 3 notifications:
    1. Today's notification
    2. 5 days old notification
    3. 10 days old notification (should not appear in 7-day filter)
    """
    try:
        
        # Create today's notification
        today_notification = PushNotification.objects.create(
            user=user,
            title="Test Notification - Today",
            message="This is a test notification created today",
            created_at=datetime.now()
        )
        
        # Create 5 days old notification
        five_days_ago = datetime.now() - timedelta(days=5)
        five_days_notification = PushNotification.objects.create(
            user=user,
            title="Test Notification - 5 Days Ago",
            message="This is a test notification created 5 days ago",
            created_at=five_days_ago
        )
        
        # Create 10 days old notification (should not appear in 7-day filter)
        ten_days_ago = datetime.now() - timedelta(days=10)
        ten_days_notification = PushNotification.objects.create(
            user=user,
            title="Test Notification - 10 Days Ago",
            message="This is a test notification created 10 days ago",
            created_at=ten_days_ago
        )
        
        return success_response(
            message="Test notifications created successfully",
            data={
                "notifications": [
                    {
                        "id": today_notification.id,
                        "title": today_notification.title,
                        "created_at": today_notification.created_at
                    },
                    {
                        "id": five_days_notification.id,
                        "title": five_days_notification.title,
                        "created_at": five_days_notification.created_at
                    },
                    {
                        "id": ten_days_notification.id,
                        "title": ten_days_notification.title,
                        "created_at": ten_days_notification.created_at
                    }
                ]
            },
            status=status.HTTP_201_CREATED
        )
        
    except Exception as e:
        return error_response(
            error=f"Failed to create test notifications: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
