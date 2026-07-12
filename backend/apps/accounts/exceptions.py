"""
Custom domain exceptions for the accounts app.

Raise these in services and catch them in views or middleware
for consistent error handling across the app.
"""


class AccountsError(Exception):
    """Base exception for all accounts domain errors."""
    pass


class InvalidCredentialsError(AccountsError):
    """Raised when login credentials are invalid."""
    pass


class UserNotActiveError(AccountsError):
    """Raised when a deactivated user attempts to authenticate."""
    pass


class UserNotFoundError(AccountsError):
    """Raised when a user lookup fails."""
    pass


class TokenExpiredError(AccountsError):
    """Raised when a token (e.g. password reset) has expired."""
    pass


class GeofenceError(AccountsError):
    """Raised when a user is outside the permitted geofence."""
    pass


class PasswordValidationError(AccountsError):
    """Raised when a new password fails validation rules."""
    pass
