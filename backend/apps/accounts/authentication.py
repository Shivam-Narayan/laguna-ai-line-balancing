from typing import Any, Optional, Tuple

from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import Token


class CookieJWTAuthentication(JWTAuthentication):
    """
    Custom JWT authentication that reads the token from an HttpOnly cookie first,
    then falls back to the standard Authorization header.
    """

    def authenticate(self, request: Request) -> Optional[Tuple[Any, Token]]:
        # 1. Try to extract the token from the HttpOnly cookie
        raw_token = request.COOKIES.get("access_token")

        # 2. Fall back to the standard Authorization header
        if not raw_token:
            header = self.get_header(request)
            if header is None:
                return None

            raw_token = self.get_raw_token(header)
            if raw_token is None:
                return None

        # 3. Validate the token and return (user, token)
        try:
            validated_token = self.get_validated_token(raw_token)
            return self.get_user(validated_token), validated_token
        except Exception:
            # If the token is invalid or expired, return None to fall back to AnonymousUser
            # This allows AllowAny endpoints (like Swagger) to load without returning 401
            return None
