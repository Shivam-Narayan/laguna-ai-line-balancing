import pytest
import pybreaker
from config.circuit_breakers import db_breaker, external_api_breaker, fallback_response

def test_circuit_breaker_success():
    @db_breaker
    def successful_operation():
        return "success"

    assert successful_operation() == "success"
    assert db_breaker.current_state == "closed"

def test_circuit_breaker_failure_opens_circuit():
    @external_api_breaker
    def failing_operation():
        raise Exception("External API failed")

    # Fail the operation exactly the failure threshold (5 times)
    for _ in range(5):
        with pytest.raises(Exception):
            failing_operation()

    # The next call should raise CircuitBreakerError immediately 
    # without running the function (fail fast)
    with pytest.raises(pybreaker.CircuitBreakerError):
        failing_operation()

    assert external_api_breaker.current_state == "open"

def test_fallback_decorator():
    # If a circuit breaker is open or the operation fails, 
    # we can test a fallback mechanism.
    
    @external_api_breaker
    def broken_operation():
        raise pybreaker.CircuitBreakerError("Circuit open")

    @fallback_response({"status": "degraded", "message": "Service unavailable"})
    def resilient_endpoint():
        return broken_operation()

    response = resilient_endpoint()
    # It should catch the CircuitBreakerError and return the fallback response
    assert response["status"] == "degraded"
    assert response["message"] == "Service unavailable"
