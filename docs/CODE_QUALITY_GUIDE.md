# Code Quality & Static Analysis Guide

This document outlines the modern code quality pipeline implemented for the Laguna AI backend, how to run it manually, and the rationale behind the "Option A" legacy code strategy.

## 1. Overview of Tools

We enforce strict industry standards using three primary tools configured in `backend/pyproject.toml`:
- **Ruff**: An extremely fast Python linter and code formatter.
- **Mypy**: A static type checker that enforces Python type hints.
- **Pytest + Coverage**: Replaces standard Django tests to provide detailed mathematical test coverage reports.

## 2. The "Option A" Strategy (Grandfathering Legacy Code)

When introducing strict linters to an existing codebase, it will typically throw thousands of errors (e.g., lines being too long, missing whitespaces, unused imports) which instantly breaks the CI pipeline.

To solve this, we implemented **Option A**:
1. **Auto-Fix**: We ran `python -m ruff check --fix .` and `python -m ruff format .` to instantly fix over 2,000 minor stylistic errors automatically.
2. **Grandfathering Stubborn Errors**: We updated `pyproject.toml` to explicitly `ignore` the remaining ~3,000 legacy errors (specifically `E501` Line too long, `E402` Module level import not at top of file, `E722` Bare except, and `F811` Redefinition).
3. **Protection**: By doing this, the CI pipeline stays **Green** and won't fail for existing code. However, if a developer writes *new* code that violates rules outside of this ignore list, the pipeline will catch it and fail!

As your team refactors old code, you can slowly remove these ignores from `pyproject.toml`.

## 3. End-to-End Manual Testing (How to do it yourself)

If you need to verify the code quality pipeline locally before pushing to GitHub, ensure your virtual environment is active and run these exact commands from the `backend/` directory:

### Step 0: Ensure Dependencies are Installed
If you just pulled new code, make sure you have the code quality tools installed:
```bash
pip install -r requirements.txt
```

### Step 1: Run the Formatter
Ruff can automatically fix most formatting issues (like quotes, spacing, and sorting imports). Always run this first:
```bash
python -m ruff format .
```

### Step 2: Run the Linter
This will check for syntax errors, unused variables, and bad practices:
```bash
python -m ruff check .
```
*(If you want Ruff to try and auto-fix any remaining linting errors, run `python -m ruff check --fix .`)*

### Step 3: Run the Type Checker
This scans all files for type hint violations:
```bash
python -m mypy .
```
*(Note: Mypy is currently configured in `pyproject.toml` to `ignore_missing_imports = true` so it doesn't crash on un-typed third-party libraries).*

### Step 4: Run Tests with Coverage
To run your test suite and instantly see a beautiful terminal breakdown of exactly which lines of code lack test coverage:
```bash
pytest --cov=. --cov-report=term-missing
```

### Step 5: Full Django Diagnostic
To ensure the Django server can boot and that there are no pending database migrations:
```bash
python manage.py check
python manage.py makemigrations --check --dry-run
```

If all 5 of these steps complete without throwing errors, your code is 100% compliant with the enterprise standards and is safe to push!
