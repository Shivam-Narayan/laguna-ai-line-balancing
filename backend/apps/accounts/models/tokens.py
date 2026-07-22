import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel


class PasswordResetToken(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="password_reset_tokens",
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)

    class Meta:
        db_table = "accounts_passwordresettoken"

    def is_expired(self) -> bool:
        """Check if the token is expired (valid for 10 minutes)."""
        return timezone.now() > self.created_at + timedelta(minutes=10)


def default_expiry() -> datetime:
    return timezone.now() + timedelta(days=365)  # 1-year expiry


# Function to generate a unique token
def generate_unique_token() -> str:
    return uuid.uuid4().hex


# Custom Multi-Session Token Model
class MultiSessionToken(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="multi_session_tokens"
    )
    key = models.CharField(
        max_length=40, unique=True, default=generate_unique_token, db_index=True
    )
    expiry = models.DateTimeField(default=default_expiry)  # 1-year expiry

    class Meta:
        db_table = "accounts_multisessiontoken"

    def is_expired(self) -> bool:
        return timezone.now() > self.expiry

    def refresh_token(self) -> None:
        """Refresh token validity (extends expiry by 1 year from now)"""
        self.expiry = timezone.now() + timedelta(days=365)
        self.save(update_fields=['expiry', 'updated_at'])

    def __str__(self) -> str:
        return f"{self.user.email} - {self.key}"
