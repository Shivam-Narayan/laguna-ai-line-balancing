# Laguna AI Line Balancing - Testing Guide

This document outlines the testing architecture, how to execute tests, and best practices for future development.

## 1. Overview
The testing suite is built using Django's `TestCase` / `SimpleTestCase` frameworks and `pytest` as the test runner. The backend is split into multiple apps (`accounts`, `absenteeism`, `data_engine`, `manning_sheet`), and each app has its own dedicated `tests/` package. Infrastructure tests (circuit breakers, database routers, idempotency) live in `backend/tests/`.

### Directory Structure
```text
backend/
├── conftest.py                   # Root pytest config (sys.path & django.setup())
├── pyproject.toml                # Pytest, Ruff, Mypy configuration
├── apps/<app_name>/
│   └── tests/
│       ├── __init__.py
│       ├── test_models.py        # Unit tests for database models
│       ├── test_views.py         # Integration tests for API endpoints
│       └── test_services.py      # (Optional) Unit tests for business logic
└── tests/
    ├── conftest.py               # Shared fixtures for infrastructure tests
    ├── test_circuit_breakers.py   # pybreaker circuit breaker tests
    ├── test_db_routers.py         # Primary/Replica database router tests
    └── test_idempotency.py        # Redis idempotency decorator tests
```

### Test Configuration (`conftest.py`)
The root `backend/conftest.py` ensures that:
1. The `backend/` directory is added to `sys.path` so Python can resolve `config.settings` and `apps.*` modules.
2. `DJANGO_SETTINGS_MODULE` is set to `config.settings`.
3. `django.setup()` is called before test collection begins.

This is critical because VS Code's test explorer runs pytest from the workspace root (`c:\Projects\laguna`), not from `backend/`. Without this file, Django models fail to import during test discovery.

## 2. How to Run Tests

Ensure your virtual environment is activated before running tests.

### Run all tests in the project:
```bash
pytest
```

### Run tests for a specific app:
```bash
pytest apps/accounts/
pytest apps/absenteeism/
pytest apps/data_engine/
pytest apps/manning_sheet/
```

### Run infrastructure tests only:
```bash
pytest tests/
```

### Run a specific test file:
```bash
pytest apps/accounts/tests/test_views.py
```

### Run a specific test class or method:
```bash
pytest apps/accounts/tests/test_views.py::AuthViewTests
pytest apps/accounts/tests/test_views.py::AuthViewTests::test_login_success
```

### Run tests with coverage report:
```bash
pytest --cov=. --cov-report=term-missing
```

## 3. Testing Without External Services (Postgres, Redis)

Many tests do **not** need a real PostgreSQL database or Redis server. For these tests, we use two key Django features:

### `SimpleTestCase` (No Database Required)
Use `SimpleTestCase` instead of `TestCase` when your test doesn't touch the database:
```python
from django.test import SimpleTestCase

class MyPureFunctionTest(SimpleTestCase):
    def test_math_logic(self):
        self.assertEqual(1 + 1, 2)
```

### `@override_settings` (Swap Redis for In-Memory Cache)
Use `@override_settings` to replace the Redis cache backend with Django's built-in `LocMemCache` during tests:
```python
from django.test import SimpleTestCase, override_settings

@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class IdempotencyTests(SimpleTestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_cached_response(self):
        # This test uses in-memory cache, no Redis needed!
        ...
```

> [!TIP]
> The `test_services.py` and `test_idempotency.py` files use this pattern. They run fully green even without Postgres or Redis running locally.

> [!IMPORTANT]
> Tests that use `TestCase` (not `SimpleTestCase`) **require** a running PostgreSQL server. These tests create a temporary `test_<dbname>` database and destroy it after the test run. If Postgres is offline, these tests will fail with `OperationalError: connection refused`.

## 4. Testing Strategy

### Models (`test_models.py`)
- Focus on verifying that models can be successfully instantiated with all required fields.
- Test custom methods, properties, and the `__str__` representations.
- **Important:** Ensure foreign keys and constraints (like `unique_together`) are respected.

### Views (`test_views.py`)
- **Authentication:** Most endpoints in this project require `CookieJWTAuthentication`. Test setups should explicitly mock a login and attach the resulting cookies to the `APIClient`.
- **Mocking Heavy Services:** Because apps like `absenteeism` and `manning_sheet` rely on heavy Pandas data transformations and machine learning orchestrators, we use `unittest.mock.patch` to mock these service functions in view tests.
  - *Example 1:* Instead of actually processing an uploaded Excel file in the view test, we mock `run_upload_absenteesim_data` to return a `200 OK` response. This isolates the test to only verify API routing, HTTP methods, and authentication.
  - *Example 2:* When testing `prediction_orchestrator.py` or `report_service.py`, we heavily mock `joblib.dump`, `RandomForestRegressor`, and internal API requests using `@patch`. This prevents expensive ML computations from slowing down the CI/CD pipeline while still guaranteeing 100% test coverage over data-extraction edge cases (like `KeyError` or `ZeroDivisionError`).

### Services (`test_services.py`)
- When testing service-level logic (e.g., `auth_service.py`), do **not** mock the logic. Test the actual Python functions by passing in dummy data or instantiated models.

### Infrastructure Tests (`backend/tests/`)
These tests verify cross-cutting production resilience modules:
- **`test_circuit_breakers.py`**: Validates that `pybreaker` correctly opens/closes circuits and that the `@fallback` decorator returns graceful error responses.
- **`test_db_routers.py`**: Validates that the `PrimaryReplicaRouter` correctly routes reads to `replica` and writes to `default`.
- **`test_idempotency.py`**: Validates that the `@idempotent` decorator caches responses and prevents duplicate processing on repeated requests.

## 5. Best Practices for Future Development

> [!TIP]
> For a step-by-step tutorial on how to fix bugs using the Red-Green-Refactor testing approach, see the **[TDD Guide](TDD_GUIDE.md)**!

1. **Test-Driven Development (TDD):** When creating a new endpoint, write the view test first (expecting it to fail), then write the view logic.
2. **Missing Required Fields:** If you add new required fields to `User` or other core models, you must update the `setUp()` methods across all test files to prevent `IntegrityError` failures during test database creation.
3. **Mocking External APIs/DBs:** Never make real network requests to external APIs (like RockHR or weather services) during tests. Always patch the function making the request.
4. **Test Database:** Django automatically creates a blank test database and destroys it after tests run. You don't need to worry about tests corrupting your local development database.
5. **Use `SimpleTestCase` when possible:** If your test doesn't need the database, prefer `SimpleTestCase` over `TestCase`. This makes tests faster and removes the Postgres dependency.
6. **Use `@override_settings` for cache-dependent tests:** If your test touches Redis-backed caching, swap it out with `LocMemCache` using `@override_settings` so tests work without a running Redis server.
