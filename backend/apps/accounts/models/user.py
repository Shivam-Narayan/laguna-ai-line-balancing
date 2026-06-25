from django.db import models
from django.utils import timezone
from django.core.validators import RegexValidator
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
    import uuid
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
