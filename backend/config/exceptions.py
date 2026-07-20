import logging
from rest_framework.views import exception_handler
from rest_framework.response import Response
from django.core.exceptions import PermissionDenied
from django.http import Http404

logger = logging.getLogger(__name__)

def custom_exception_handler(exc, context):
    """
    Custom exception handler for Django Rest Framework that ensures all 
    uncaught exceptions return a JSON response instead of a Django HTML page.
    """
    # Call REST framework's default exception handler first to get the standard error response.
    response = exception_handler(exc, context)

    # If the exception is not handled by DRF (e.g., standard Python exceptions like ValueError, AttributeError)
    # response will be None. We need to handle it ourselves to ensure a JSON output.
    if response is None:
        if isinstance(exc, Http404):
            data = {'error': 'Not found.'}
            return Response(data, status=404)
        
        if isinstance(exc, PermissionDenied):
            data = {'error': 'Permission denied.'}
            return Response(data, status=403)
        
        # Log the unhandled exception
        logger.error(f"Unhandled Exception: {str(exc)}", exc_info=exc)
        
        # Any other uncaught exception is a 500
        data = {
            'error': 'Internal Server Error',
            'details': str(exc)
        }
        return Response(data, status=500)

    return response
