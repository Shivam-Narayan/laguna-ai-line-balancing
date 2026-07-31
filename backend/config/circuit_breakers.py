import logging
import pybreaker
from functools import wraps

logger = logging.getLogger(__name__)

class LogListener(pybreaker.CircuitBreakerListener):
    """
    Listener to log state changes in the circuit breaker.
    """
    def state_change(self, cb, old_state, new_state):
        msg = f"Circuit Breaker '{cb.name}' changed state from {old_state.name} to {new_state.name}"
        if new_state.name == 'open':
            logger.error(msg)
        else:
            logger.info(msg)

# Breaker for database-heavy operations (e.g., Reports, Manning Sheet generation)
# Fails after 5 consecutive errors, stays open for 60 seconds
db_breaker = pybreaker.CircuitBreaker(
    fail_max=5,
    reset_timeout=60,
    name="db_breaker",
    listeners=[LogListener()]
)

# Breaker for external API calls (e.g., SendGrid, Mailgun)
# Fails fast after 3 errors, stays open for 30 seconds
external_api_breaker = pybreaker.CircuitBreaker(
    fail_max=3,
    reset_timeout=30,
    name="external_api_breaker",
    listeners=[LogListener()]
)

def fallback_response(fallback_data):
    """
    Decorator to return a fallback response when a CircuitBreakerError occurs,
    preventing 500 errors and giving a graceful degradation message instead.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except pybreaker.CircuitBreakerError:
                # Log that we hit the fallback
                logger.warning(f"Circuit open on {func.__name__}, returning fallback.")
                return fallback_data
        return wrapper
    return decorator
