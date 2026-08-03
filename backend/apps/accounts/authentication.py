from typing import Any, Optional, Tuple

from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import Token
from rest_framework.authentication import CSRFCheck
from rest_framework import exceptions

import logging

logger = logging.getLogger(__name__)


class CookieJWTAuthentication(JWTAuthentication):
    """
    Custom JWT authentication that reads the token from an HttpOnly cookie first,
    then falls back to the standard Authorization header.
    Enforces CSRF protection if the token is extracted from a cookie.
    """

    def _check_csrf(self, request: Request) -> Optional[str]:
        """
        Check CSRF validation for cookie-based authentication.
        Returns the failure reason string if CSRF fails, or None if it passes.
        """
        check = CSRFCheck(get_response=lambda req: None)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        return reason

    def authenticate(self, request: Request) -> Optional[Tuple[Any, Token]]:
        # 1. Check the standard Authorization header FIRST
        header = self.get_header(request)
        logger.error(f"Auth Header: {header}")
        if header is not None:
            raw_token = self.get_raw_token(header)
            logger.error(f"Raw Token from Header: {raw_token}")
            is_cookie = False
        else:
            # 2. Fall back to the HttpOnly cookie
            raw_token = request.COOKIES.get("access_token")
            logger.error(f"Raw Token from Cookie: {raw_token is not None}")
            is_cookie = True

        if raw_token is None:
            logger.error("No raw token found. Returning None.")
            return None

        # 3. Validate the token and return (user, token)
        try:
            validated_token = self.get_validated_token(raw_token)
            
            # 4. Enforce CSRF if the token came from the browser cookie
            if is_cookie:
                csrf_reason = self._check_csrf(request)
                if csrf_reason:
                    logger.error(
                        "CSRF check failed for cookie auth on %s: %s",
                        request.path,
                        csrf_reason,
                    )
                    return None

            return self.get_user(validated_token), validated_token
        except Exception as e:
            logger.error(f"Token validation failed: {str(e)}")
            return None
