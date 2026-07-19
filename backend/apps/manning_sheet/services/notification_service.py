import logging
import os
from datetime import datetime, timedelta

import pytz
from django.db import transaction
from django.db.models import FloatField, Func
from django.utils import timezone
from rest_framework import status

from apps.accounts.utils.response_handlers import error_response, success_response

from ..models import (
    PushNotification,
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
        base_filter = {"user": user, "created_at__gte": seven_days_ago}

        # Add unread filter if requested
        if unread_only:
            base_filter["is_read"] = False

        # Get notifications using the filter dictionary
        notifications = PushNotification.objects.filter(**base_filter).order_by(
            "-created_at"
        )

        # Convert to list of dictionaries
        notification_list = []
        for notification in notifications:
            # Convert created_at to IST
            created_at_ist = timezone.localtime(
                notification.created_at, pytz.timezone("Asia/Kolkata")
            )
            created_at_ist = created_at_ist.strftime("%B %d, %Y %I:%M %p")

            notification_list.append(
                {
                    "id": notification.id,
                    "type": notification.get_notification_type_display(),
                    "title": notification.title,
                    "message": notification.message,
                    "created_at": created_at_ist,
                    "is_read": notification.is_read,
                    "data": notification.data,
                }
            )

        return success_response(
            message="Notifications retrieved successfully",
            data={"notifications": notification_list},
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        return error_response(
            error=f"Failed to retrieve notifications: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
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
            unread_filter = {"user": user, "is_read": False}

            # Mark all notifications for this user as read
            with transaction.atomic():
                PushNotification.objects.filter(**unread_filter).update(is_read=True)

            return success_response(
                message="All notifications marked as read", status=status.HTTP_200_OK
            )

        if not notification_id:
            return error_response(
                error="notification_id is required", status=status.HTTP_400_BAD_REQUEST
            )

        # Create filter for specific notification
        notification_filter = {"id": notification_id, "user": user}

        # Update notification in a single database call
        updated_count = PushNotification.objects.filter(**notification_filter).update(
            is_read=True
        )

        if updated_count == 0:
            return error_response(
                error="Notification not found", status=status.HTTP_404_NOT_FOUND
            )

        return success_response(
            message="Notification marked as read", status=status.HTTP_200_OK
        )

    except Exception as e:
        return error_response(
            error=f"Failed to mark notification as read: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
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
            created_at=datetime.now(),
        )

        # Create 5 days old notification
        five_days_ago = datetime.now() - timedelta(days=5)
        five_days_notification = PushNotification.objects.create(
            user=user,
            title="Test Notification - 5 Days Ago",
            message="This is a test notification created 5 days ago",
            created_at=five_days_ago,
        )

        # Create 10 days old notification (should not appear in 7-day filter)
        ten_days_ago = datetime.now() - timedelta(days=10)
        ten_days_notification = PushNotification.objects.create(
            user=user,
            title="Test Notification - 10 Days Ago",
            message="This is a test notification created 10 days ago",
            created_at=ten_days_ago,
        )

        return success_response(
            message="Test notifications created successfully",
            data={
                "notifications": [
                    {
                        "id": today_notification.id,
                        "title": today_notification.title,
                        "created_at": today_notification.created_at,
                    },
                    {
                        "id": five_days_notification.id,
                        "title": five_days_notification.title,
                        "created_at": five_days_notification.created_at,
                    },
                    {
                        "id": ten_days_notification.id,
                        "title": ten_days_notification.title,
                        "created_at": ten_days_notification.created_at,
                    },
                ]
            },
            status=status.HTTP_201_CREATED,
        )

    except Exception as e:
        return error_response(
            error=f"Failed to create test notifications: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
