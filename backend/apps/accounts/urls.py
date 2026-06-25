from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('users/', views.get_all_users, name='get_all_users'),
    path('users/create/', views.register_user, name='user-register'),
    path('users/<uuid:user_id>/', views.get_user_by_id, name='get_user_by_id'),
    path('users/<uuid:user_id>/update/', views.update_user, name='update_user'),
    path('users/<uuid:user_id>/delete/', views.delete_user, name='delete_user'),
    path('locations/validate/', views.check_geofence, name='location_validator'),
    path('auth/login/', views.login, name='login'),
    path('auth/logout/', views.logout, name='logout'),
    path('auth/password/reset/request/', views.request_password_reset, name='request_reset_password'),
    path('auth/password/reset/confirm/', views.reset_password, name='reset_password' ),
    path('auth/password/change/', views.change_password, name='change_password'),
    path('test/protected/', views.protected_endpoint, name='protected'),  # for testing whether the Authentication token is working or not.

    path('logs/<str:log_filename>/', views.fetch_logs, name='fetch_logs'),  # for testing whether the Authentication token is working or not.
]