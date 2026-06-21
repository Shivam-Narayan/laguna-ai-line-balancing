import uuid
from django.utils import timezone
from django.db import models, transaction
from django.core.exceptions import ValidationError
from .user import User

class EndpointLock(models.Model):
    """
    Enhanced model to manage endpoint-level locks with user-specific restrictions
    """
    LOCK_TYPES = (
        ('data_update', 'Data Update Endpoint'),
        # Add more lock types as needed
    )

    lock_type = models.CharField(max_length=50, choices=LOCK_TYPES)
    locked_by = models.ForeignKey(User, on_delete=models.CASCADE)
    locked_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    
    # Add additional fields to track user session/origin
    session_id = models.UUIDField(unique=True, default=uuid.uuid4)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    url_name = models.CharField(null=True, blank=True, max_length=1000)

    class Meta:
        db_table="accounts_endpointlock"

    @classmethod
    def acquire_lock(cls, lock_type, user, url_name, request=None):
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
                locked_at__lt=lock_expiry_time
            ).update(is_active=False)

            # Check if current user already holds a lock
            existing_lock = cls.objects.filter(
                lock_type=lock_type,
                locked_by=user,
                url_name=url_name
            ).first()

            if existing_lock:
                # If already locked by this user and active, raise error
                if existing_lock.is_active:
                    raise ValidationError("You already have an active lock on this endpoint. Please wait.")

                # Reactivate expired lock
                existing_lock.locked_at = timezone.now()
                existing_lock.is_active = True
                if request:
                    existing_lock.ip_address = cls.get_client_ip(request)
                    existing_lock.user_agent = request.META.get('HTTP_USER_AGENT', '')[:255]
                existing_lock.save()
                return existing_lock

            # Check if someone else has the lock active
            if cls.objects.filter(
                lock_type=lock_type,
                is_active=True,
                url_name=url_name
            ).exists():
                raise ValidationError("Endpoint is currently locked by another user. Please try again later.")

            # Create a new lock for the user
            lock_details = {
                'lock_type': lock_type,
                'locked_by': user,
                'url_name': url_name,
                'is_active': True,
                'locked_at': timezone.now(),
            }

            if request:
                lock_details.update({
                    'ip_address': cls.get_client_ip(request),
                    'user_agent': request.META.get('HTTP_USER_AGENT', '')[:255]
                })

            return cls.objects.create(**lock_details)

    @classmethod
    def release_lock(cls, lock_type, user, url_name):
        """
        Release the lock for a specific endpoint
        """
        with transaction.atomic():
            locks = cls.objects.filter(
                lock_type=lock_type, 
                locked_by=user,
                url_name=url_name,
                is_active=True
            )
            
            locks.update(is_active=False)
            return locks.count()

    @classmethod
    def get_client_ip(cls, request):
        """
        Retrieve client IP address
        """
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
