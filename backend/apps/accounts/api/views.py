import logging
import os
import pathlib

from django.conf import settings
from rest_framework import status, serializers
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.http import FileResponse, HttpResponseNotFound, JsonResponse
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import MultiSessionToken
from apps.accounts.api.authentication import CookieJWTAuthentication
from apps.accounts.utils.response_handlers import success_response, error_response
from apps.accounts.api.serializers import (
    UserSerializer,
    RegisterUserSerializer,
    UpdateUserSerializer,
    RequestPasswordResetSerializer,
    ResetPasswordSerializer,
)

# Services
from apps.accounts.services.auth_service import authenticate_user, logout_user
from apps.accounts.services.user_service import change_user_password, delete_user_account
from apps.accounts.services.location_service import verify_geofence

# Path to logs directory
LOGS_DIR = os.path.join(settings.BASE_DIR, "logs")

logger = logging.getLogger(__name__)
User = get_user_model()


# Check if the user is within the geofence based on their location
@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def check_geofence(request):
    try:
        current_lat = float(request.POST.get('latitude'))
        current_lon = float(request.POST.get('longitude'))
    except (TypeError, ValueError):
        return error_response(
            {'status': 'Invalid Latitude and Longitude values (Float type)'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Use request.user directly — no need for an extra DB query
    is_within, message, status_code = verify_geofence(request.user, current_lat, current_lon)

    if is_within:
        return success_response({'status': message, 'within_geofence': True})
    return error_response({'status': message, 'within_geofence': False}, status=status_code)


# Home view
@api_view(['GET'])
def home(request):
    return Response({
        "message": "app is running successfully"
    })


# Register a new User function
@extend_schema(request=RegisterUserSerializer)
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def register_user(request):
    try:
        serializer = RegisterUserSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            user_details = {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'location': user.location,
                'department': user.department,
                'status': user.status,
                'send_mail': user.send_mail,
            }
            return success_response(data=user_details, message="User registered successfully", status=status.HTTP_201_CREATED)
        return error_response(error=serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except ValidationError as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.exception("Unexpected error during register_user")
        return error_response(error="An unexpected error occurred.", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Get all users from db (non-admin users)
@api_view(['GET'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_all_users(request):
    try:
        users = User.objects.filter(user_type=0)
        serializer = UserSerializer(users, many=True)
        return success_response(data=serializer.data, message="Fetched all the users", status=status.HTTP_200_OK)
    except Exception as e:
        logger.exception("Unexpected error during get_all_users")
        return error_response(error="An unexpected error occurred.", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Get a user from db by user_id
@api_view(['GET'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_user_by_id(request, user_id):
    try:
        user = User.objects.get(id=user_id)
        serializer = UserSerializer(user)
        return success_response(data=serializer.data, message="Fetched user by Id", status=status.HTTP_200_OK)
    except User.DoesNotExist:
        return error_response(error="User not found", status=status.HTTP_404_NOT_FOUND)


@api_view(['PUT'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def update_user(request, user_id):
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return error_response(error="User not found.", status=status.HTTP_404_NOT_FOUND)

    # Copy request.data to avoid mutating the immutable QueryDict
    mutable_data = request.data.copy()
    mutable_data.pop('username', None)
    mutable_data.pop('created_at', None)

    serializer = UpdateUserSerializer(user, data=mutable_data)
    if serializer.is_valid():
        updated_user = serializer.save()
        user_details = {
            'id': updated_user.id,
            'username': updated_user.username,
            'email': updated_user.email,
            'location': updated_user.location,
            'department': updated_user.department,
            'phonenumber': updated_user.phonenumber,
            'user_type': updated_user.user_type,
            'status': updated_user.status,
        }
        return success_response(data=user_details, message="User updated successfully", status=status.HTTP_200_OK)
    return error_response(error=serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# Delete a user by user_id
@api_view(['DELETE'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def delete_user(request, user_id):
    user_details, error_msg, status_code = delete_user_account(user_id)
    if error_msg:
        return error_response(error=error_msg, status=status_code)
    return success_response(data=user_details, message=f"User with ID {user_id} deleted successfully", status=status_code)


# Login functionality
@extend_schema(
    request=inline_serializer(
        name="LoginRequest",
        fields={
            "email": serializers.EmailField(),
            "password": serializers.CharField()
        }
    )
)
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def login(request):
    email = request.data.get('email')
    password = request.data.get('password')

    user_details, access_token, refresh_token, error_msg, status_code = authenticate_user(email, password)

    if error_msg:
        logger.warning(f"Failed login attempt for email: {email} - {error_msg}")
        return error_response(error=error_msg, status=status_code)

    response_data = {
        'user_details': user_details
    }

    response = success_response(
        data=response_data,
        message="Login Successful",
        status=status.HTTP_200_OK
    )

    logger.info(f"User logged in successfully: {email}")

    cookie_samesite = 'None' if settings.IS_PRODUCTION else 'Lax'
    cookie_secure = settings.IS_PRODUCTION

    response.set_cookie(
        key='access_token',
        value=access_token,
        httponly=True,
        samesite=cookie_samesite,
        secure=cookie_secure
    )

    response.set_cookie(
        key='refresh_token',
        value=refresh_token,
        httponly=True,
        samesite=cookie_samesite,
        secure=cookie_secure
    )

    response['Authorization'] = f"Bearer {access_token}"
    return response


@api_view(['GET'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def protected_endpoint(request):
    return success_response(
        message='You have access to this protected endpoint',
        data=request.user.username,
        status=status.HTTP_200_OK
    )


@extend_schema(request=None)
@api_view(['GET', 'POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def debug_headers(request):
    # This endpoint is for development only — block in production
    if getattr(settings, 'IS_PRODUCTION', False):
        return error_response(error="Not available", status=status.HTTP_404_NOT_FOUND)

    return success_response(
        data={
            "headers": dict(request.headers),
            "body": request.data
        },
        message="Debug info",
        status=status.HTTP_200_OK
    )


@extend_schema(
    request=None,
    responses={200: inline_serializer(name="LogoutResponse", fields={"message": serializers.CharField()})}
)
@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def logout(request):
    try:
        # 1. Clear database multi-session tokens
        error_msg, _ = logout_user(request.user, request.user.email)
        if error_msg:
            logger.warning(f"Failed to clear multi-session token during logout for {request.user.email}: {error_msg}")

        # 2. Blacklist the JWT refresh token
        refresh_token = request.COOKIES.get('refresh_token')
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except Exception as e:
                logger.error(f"Failed to blacklist token: {e}")

        response = success_response(
            data=None,
            message="User logged out successfully.",
            status=status.HTTP_200_OK
        )
        response.delete_cookie('access_token')
        response.delete_cookie('refresh_token')
        return response

    except Exception as e:
        logger.exception("An error occurred during logout")
        return error_response(
            error="An unexpected error occurred. Please try again later.",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def request_password_reset(request):
    serializer = RequestPasswordResetSerializer(data=request.data, context={'request': request})
    if serializer.is_valid():
        serializer.save()
        return success_response(
            data=serializer.data,
            message="If this email is registered, a password reset link has been sent.",
            status=status.HTTP_200_OK
        )

    return error_response(
        error="A valid email address is required.",
        status=status.HTTP_400_BAD_REQUEST
    )


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def reset_password(request):
    serializer = ResetPasswordSerializer(data=request.data)
    if serializer.is_valid():
        data = serializer.save()
        return success_response(
            data=data,
            message="Password has been reset successfully",
            status=status.HTTP_200_OK
        )
    return error_response(
        error=serializer.errors,
        status=status.HTTP_400_BAD_REQUEST
    )


@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def change_password(request):
    try:
        current_password = request.data.get('current_password')
        new_password = request.data.get('new_password')
        confirm_password = request.data.get('confirm_password')

        # Use request.user directly — already authenticated, no extra DB hit needed
        error_msg, status_code = change_user_password(request.user, current_password, new_password, confirm_password)
        if error_msg:
            return error_response(error=error_msg, status=status_code)

        return success_response(
            message="Password changed successfully",
            status=status.HTTP_200_OK
        )

    except Exception as e:
        logger.exception("Unexpected error during change_password")
        return error_response(
            error="An error occurred while processing your request. Please try again later.",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["GET", "POST"])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def fetch_logs(request, log_filename):
    """
    API to fetch or clear log files.
    GET  /fetch_logs/<log_filename>/ — returns the log file contents
    POST /fetch_logs/<log_filename>/ — clears the log file contents
    """
    # Sanitize filename: strip directory components to prevent path traversal
    safe_name = pathlib.Path(log_filename).name
    log_path = os.path.join(LOGS_DIR, f"{safe_name}.log")

    # Double-check the resolved path is still inside LOGS_DIR
    if not os.path.realpath(log_path).startswith(os.path.realpath(LOGS_DIR)):
        return error_response(error="Invalid log filename.", status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'POST':
        if not os.path.exists(log_path):
            return error_response(error="Log file not found.", status=status.HTTP_404_NOT_FOUND)
        with open(log_path, "w") as log_file:
            log_file.truncate(0)
        return JsonResponse({"message": f"{safe_name}.log has been cleared successfully."})

    if not os.path.exists(log_path):
        return HttpResponseNotFound("Log file not found")

    return FileResponse(open(log_path, "rb"), content_type="text/plain")
