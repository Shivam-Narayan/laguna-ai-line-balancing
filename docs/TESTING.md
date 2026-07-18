# Laguna AI Line Balancing - Testing Guide

This document outlines the testing architecture, how to execute tests, and best practices for future development.

## 1. Overview
The testing suite is built using Django's built-in `TestCase` framework. The backend is split into multiple apps (`accounts`, `absenteeism`, `data_engine`, `manning_sheet`), and each app has its own dedicated `tests/` package.

### Directory Structure
Each app contains a `tests` directory structured as follows:
```text
apps/<app_name>/
├── tests/
│   ├── __init__.py
│   ├── test_models.py    # Unit tests for database models
│   ├── test_views.py     # Integration tests for API endpoints
│   └── test_services.py  # (Optional) Unit tests for business logic
```

## 2. How to Run Tests

Ensure your virtual environment is activated before running tests.

### Run all tests in the project:
```bash
python manage.py test
```

### Run tests for a specific app:
```bash
python manage.py test apps.accounts
python manage.py test apps.absenteeism
python manage.py test apps.data_engine
python manage.py test apps.manning_sheet
```

### Run a specific test file:
```bash
python manage.py test apps.accounts.tests.test_views
```

### Run a specific test class or method:
```bash
python manage.py test apps.accounts.tests.test_views.AuthViewTests
python manage.py test apps.accounts.tests.test_views.AuthViewTests.test_login_success
```

### Run tests with increased verbosity (to see test names):
```bash
python manage.py test -v 2
```

## 3. Testing Strategy

### Models (`test_models.py`)
- Focus on verifying that models can be successfully instantiated with all required fields.
- Test custom methods, properties, and the `__str__` representations.
- **Important:** Ensure foreign keys and constraints (like `unique_together`) are respected.

### Views (`test_views.py`)
- **Authentication:** Most endpoints in this project require `CookieJWTAuthentication`. Test setups should explicitly mock a login and attach the resulting cookies to the `APIClient`.
- **Mocking Heavy Services:** Because apps like `absenteeism` and `manning_sheet` rely on heavy Pandas data transformations and machine learning orchestrators, we use `unittest.mock.patch` to mock these service functions in view tests.
  - *Example:* Instead of actually processing an uploaded Excel file in the view test, we mock `run_upload_absenteesim_data` to return a `200 OK` response. This isolates the test to only verify API routing, HTTP methods, and authentication.

### Services (`test_services.py`)
- When testing service-level logic (e.g., `auth_service.py`), do **not** mock the logic. Test the actual Python functions by passing in dummy data or instantiated models.

## 4. Best Practices for Future Development

1. **Test-Driven Development (TDD):** When creating a new endpoint, write the view test first (expecting it to fail), then write the view logic.
2. **Missing Required Fields:** If you add new required fields to `User` or other core models, you must update the `setUp()` methods across all test files to prevent `IntegrityError` failures during test database creation.
3. **Mocking External APIs/DBs:** Never make real network requests to external APIs (like RockHR or weather services) during tests. Always patch the function making the request.
4. **Test Database:** Django automatically creates a blank test database and destroys it after tests run. You don't need to worry about tests corrupting your local development database.
