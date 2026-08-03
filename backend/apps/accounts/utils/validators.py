import re

from django.core.validators import validate_email as django_validate_email
from rest_framework.exceptions import ValidationError  # type:ignore


# Function to validate password
def validate_password(password):
    """
    Validating the given password based on the following criteria:
    - No leading or trailing spaces and no spaces within the password
    - At least one uppercase letter
    - At least one special character
    """
    if len(password) < 8:
        raise ValidationError("Passsword must contain minimum of 8 characters.")
    if password != password.strip():
        raise ValidationError("Password must not contain leading or trailing spaces.")
    if " " in password:
        raise ValidationError("Password must not contain spaces within.")
    if not re.search(r"[A-Z]", password):
        raise ValidationError("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        raise ValidationError("Password must contain at least one lowercase letter.")
    if not re.search(r"[@#$%^&*!_?+\-]", password):
        raise ValidationError(
            "Password must contain at least one special character (@, #, $, %, ^, &, *, !, _, ?, +, -)."
        )
    return password


# Function to validate the email
def validate_email(email):
    """
    Validates the given email
    """

    domain_name = email.split("@")[-1]
    allowed_chars_regex = r"^[a-zA-Z0-9._%+-@]+$"
    email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"

    # Mandatory field.
    if not email:
        raise ValidationError("Email address is required.")

    # character limit should be in the below range
    elif len(email) < 5 or len(email) > 64:
        raise ValidationError("Email must be between 5 and 64 characters.")

    # No Whitespace
    elif any(c.isspace() for c in email):
        raise ValidationError("Email cannot contain spaces.")

    # It will validate the domain
    elif not re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", domain_name):
        raise ValidationError("Invalid email domain.")

    # Only for Allowed Characters
    elif not re.match(allowed_chars_regex, email):
        raise ValidationError(
            "Email can only contain letters, numbers, and valid symbols like '.', '-', '_', and '@'."
        )

    # It will validate the Format of email
    elif not re.match(email_regex, email):
        raise ValidationError("Please enter a valid email address.")

    # # Already Uniqueness is checked in views.py for additional check
    # elif User.objects.filter(Q(email__iexact=email)).exists():
    #     raise ValidationError("This email address is already registered.")

    # for case sensitivity
    try:
        django_validate_email(email.lower())  # Uses Django's built-in email validator.
    except ValidationError:
        raise ValidationError("Invalid email format.")

    # If all validations pass it will return original email
    return email
