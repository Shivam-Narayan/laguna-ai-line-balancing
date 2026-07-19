import uuid
from typing import Any, Optional

from django.db import models, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.models import BaseModel

from .user import User


class LockType(models.TextChoices):
    DATA_UPDATE = "data_update", "Data Update Endpoint"


class EndpointLock(BaseModel):
    """
    Enhanced model to manage endpoint-level locks with user-specific restrictions
    """

    lock_type = models.CharField(max_length=50, choices=LockType.choices)
    locked_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="endpoint_locks"
    )
    locked_at = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=True, db_index=True)

    # Add additional fields to track user session/origin
    session_id = models.UUIDField(unique=True, default=uuid.uuid4)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, null=True, blank=True)
    url_name = models.CharField(null=True, blank=True, max_length=1000)

    class Meta:
        db_table = "accounts_endpointlock"

    @classmethod
    def acquire_lock(
        cls, lock_type: str, user: User, url_name: str, request: Optional[Any] = None
    ) -> "EndpointLock":
        """
        Acquire or update a lock for a specific endpoint and user.
        """
        with transaction.atomic():
            lock_expiry_time = timezone.now() - timezone.timedelta(minutes=10)

            # Auto-expire old locks
            cls.objects.filter(
                lock_type=lock_type,
                url_name=url_name,
                is_active=True,
                locked_at__lt=lock_expiry_time,
            ).update(is_active=False)

            # Check if current user already holds a lock
            existing_lock = cls.objects.filter(
                lock_type=lock_type, locked_by=user, url_name=url_name
            ).first()

            if existing_lock:
                # If already locked by this user and active, raise error
                if existing_lock.is_active:
                    raise ValidationError(
                        "You already have an active lock on this endpoint. Please wait."
                    )

                # Reactivate expired lock
                existing_lock.locked_at = timezone.now()
                existing_lock.is_active = True
                if request:
                    existing_lock.ip_address = cls.get_client_ip(request)
                    existing_lock.user_agent = request.META.get("HTTP_USER_AGENT", "")[
                        :255
                    ]
                existing_lock.save()
                return existing_lock

            # Check if someone else has the lock active
            if cls.objects.filter(
                lock_type=lock_type, is_active=True, url_name=url_name
            ).exists():
                raise ValidationError(
                    "Endpoint is currently locked by another user. Please try again later."
                )

            # Create a new lock for the user
            lock_details = {
                "lock_type": lock_type,
                "locked_by": user,
                "url_name": url_name,
                "is_active": True,
                "locked_at": timezone.now(),
            }

            if request:
                lock_details.update(
                    {
                        "ip_address": cls.get_client_ip(request),
                        "user_agent": request.META.get("HTTP_USER_AGENT", "")[:255],
                    }
                )

            return cls.objects.create(**lock_details)

    @classmethod
    def release_lock(cls, lock_type: str, user: User, url_name: str) -> int:
        """
        Release the lock for a specific endpoint.
        Returns the number of locks released.
        """
        with transaction.atomic():
            # update() returns the number of rows affected — capture it before the queryset re-evaluates
            count = cls.objects.filter(
                lock_type=lock_type, locked_by=user, url_name=url_name, is_active=True
            ).update(is_active=False)
            return count

    @classmethod
    def get_client_ip(cls, request: Any) -> Optional[str]:
        """
        Retrieve client IP address
        """
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0]
        else:
            ip = request.META.get("REMOTE_ADDR")
        return ip
