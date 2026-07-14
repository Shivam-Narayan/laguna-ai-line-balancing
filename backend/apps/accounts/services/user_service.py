from typing import Tuple, Optional, Dict, Any
from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError
from apps.accounts.utils.validators import validate_password

User = get_user_model()

def change_user_password(user, current_password: str, new_password: str, confirm_password: str) -> Tuple[Optional[str], int]:
    """Changes the password for a user after validating the current password and new password rules."""
    if not all([current_password, new_password, confirm_password]):
        return "All fields are required: current_password, new_password, confirm_password", 400

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


def delete_user_account(user_id: int) -> Tuple[Optional[Dict[str, Any]], Optional[str], int]:
    """Deletes a user account by ID and returns the details of the deleted user."""
    try:
        user = User.objects.get(id=user_id)
        user_details = {
            'username': user.username,
            'email': user.email,
            'location': user.location,
            'department': user.department,
            'status': user.status,
        }
        user.delete()
        return user_details, None, 200
    except User.DoesNotExist:
        return None, "User not found", 404
    except Exception as e:
        return None, f"An error occurred while deleting the user: {str(e)}", 500
