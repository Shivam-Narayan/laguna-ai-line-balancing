from typing import Any, Dict, Optional, Tuple

from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError

from apps.accounts.utils.validators import validate_password

User = get_user_model()
import logging

from apps.accounts.serializers import (
    RegisterUserSerializer,
    UpdateUserSerializer,
    UserSerializer,
)

logger = logging.getLogger(__name__)


def register_new_user(
    data: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[Any], int]:
    try:
        serializer = RegisterUserSerializer(data=data)
        if serializer.is_valid():
            user = serializer.save()
            user_details = {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "location": user.location,
                "department": user.department,
                "status": user.status,
                "send_mail": user.send_mail,
            }
            return user_details, None, 201
        return None, serializer.errors, 400
    except ValidationError as e:
        return None, str(e), 400
    except Exception:
        logger.exception("Unexpected error during register_new_user")
        return None, "An unexpected error occurred.", 500


def get_all_users() -> Tuple[Optional[Any], Optional[str], int]:
    try:
        users = User.objects.filter(user_type=0)
        serializer = UserSerializer(users, many=True)
        return serializer.data, None, 200
    except Exception:
        logger.exception("Unexpected error during get_all_users")
        return None, "An unexpected error occurred.", 500


def get_user_by_id(user_id: int) -> Tuple[Optional[Any], Optional[str], int]:
    try:
        user = User.objects.get(id=user_id)
        serializer = UserSerializer(user)
        return serializer.data, None, 200
    except User.DoesNotExist:
        return None, "User not found", 404
    except Exception:
        logger.exception("Unexpected error during get_user_by_id")
        return None, "An unexpected error occurred.", 500


def update_user_details(
    user_id: int, data: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Optional[Any], int]:
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return None, "User not found.", 404

    serializer = UpdateUserSerializer(user, data=data)
    if serializer.is_valid():
        updated_user = serializer.save()
        user_details = {
            "id": updated_user.id,
            "username": updated_user.username,
            "email": updated_user.email,
            "location": updated_user.location,
            "department": updated_user.department,
            "phonenumber": updated_user.phonenumber,
            "user_type": updated_user.user_type,
            "status": updated_user.status,
        }
        return user_details, None, 200
    return None, serializer.errors, 400


def change_user_password(
    user, current_password: str, new_password: str, confirm_password: str
) -> Tuple[Optional[str], int]:
    """Changes the password for a user after validating the current password and new password rules."""
    if not all([current_password, new_password, confirm_password]):
        return (
            "All fields are required: current_password, new_password, confirm_password",
            400,
        )

    if not user.check_password(current_password):
        return "Current password is incorrect", 400

    try:
        validate_password(new_password)
    except ValidationError as e:
        return str(e), 400

    if new_password != confirm_password:
        return "New password and confirm password do not match", 400

    if user.check_password(new_password):
        return "New password must be different from the previous passwords", 400

    user.set_password(new_password)
    user.save()
    return None, 200


def delete_user_account(
    user_id: int,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], int]:
    """Deletes a user account by ID and returns the details of the deleted user."""
    try:
        user = User.objects.get(id=user_id)
        user_details = {
            "username": user.username,
            "email": user.email,
            "location": user.location,
            "department": user.department,
            "status": user.status,
        }
        user.delete()
        return user_details, None, 200
    except User.DoesNotExist:
        return None, "User not found", 404
    except Exception as e:
        return None, f"An error occurred while deleting the user: {str(e)}", 500
