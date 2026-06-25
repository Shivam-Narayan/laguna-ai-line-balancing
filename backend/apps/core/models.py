import uuid
from django.db import models
from django.utils import timezone

class BaseModel(models.Model):
    """
    Abstract Base Model that all other models should inherit from.
    Provides standard UUID primary key and audit timestamps.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
