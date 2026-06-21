import logging
logger = logging.getLogger(__name__)

import os

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.http import FileResponse, HttpResponseNotFound, JsonResponse
from rest_framework.decorators import api_view, permission_classes, authentication_classes

from apps.accounts.models import MultiSessionToken
from apps.accounts.authentication import MultiSessionTokenAuthentication
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

User = get_user_model()


class BaseProtectedView:
    authentication_classes = [MultiSessionTokenAuthentication]
    permission_classes = [IsAuthenticated]


# Check if the user is within the geofence based on their location
@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def check_geofence(request):
    if request.method == 'POST':
        try:
            current_lat = float(request.POST.get('latitude'))
            current_lon = float(request.POST.get('longitude'))
        except Exception:
            return error_response({'status': 'Invalid Latitude and Longitude values (Float type)'}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.get(id=request.user.id)

        is_within, message, status_code = verify_geofence(user, current_lat, current_lon)

        if is_within:
            return success_response({'status': message, 'within_geofence': True})
        else:
            return error_response({'status': message, 'within_geofence': False}, status=status_code)

    return error_response({'status': 'Invalid request method.'}, status=400)


# Home view
@api_view(['GET'])
def home(request):
    return Response({
        "message": "app is running successfully"
       }
    )


# Register a new User function
@api_view(['POST'])
@permission_classes([AllowAny])
def register_user(request):
    try:
        serializer = RegisterUserSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            user_details = {
                'username': user.username,
                'email': user.email,
                'location': user.location,
                'department': user.department,
                'status': user.status,
                'send_mail': user.send_mail,
            }
            return success_response(data=user_details, message="User registered successfully", status=status.HTTP_201_CREATED)
        else:
            return error_response(error=serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    except ValidationError as e:
        # Catching validation errors explicitly
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return error_response(error="An unexpected error occurred: " + str(e), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# get all the user from db
@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def get_all_users(request):
    try:
        users = User.objects.filter(user_type=0)
        serializer = UserSerializer(users, many=True)
        return success_response(data=serializer.data, message="Fetched all the users", status=status.HTTP_200_OK)
    except Exception as e:
        return error_response(error="An unexpected error occurred: " + str(e), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# get the user from db by user_id
@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def get_user_by_id(request, user_id):
    try:
        user = User.objects.get(id=user_id)
        serializer = UserSerializer(user)
        return success_response(data=serializer.data, message="Fetched user by Id", status=status.HTTP_200_OK)
    except User.DoesNotExist:
        return error_response(error="user not found", status=status.HTTP_404_NOT_FOUND)


@api_view(['PUT'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def update_user(request, user_id):
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return error_response(error="User not found.", status=status.HTTP_404_NOT_FOUND)

    # Remove 'username' and 'created_at' from the request data if present
    if 'username' in request.data:
        request.data.pop('username')
    if 'created_at' in request.data:
        request.data.pop('created_at')

    serializer = UpdateUserSerializer(user, data=request.data)
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


# delete the user by user_id
@api_view(['DELETE'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def delete_user(request, user_id):
    user_details, error_msg, status_code = delete_user_account(user_id)
    if error_msg:
        return error_response(error=error_msg, status=status_code)
    
    return success_response(data=user_details, message=f"User with ID {user_id} deleted successfully", status=status_code)


# Login functionality
@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    email = request.data.get('email')
    password = request.data.get('password')

    user_details, token, error_msg, status_code = authenticate_user(email, password)

    if error_msg:
        return error_response(error=error_msg, status=status_code)

    response_data = {
        'Authorization': token,
        'user_details': user_details
    }

    response = success_response(
        data=response_data,
        message="Login Successful",
        status=status.HTTP_200_OK
    )

    response['Authorization'] = f"Token {token}"
    return response


@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def protected_endpoint(request):
    return success_response(
         message='You have access to this protected endpoint',
         data=request.user.username,
         status=status.HTTP_200_OK
    )


@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def logout(request):
    try:
        email = request.data.get('email')
        
        error_msg, status_code = logout_user(request.user, email)
        if error_msg:
            return error_response(error=error_msg, status=status_code)

        return success_response(
            data=request.user.email,
            message="User logged out successfully.",
            status=status.HTTP_200_OK
        )

    except Exception as e:
        return error_response(
            error=f"An error occurred while processing your request. Please try again later. Error: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([AllowAny])
def request_password_reset(request):
    serializer = RequestPasswordResetSerializer(data=request.data, context={'request': request})
    if serializer.is_valid():
        serializer.save()
        return success_response(
            data=serializer.data,
            message="Password reset link has been sent to your email",
            status=status.HTTP_200_OK
        )

    if 'email' in serializer.errors and serializer.errors['email'][0].code == 'does_not_exist':
        return error_response(
            error="Invalid or unregistered email address",
            status=status.HTTP_404_NOT_FOUND
        )

    return error_response(
        error="Email address is required",
        status=status.HTTP_400_BAD_REQUEST
    )


@api_view(['POST'])
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
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def change_password(request):
    try:
        current_password = request.data.get('current_password')
        new_password = request.data.get('new_password')
        confirm_password = request.data.get('confirm_password')

        user = User.objects.get(id=request.user.id)
        
        error_msg, status_code = change_user_password(user, current_password, new_password, confirm_password)
        if error_msg:
            return error_response(error=error_msg, status=status_code)

        return success_response(
            message="Password changed successfully",
            status=status.HTTP_200_OK
        )

    except User.DoesNotExist:
        return error_response(
            error="User not found",
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return error_response(
            error=f"An error occurred while processing your request. Please try again later. Error: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["GET", "POST"])
@authentication_classes([MultiSessionTokenAuthentication])  # Add authentication if required
@permission_classes([IsAuthenticated])  # Remove if you want it public
def fetch_logs(request, log_filename):
    """
    API to fetch log files.
    Usage: GET /fetch_logs/<log_filename>/ will fetch the file contents
    Usage: POST /fetch_logs/<log_filename>/ will clear the file contents
    """
    log_path = os.path.join(LOGS_DIR, f"{log_filename}.log")

    if request.method == 'POST':
        with open(log_path, "w") as log_file:
            log_file.truncate(0)  # Empty the file without deleting it
        return JsonResponse({"message": f"{log_filename}.log has been cleared successfully."})

    if not os.path.exists(log_path):
        return HttpResponseNotFound("Log file not found")

    return FileResponse(open(log_path, "rb"), content_type="text/plain")
