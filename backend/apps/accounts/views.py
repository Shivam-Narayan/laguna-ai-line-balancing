import logging
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import FileResponse, HttpResponseNotFound, JsonResponse
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from dj_rest_auth.registration.views import SocialLoginView

from apps.accounts.authentication import CookieJWTAuthentication
from apps.accounts.serializers import (
    RegisterUserSerializer,
)

# Services
from apps.accounts.services.auth_service import (
    authenticate_user,
    logout_user,
    request_password_reset_email,
    reset_user_password,
)
from apps.accounts.services.location_service import verify_geofence
from apps.accounts.services.log_service import clear_log_file, get_log_file_path
from apps.accounts.services.user_service import (
    change_user_password,
    delete_user_account,
    register_new_user,
    update_user_details,
)
from apps.accounts.services.user_service import get_all_users as get_all_users_service
from apps.accounts.services.user_service import get_user_by_id as get_user_by_id_service
from apps.accounts.utils.response_handlers import error_response, success_response

# Path to logs directory
LOGS_DIR = os.path.join(settings.BASE_DIR, "logs")

logger = logging.getLogger(__name__)
User = get_user_model()


# Check if the user is within the geofence based on their location
@api_view(["POST"])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def check_geofence(request):
    try:
        current_lat = float(request.data.get("latitude"))
        current_lon = float(request.data.get("longitude"))
    except (TypeError, ValueError):
        return error_response(
            {"status": "Invalid Latitude and Longitude values (Float type)"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Use request.user directly — no need for an extra DB query
    is_within, message, status_code = verify_geofence(
        request.user, current_lat, current_lon
    )

    if is_within:
        return success_response({"status": message, "within_geofence": True})
    return error_response(
        {"status": message, "within_geofence": False}, status=status_code
    )


# Home view
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def home(request):
    return Response({"message": "app is running successfully"})


# Register a new User function
@extend_schema(request=RegisterUserSerializer)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def register_user(request):
    user_details, error_msg, status_code = register_new_user(request.data)
    if error_msg:
        return error_response(error=error_msg, status=status_code)
    return success_response(
        data=user_details, message="User registered successfully", status=status_code
    )


# Get all users from db (non-admin users)
@api_view(["GET"])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_all_users(request):
    data, error_msg, status_code = get_all_users_service()
    if error_msg:
        return error_response(error=error_msg, status=status_code)
    return success_response(
        data=data, message="Fetched all the users", status=status_code
    )


# Get a user from db by user_id
@api_view(["GET"])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_user_by_id(request, user_id):
    data, error_msg, status_code = get_user_by_id_service(user_id)
    if error_msg:
        return error_response(error=error_msg, status=status_code)
    return success_response(data=data, message="Fetched user by Id", status=status_code)


@api_view(["PUT"])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def update_user(request, user_id):
    if str(request.user.id) != str(user_id) and not request.user.is_superuser:
        return error_response(
            error="You do not have permission to perform this action.",
            status=status.HTTP_403_FORBIDDEN,
        )

    # Copy request.data to avoid mutating the immutable QueryDict
    mutable_data = request.data.copy()
    mutable_data.pop("username", None)
    mutable_data.pop("created_at", None)

    user_details, error_msg, status_code = update_user_details(user_id, mutable_data)
    if error_msg:
        return error_response(error=error_msg, status=status_code)
    return success_response(
        data=user_details, message="User updated successfully", status=status_code
    )


# Delete a user by user_id
@api_view(["DELETE"])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def delete_user(request, user_id):
    if str(request.user.id) != str(user_id) and not request.user.is_superuser:
        return error_response(
            error="You do not have permission to perform this action.",
            status=status.HTTP_403_FORBIDDEN,
        )

    user_details, error_msg, status_code = delete_user_account(user_id)
    if error_msg:
        return error_response(error=error_msg, status=status_code)
    return success_response(
        data=user_details,
        message=f"User with ID {user_id} deleted successfully",
        status=status_code,
    )


class LoginThrottle(UserRateThrottle):
    scope = 'login_attempts'


# Login functionality
@extend_schema(
    request=inline_serializer(
        name="LoginRequest",
        fields={"email": serializers.EmailField(), "password": serializers.CharField()},
    )
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def login(request):
    email = request.data.get("email")
    password = request.data.get("password")

    user_details, access_token, refresh_token, error_msg, status_code = (
        authenticate_user(email, password)
    )

    if error_msg:
        logger.warning(f"Failed login attempt for email: {email} - {error_msg}")
        return error_response(error=error_msg, status=status_code)

    response_data = {
        "user_details": user_details,
        "access_token": access_token
    }

    response = success_response(
        data=response_data, message="Login Successful", status=status.HTTP_200_OK
    )

    logger.info(f"User logged in successfully: {email}")

    is_production = getattr(settings, "IS_PRODUCTION", False)
    cookie_samesite = "None" if is_production else "Lax"
    cookie_secure = is_production

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite=cookie_samesite,
        secure=cookie_secure,
    )

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite=cookie_samesite,
        secure=cookie_secure,
    )

    response["Authorization"] = f"Bearer {access_token}"
    return response


@api_view(["GET"])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def protected_endpoint(request):
    return success_response(
        message="You have access to this protected endpoint",
        data=request.user.username,
        status=status.HTTP_200_OK,
    )


class CookieTokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        refresh_token = request.COOKIES.get("refresh_token")

        if refresh_token and "refresh" not in request.data:
            # Make data mutable if it is a QueryDict
            if hasattr(request.data, "_mutable"):
                request.data._mutable = True
                request.data["refresh"] = refresh_token
                request.data._mutable = False
            else:
                try:
                    request.data["refresh"] = refresh_token
                except TypeError:
                    # In case request.data is somehow a tuple or immutable list
                    pass

        response = super().post(request, *args, **kwargs)

        if response.status_code == 200:
            access_token = response.data.get("access")
            new_refresh_token = response.data.get("refresh")

            cookie_samesite = (
                "None" if getattr(settings, "IS_PRODUCTION", False) else "Lax"
            )
            cookie_secure = getattr(settings, "IS_PRODUCTION", False)

            if access_token:
                response.set_cookie(
                    key="access_token",
                    value=access_token,
                    httponly=True,
                    samesite=cookie_samesite,
                    secure=cookie_secure,
                )
            if new_refresh_token:
                response.set_cookie(
                    key="refresh_token",
                    value=new_refresh_token,
                    httponly=True,
                    samesite=cookie_samesite,
                    secure=cookie_secure,
                )
        return response


@extend_schema(request=None)
@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def debug_headers(request):
    # This endpoint is for development only — block in production
    if getattr(settings, "IS_PRODUCTION", False):
        return error_response(error="Not available", status=status.HTTP_404_NOT_FOUND)

    return success_response(
        data={"headers": dict(request.headers), "body": request.data},
        message="Debug info",
        status=status.HTTP_200_OK,
    )


@extend_schema(
    request=None,
    responses={
        200: inline_serializer(
            name="LogoutResponse", fields={"message": serializers.CharField()}
        )
    },
)
@api_view(["POST"])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def logout(request):
    try:
        # 1. Clear database multi-session tokens
        error_msg, _ = logout_user(request.user, request.user.email)
        if error_msg:
            logger.warning(
                f"Failed to clear multi-session token during logout for {request.user.email}: {error_msg}"
            )

        # 2. Blacklist the JWT refresh token
        refresh_token = request.COOKIES.get("refresh_token")
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except Exception as e:
                logger.error(f"Failed to blacklist token: {e}")

        response = success_response(
            data=None,
            message="User logged out successfully.",
            status=status.HTTP_200_OK,
        )
        response.delete_cookie("access_token")
        response.delete_cookie("refresh_token")
        return response

    except Exception:
        logger.exception("An error occurred during logout")
        return error_response(
            error="An unexpected error occurred. Please try again later.",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def request_password_reset(request):
    data, error_msg, status_code = request_password_reset_email(request.data)
    if error_msg:
        return error_response(error=error_msg, status=status_code)
    return success_response(
        data=data,
        message="If this email is registered, a password reset link has been sent.",
        status=status_code,
    )


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def reset_password(request):
    data, error_msg, status_code = reset_user_password(request.data)
    if error_msg:
        return error_response(error=error_msg, status=status_code)
    return success_response(
        data=data, message="Password has been reset successfully", status=status_code
    )


@api_view(["POST"])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def change_password(request):
    try:
        current_password = request.data.get("current_password")
        new_password = request.data.get("new_password")
        confirm_password = request.data.get("confirm_password")

        # Use request.user directly — already authenticated, no extra DB hit needed
        error_msg, status_code = change_user_password(
            request.user, current_password, new_password, confirm_password
        )
        if error_msg:
            return error_response(error=error_msg, status=status_code)

        return success_response(
            message="Password changed successfully", status=status.HTTP_200_OK
        )

    except Exception:
        logger.exception("Unexpected error during change_password")
        return error_response(
            error="An error occurred while processing your request. Please try again later.",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET", "POST"])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAdminUser])
def fetch_logs(request, log_filename):
    """
    API to fetch or clear log files.
    GET  /fetch_logs/<log_filename>/ — returns the log file contents
    POST /fetch_logs/<log_filename>/ — clears the log file contents
    """
    if request.method == "POST":
        message, error_msg, status_code = clear_log_file(log_filename)
        if error_msg:
            return error_response(error=error_msg, status=status_code)
        return JsonResponse({"message": message})

    log_path, error_msg, status_code = get_log_file_path(log_filename)
    if error_msg:
        if status_code == 404:
            return HttpResponseNotFound(error_msg)
        return error_response(error=error_msg, status=status_code)

    return FileResponse(open(log_path, "rb"), content_type="text/plain")


class GoogleLoginView(SocialLoginView):
    authentication_classes = []
    permission_classes = [AllowAny]
    adapter_class = GoogleOAuth2Adapter
    client_class = OAuth2Client
    # The callback URL must match exactly what is registered in Google Cloud Console
    # The frontend is responsible for passing the token here, but the adapter needs a callback URL.
    callback_url = (
        getattr(settings, "DEV_FRONTED_URL", "http://localhost:5173")
        + "/auth/callback/google"
    )

