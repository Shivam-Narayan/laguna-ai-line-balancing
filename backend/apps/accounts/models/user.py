from typing import Any, Optional
from django.db import models
from django.utils import timezone
from django.core.validators import RegexValidator
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from apps.core.models import BaseModel

class CustomUserManager(BaseUserManager):
    def create_user(self, username: str, email: str, password: Optional[str] = None, **extra_fields: Any) -> "User":
        if not username:
            raise ValueError('Username is required')
        if not email:
            raise ValueError('Email is required')
        
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username: str, email: str, password: Optional[str] = None, **extra_fields: Any) -> "User":
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(username, email, password, **extra_fields)

class UserType(models.IntegerChoices):
    NORMAL = 0, 'Normal'
    ADMIN = 1, 'Admin'

class User(AbstractBaseUser, PermissionsMixin, BaseModel):
    last_login = None  # Intentionally disabled — we do not track last login
    is_staff = models.BooleanField(default=False)  # Required for Django Admin access
    username = models.CharField(max_length=150)
    email = models.EmailField(unique=True, max_length=255, db_index=True)
    location = models.CharField(max_length=50, default="", blank=True)
    department = models.CharField(max_length=100, default="", blank=True)
    status = models.BooleanField(default=True, db_index=True)
    phonenumber = models.CharField(
        max_length=10,
        validators=[RegexValidator(
            regex=r'^[6-9]\d{9}$',
            message="Phone number must be a valid 10-digit number starting with 6-9."
        )],
        blank=True,
    )
    user_type = models.IntegerField(choices=UserType.choices, default=UserType.NORMAL)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True) 
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    send_mail = models.BooleanField(default=False)

    class Meta:
        db_table = 'accounts_user'
        ordering = ['-created_at']
    
    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'location', 'department', 'phonenumber', 'user_type']

    def __str__(self):
        return self.username

from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.apps import apps

@receiver(pre_delete, sender=User)
def _clear_jwt_outstanding_tokens(sender: Any, instance: "User", **kwargs: Any) -> None:
    """
    SimpleJWT's OutstandingToken model has a ForeignKey to the User model but does 
    not use CASCADE deletion. We must manually delete the tokens before deleting the user 
    to prevent an IntegrityError (Foreign Key constraint violation).
    """
    try:
        OutstandingToken = apps.get_model('token_blacklist', 'OutstandingToken')
    except LookupError:
        return

    OutstandingToken.objects.filter(user=instance).delete()
