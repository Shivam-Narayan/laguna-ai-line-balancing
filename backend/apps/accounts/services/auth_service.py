from django.contrib.auth import get_user_model
from apps.accounts.models import MultiSessionToken

User = get_user_model()

def authenticate_user(email, password):
    """
    Authenticates a user and generates a session token.
    Returns a tuple (user_data, token, error_message, status_code).
    """
    if email is not None:
        email = email.lower()

    if not email and not password:
        return None, None, "email address and password is required", 400

    if not email:
        return None, None, "email address is required", 400

    if not password:
        return None, None, "password is required", 400

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return None, None, "No user found with this email", 404

    if not user.check_password(password):
        return None, None, "Invalid email or password", 401

    try:
        token = MultiSessionToken.objects.create(user=user)

        if user.user_type == 0:
            redirect_url = '/home'
        else:
            redirect_url = '/user-management/users'

        user_details = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'location': user.location,
            'department': user.department,
            'status': user.status,
            'user_type': user.user_type,
            'redirect_url': redirect_url,
        }

        return user_details, token.key, None, 200
    except Exception as e:
        return None, None, f'Error generating token : {str(e)}', 500

def logout_user(user, email):
    """
    Logs out a user by invalidating their tokens.
    """
    if not email:
        return "email address is required", 400

    email = email.lower()
    if email != user.email:
        return "Invalid email address provided.", 400

    MultiSessionToken.objects.filter(user=user).delete()
    return None, 200
