from rest_framework.exceptions import AuthenticationFailed
from rest_framework.authentication import TokenAuthentication

from .models import MultiSessionToken

class MultiSessionTokenAuthentication(TokenAuthentication):
    model = MultiSessionToken  # Using the custom model

    def authenticate(self, request):
        token_key = request.headers.get('Authorization', '').split(' ')[-1]  # Extract token from headers

        if not token_key:
            return None

        try:
            token = MultiSessionToken.objects.get(key=token_key)

            # Check if token has expired
            if token.is_expired():
                token.refresh_token()  # Refresh token if expired

            return (token.user, token)

        except MultiSessionToken.DoesNotExist:
            raise AuthenticationFailed('Invalid token')