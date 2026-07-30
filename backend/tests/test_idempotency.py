import json
from django.test import SimpleTestCase, override_settings
from django.core.cache import cache
from django.http import JsonResponse
from rest_framework.test import APIRequestFactory
from config.idempotency import idempotent

# A dummy view to test the decorator
@idempotent(timeout=300)
def dummy_view(request):
    # This simulates a heavy operation that should only run once
    request.run_count = getattr(request, 'run_count', 0) + 1
    return JsonResponse({"status": "success", "run_count": request.run_count})

@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class IdempotencyTests(SimpleTestCase):
    def setUp(self):
        # Clear the local memory cache before each test
        cache.clear()

    def test_idempotency_first_request(self):
        factory = APIRequestFactory()
        # HTTP headers in Django test client have HTTP_ prefix and are uppercase
        request = factory.post('/dummy/', HTTP_IDEMPOTENCY_KEY='key123')
        request.run_count = 0
        
        response = dummy_view(request)
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["run_count"], 1)
        
        # Check if the response is cached
        cached_response = cache.get("idemp_key123")
        self.assertIsNotNone(cached_response)
        self.assertEqual(cached_response.status_code, 200)

    def test_idempotency_duplicate_request(self):
        factory = APIRequestFactory()
        
        # First request
        request1 = factory.post('/dummy/', HTTP_IDEMPOTENCY_KEY='key-duplicate')
        request1.run_count = 0
        response1 = dummy_view(request1)
        
        # Second request with the same idempotency key
        request2 = factory.post('/dummy/', HTTP_IDEMPOTENCY_KEY='key-duplicate')
        request2.run_count = 0
        response2 = dummy_view(request2)
        
        # The view should NOT have run the second time, so run_count in response should still be 1
        data1 = json.loads(response1.content)
        data2 = json.loads(response2.content)
        
        self.assertEqual(data1["run_count"], 1)
        self.assertEqual(data2["run_count"], 1)
        
        # The request2 object itself should not have been mutated
        self.assertEqual(request2.run_count, 0)

    def test_idempotency_missing_key(self):
        factory = APIRequestFactory()
        request = factory.post('/dummy/') # No key provided
        request.run_count = 0
        
        response = dummy_view(request)
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["run_count"], 1)
        
        # Another request without key should run the view again
        request2 = factory.post('/dummy/')
        request2.run_count = getattr(request, 'run_count') # Pass the run count along
        response2 = dummy_view(request2)
        
        data2 = json.loads(response2.content)
        self.assertEqual(data2["run_count"], 2) # View ran again because no key was provided
