"""
Custom DRF permissions for the accounts app.
Add new permission classes here as the app grows.
"""

from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import View

from apps.accounts.models import UserType


class IsAdminUser(BasePermission):
    """
    Allows access only to users with user_type == UserType.ADMIN (1).
    Use this instead of Django's built-in is_staff flag.
    """

    message = (
        "You do not have permission to perform this action. Admin access required."
    )

    def has_permission(self, request: Request, view: View) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.user_type == UserType.ADMIN
        )


class IsOwnerOrAdmin(BasePermission):
    """
    Object-level permission: allow access if the requesting user owns the object
    or is an admin. The view must pass the object to has_object_permission().
    """

    message = "You do not have permission to access this resource."

    def has_object_permission(self, request: Request, view: View, obj: Any) -> bool:
        if request.user.user_type == UserType.ADMIN:
            return True

        # obj is expected to have a `user` or `id` attribute
        if hasattr(obj, "user"):
            return obj.user == request.user
        return obj == request.user
