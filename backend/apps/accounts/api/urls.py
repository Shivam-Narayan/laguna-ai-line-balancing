from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.api.views import (
    home,
    register_user,
    get_all_users,
    get_user_by_id,
    update_user,
    delete_user,
    login,
    logout,
    protected_endpoint,
    check_geofence,
    request_password_reset,
    reset_password,
    change_password,
    fetch_logs,
)

urlpatterns = [
    path('', home, name='home'),

    # Auth
    path('auth/login/', login, name='login'),
    path('auth/logout/', logout, name='logout'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/password/reset/request/', request_password_reset, name='request_reset_password'),
    path('auth/password/reset/confirm/', reset_password, name='reset_password'),
    path('auth/password/change/', change_password, name='change_password'),

    # Users
    path('users/', get_all_users, name='get_all_users'),
    path('users/create/', register_user, name='user-register'),
    path('users/<uuid:user_id>/', get_user_by_id, name='get_user_by_id'),
    path('users/<uuid:user_id>/update/', update_user, name='update_user'),
    path('users/<uuid:user_id>/delete/', delete_user, name='delete_user'),

    # Location
    path('locations/validate/', check_geofence, name='location_validator'),

    # Logs (authenticated)
    path('logs/<str:log_filename>/', fetch_logs, name='fetch_logs'),

    # Dev / Testing
    path('test/protected/', protected_endpoint, name='protected'),
]
