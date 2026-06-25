from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed

class CookieJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        # 1. First attempt to extract the token from the HttpOnly cookie
        raw_token = request.COOKIES.get('access_token')

        # 2. If it's not in the cookie, fallback to the standard Authorization header
        if not raw_token:
            header = self.get_header(request)
            if header is None:
                return None
            raw_token = self.get_raw_token(header)
            if raw_token is None:
                return None

        # 3. Validate the token and return the user
        try:
            validated_token = self.get_validated_token(raw_token)
            return self.get_user(validated_token), validated_token
        except Exception as e:
            raise AuthenticationFailed(f"Invalid token: {str(e)}")