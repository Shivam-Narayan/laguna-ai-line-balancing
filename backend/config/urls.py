from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from apps.accounts.views import GoogleLoginView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("test/", lambda request: HttpResponse("Routing works"), name="test"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "swagger/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"
    ),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    # Application includes (placed after Swagger routes)
    path("", include("apps.accounts.urls")),
    path("data/", include("apps.data_engine.urls")),
    path("absenteeism/", include("apps.absenteeism.urls")),
    path("manning-sheet/", include("apps.manning_sheet.urls")),
    # SSO Authentication Routes
    path(
        "accounts/", include("allauth.urls")
    ),  # Required for socialaccount_signup reverse matching
    path("api/auth/social/", include("dj_rest_auth.registration.urls")),
    path("api/auth/google/", GoogleLoginView.as_view(), name="google_login"),
]
