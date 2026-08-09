import logging
import os
from datetime import datetime, timedelta

import pytz
from django.db import transaction
from django.utils import timezone

from ..models import (
    PushNotification,
)

logger = logging.getLogger("general")

CHUNK_SIZE = 1000
os.makedirs("exports", exist_ok=True)

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


class NotificationServiceError(Exception):
    pass


class NotificationService:
    """Handles business logic for push notifications."""

    @staticmethod
    def get_user_notifications(user, unread_only):
        """
        Get all notifications for the authenticated user from the last 7 days.
        Returns a list of notification dicts.
        """
        try:
            seven_days_ago = datetime.now() - timedelta(days=7)
            base_filter = {"user": user, "created_at__gte": seven_days_ago}
            if unread_only:
                base_filter["is_read"] = False

            notifications = PushNotification.objects.filter(**base_filter).order_by("-created_at")

            notification_list = []
            for notification in notifications:
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
            return notification_list
        except Exception as e:
            raise NotificationServiceError(f"Failed to retrieve notifications: {str(e)}")

    @staticmethod
    def mark_notification_read(user, mark_all, notification_id):
        """Mark one or all notifications as read for the given user."""
        try:
            if mark_all:
                unread_filter = {"user": user, "is_read": False}
                with transaction.atomic():
                    PushNotification.objects.filter(**unread_filter).update(is_read=True)
                return "All notifications marked as read"

            if not notification_id:
                raise ValueError("notification_id is required")

            notification_filter = {"id": notification_id, "user": user}
            updated_count = PushNotification.objects.filter(**notification_filter).update(is_read=True)

            if updated_count == 0:
                raise LookupError("Notification not found")

            return "Notification marked as read"
        except (ValueError, LookupError):
            raise
        except Exception as e:
            raise NotificationServiceError(f"Failed to mark notification as read: {str(e)}")

    @staticmethod
    def create_test_notification(user):
        """Create test notifications with different dates to test the 7-day filter."""
        try:
            today_notification = PushNotification.objects.create(
                user=user,
                title="Test Notification - Today",
                message="This is a test notification created today",
                created_at=datetime.now(),
            )
            five_days_ago = datetime.now() - timedelta(days=5)
            five_days_notification = PushNotification.objects.create(
                user=user,
                title="Test Notification - 5 Days Ago",
                message="This is a test notification created 5 days ago",
                created_at=five_days_ago,
            )
            ten_days_ago = datetime.now() - timedelta(days=10)
            ten_days_notification = PushNotification.objects.create(
                user=user,
                title="Test Notification - 10 Days Ago",
                message="This is a test notification created 10 days ago",
                created_at=ten_days_ago,
            )
            return [
                {"id": today_notification.id, "title": today_notification.title, "created_at": today_notification.created_at},
                {"id": five_days_notification.id, "title": five_days_notification.title, "created_at": five_days_notification.created_at},
                {"id": ten_days_notification.id, "title": ten_days_notification.title, "created_at": ten_days_notification.created_at},
            ]
        except Exception as e:
            raise NotificationServiceError(f"Failed to create test notifications: {str(e)}")


# --- Backward Compatibility Wrappers ---
def run_get_user_notifications(user, unread_only):
    from rest_framework import status
    from apps.accounts.utils.response_handlers import error_response, success_response
    try:
        data = NotificationService.get_user_notifications(user, unread_only)
        return success_response(message="Notifications retrieved successfully", data={"notifications": data}, status=status.HTTP_200_OK)
    except NotificationServiceError as e:
        return error_response(error=str(e), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def run_mark_notification_read(user, mark_all, notification_id):
    from rest_framework import status
    from apps.accounts.utils.response_handlers import error_response, success_response
    try:
        msg = NotificationService.mark_notification_read(user, mark_all, notification_id)
        return success_response(message=msg, status=status.HTTP_200_OK)
    except ValueError as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
    except LookupError as e:
        return error_response(error=str(e), status=status.HTTP_404_NOT_FOUND)
    except NotificationServiceError as e:
        return error_response(error=str(e), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def run_create_test_notification(user):
    from rest_framework import status
    from apps.accounts.utils.response_handlers import error_response, success_response
    try:
        data = NotificationService.create_test_notification(user)
        return success_response(message="Test notifications created successfully", data={"notifications": data}, status=status.HTTP_201_CREATED)
    except NotificationServiceError as e:
        return error_response(error=str(e), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
