from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.accounts.models import (
    EndpointLock,
    MultiSessionToken,
    PasswordResetToken,
    User,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "email",
        "username",
        "user_type",
        "location",
        "department",
        "status",
        "created_at",
    )
    list_filter = ("user_type", "status", "location", "department")
    search_fields = ("email", "username", "phonenumber")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Personal Info",
            {"fields": ("username", "phonenumber", "location", "department")},
        ),
        ("Location", {"fields": ("latitude", "longitude")}),
        (
            "Permissions",
            {
                "fields": (
                    "user_type",
                    "status",
                    "send_mail",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "username",
                    "password1",
                    "password2",
                    "user_type",
                    "location",
                    "department",
                ),
            },
        ),
    )


@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "token", "created_at")
    search_fields = ("user__email", "token")
    readonly_fields = ("created_at", "updated_at")


@admin.register(MultiSessionToken)
class MultiSessionTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "key", "expiry", "created_at")
    search_fields = ("user__email", "key")
    readonly_fields = ("created_at", "updated_at")


@admin.register(EndpointLock)
class EndpointLockAdmin(admin.ModelAdmin):
    list_display = ("lock_type", "locked_by", "url_name", "is_active", "locked_at")
    list_filter = ("lock_type", "is_active")
    search_fields = ("locked_by__email", "url_name")
    readonly_fields = ("session_id", "created_at", "updated_at")
