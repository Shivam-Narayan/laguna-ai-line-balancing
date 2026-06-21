from django.contrib.auth import get_user_model
from apps.accounts.models import MultiSessionToken

User = get_user_model()

def authenticate_user(email, password):
    """Authenticates a user and generates a session token."""
    if not email or not password:
        return None, None, "Email and password are required", 400

    try:
        user = User.objects.get(email=email.lower())
    except User.DoesNotExist:
        return None, None, "No user found with this email", 404

    if not user.check_password(password):
        return None, None, "Invalid email or password", 401

    try:
        token = MultiSessionToken.objects.create(user=user)
        user_details = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'location': user.location,
            'department': user.department,
            'status': user.status,
            'user_type': user.user_type,
            'redirect_url': '/home' if user.user_type == 0 else '/user-management/users',
        }
        return user_details, token.key, None, 200
    except Exception as e:
        return None, None, f"Error generating token: {str(e)}", 500

def logout_user(user, email):
    """Logs out a user by invalidating their tokens."""
    if not email:
        return "Email address is required", 400

    if email.lower() != user.email:
        return "Invalid email address provided.", 400

    MultiSessionToken.objects.filter(user=user).delete()
    return None, 200
