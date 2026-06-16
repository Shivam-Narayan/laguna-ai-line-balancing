import logging

from django.conf import settings
from urllib.parse import urlparse
from django.http import JsonResponse

from apps.dataEngine.urls import dataEngine_endpoints
from apps.absenteeism.urls import absenteeism_endpoints
from apps.manning_sheet.urls import manning_sheet_endpoints


CORS_ALLOWED_ORIGINS = settings.CORS_ALLOWED_ORIGINS
ALLOWED_HOSTS = settings.ALLOWED_HOSTS


logger = logging.getLogger('middleware')

class RequestFilterMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

        # List of allowed frontend origins
        self.allowed_origins = [origin.rstrip('/') for origin in (settings.CORS_ALLOWED_ORIGINS + settings.ALLOWED_HOSTS)]
        self.allowed_methods = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']

    def __call__(self, request):
        origin = request.headers.get('Origin') or request.META.get('HTTP_REFERER', '')
        origin = origin.rstrip('/')
        # Log method and path
        logger.info(f"Incoming {request.method} request at path: {request.path} from origin: {origin}")

        # Check HTTP method
        if request.method not in self.allowed_methods:
            logger.warning(f"Blocked method: {request.method}")
            return JsonResponse({'error': 'Method not allowed'}, status=405)
        
        # Allow requests from Postman or curl (no origin header)
        if origin:
            parsed_origin = urlparse(origin)
            origin_host = parsed_origin.hostname
            if origin_host and not any(origin_host == allowed or origin.startswith(allowed) for allowed in self.allowed_origins):
                logger.warning(f"Blocked origin: {origin}")
                return JsonResponse({'error': 'Request from disallowed origin'}, status=403)
            
         # Allow only specified routes
        allowed_endpoints = accounts_endpoints + dataEngine_endpoints + absenteeism_endpoints + manning_sheet_endpoints
        if not any(
            request.path == endpoint or (endpoint != '/' and request.path.startswith(endpoint))
            for endpoint in allowed_endpoints
        ):
            logger.warning(f"Blocked unknown path: {request.path}")
            return JsonResponse({'error': 'Unknown request path'}, status=404)

        response = self.get_response(request)
        return response
    

# List of accounts app endpoints
accounts_endpoints = [
    '/',  # home/health
    '/user-management/create/',
    '/user-management/users/',
    '/user-management/users/update/',
    '/user-management/users/delete/',
    '/location-validator/',
    '/login/',
    '/logout/',
    '/request-reset-password/',
    '/reset-password/',
    '/change-password/',
    '/protected/',
    '/fetch_logs/',
    # API documentation & admin endpoints
    '/admin/',
    '/api/schema/',
    '/api/schema/swagger-ui/',
    '/api/schema/redoc/',
    '/swagger/',
    '/swagger-ui/',
    '/test/',
]