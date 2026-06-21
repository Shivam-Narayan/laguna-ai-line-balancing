import uuid
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.utils.timezone import now
from django.db import models
from .user import User

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
