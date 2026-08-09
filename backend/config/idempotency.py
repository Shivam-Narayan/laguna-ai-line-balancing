from functools import wraps
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse

def idempotent(timeout=300):
    """
    Decorator to make an endpoint idempotent based on an Idempotency-Key header.
    It caches the response for the given timeout.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # Only POST, PUT, PATCH are typically idempotent-protected, 
            # but we'll apply it whenever the key is present for flexibility.
            
            # Support both DRF view instances and plain Django request objects.
            meta = getattr(request, 'META', None)
            if meta is None and hasattr(request, 'request'):
                meta = getattr(request.request, 'META', {})
            if meta is None:
                meta = {}

            # Check for Idempotency-Key header
            idemp_key = meta.get('HTTP_IDEMPOTENCY_KEY')
            if not idemp_key:
                # No key provided, just run the view
                return view_func(request, *args, **kwargs)

            # Create a unique cache key
            cache_key = f"idemp_{idemp_key}"
            
            # Check if response is already cached
            cached_response = cache.get(cache_key)
            if cached_response:
                return cached_response
                
            # If not cached, we need to run the view
            # To handle race conditions, we can set a lock flag
            # (A robust implementation would use Redis setnx here, but we keep it simple for now)
            lock_key = f"idemp_lock_{idemp_key}"
            if not cache.add(lock_key, True, timeout=10):
                return JsonResponse({"error": "Concurrent request processing"}, status=409)

            try:
                # Process the request
                response = view_func(request, *args, **kwargs)
                
                # Cache the successful response
                if response.status_code in (200, 201, 202, 204):
                    cache.set(cache_key, response, timeout=timeout)
                
                return response
            finally:
                # Always release the lock
                cache.delete(lock_key)

        return _wrapped_view
    return decorator
