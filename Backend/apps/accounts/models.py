import uuid

from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.utils.timezone import now
from django.db import models, transaction
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin


class CustomUserManager(BaseUserManager):
    def create_user(self, username, email, password=None, **extra_fields):
        if not username:
            raise ValueError('Username is required')
        if not email:
            raise ValueError('Email is required')
        
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(username, email, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):
    last_login = None #disabled this field
    id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=150)
    email = models.EmailField(unique=True, max_length=255)
    location = models.CharField(max_length=50, default="", blank=True)
    department = models.CharField(max_length=100, default="", blank=True)
    status = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    phonenumber = models.CharField(
        max_length=10,
        validators=[RegexValidator(
            regex=r'^[6-9]\d{9}$',
            message="Phone number must be a valid 10-digit number starting with 6-9."
        )],
        blank=True,
    )
    user_type = models.PositiveIntegerField(choices=[(0, 'Normal'), (1, 'Admin')], default=0)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True) 
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    send_mail = models.BooleanField(default=False)
    
    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'location', 'department', 'phonenumber', 'user_type']

    def __str__(self):
        return self.username
    


class PasswordResetToken(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='password_reset_tokens')
    token = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        """Check if the token is expired (valid for 10 minutes)."""
        return now() > self.created_at + timedelta(minutes=10)


def default_expiry():
    return timezone.now() + timedelta(days=365)  # 1-year expiry
    
# Function to generate a unique token
def generate_unique_token():
    return uuid.uuid4().hex  

# Custom Multi-Session Token Model
class MultiSessionToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    key = models.CharField(max_length=40, unique=True, default=generate_unique_token)
    created = models.DateTimeField(auto_now_add=True)
    expiry = models.DateTimeField(default=default_expiry)  # 1-year expiry

    def is_expired(self):
        return timezone.now() > self.expiry

    def refresh_token(self):
        """Refresh token validity if expired"""
        if self.is_expired():
            self.key = generate_unique_token()
            self.expiry = timezone.now() + timedelta(days=365)
            self.save()

    def __str__(self):
        return f"{self.user.email} - {self.key}"

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

