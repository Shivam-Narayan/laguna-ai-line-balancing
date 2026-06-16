from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('user-management/create/', views.register_user, name='user-register'),
    path('user-management/users/', views.get_all_users, name='get_all_users'),
    path('user-management/users/<int:user_id>/', views.get_user_by_id, name='get_user_by_id'),
    path('user-management/users/update/<int:user_id>/', views.update_user, name='update_user'),
    path('user-management/users/delete/<int:user_id>/', views.delete_user, name='delete_user'),
    path('location-validator/', views.check_geofence, name='location_validator'),
    path('login/', views.login, name='login'),
    path('logout/', views.logout, name='logout'),
    path('request-reset-password/', views.request_password_reset, name='request_reset_password'),
    path('reset-password/', views.reset_password, name='reset_password' ),
    path('change-password/', views.change_password, name='change_password'),
    path('protected/', views.protected_endpoint, name='protected'),  # for testing whether the Authentication token is working or not.

    path('fetch_logs/<log_filename>', views.fetch_logs, name='fetch_logs'),  # for testing whether the Authentication token is working or not.
]