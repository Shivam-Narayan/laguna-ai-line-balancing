from django.middleware.csrf import get_token

class EnsureCSRFCookieMiddleware:
    """
    Middleware that forces Django to send the `csrftoken` cookie 
    on every response. This ensures the React frontend always has 
    the token available to send back in the X-CSRFToken header.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        get_token(request)
        return self.get_response(request)
