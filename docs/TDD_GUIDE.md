# Test-Driven Development (TDD) Guide

This guide outlines the standard workflow for implementing Test-Driven Development (TDD) in the Laguna-AI Line Balancing backend. 

TDD is a software development process where you write the **tests before you write the code**. It guarantees that our applications (like the `absenteeism` machine learning modules) remain robust against silent failures, edge-cases, and future regressions.

---

## 🚀 The TDD Workflow (Red-Green-Refactor)

TDD follows a strict 3-step cycle:

1. 🔴 **Red (Write a Failing Test):** Write a test for the exact behavior or bug fix you intend to implement. Run the test and watch it fail (since the feature doesn't exist or the bug is still present).
2. 🟢 **Green (Write the Code):** Write the *minimum* amount of code necessary to make that specific test pass. Do not over-engineer.
3. 🛠️ **Refactor:** Clean up the code. Remove duplication, optimize logic, and ensure it adheres to our architecture standards, all while keeping the test passing.

---

## 🛠️ Step-by-Step TDD Example: Fixing a Bug

Let's walk through how you would fix a bug using TDD.

### Scenario
You are assigned a bug where the `absenteeism_report` function crashes with a `KeyError` if it encounters a new factory section (e.g., "WeirdSection") that isn't in the hardcoded list of known sections.

### Step 1: Write the Failing Test (🔴 Red)
Before touching `report_service.py`, open `apps/absenteeism/tests/test_report_service.py` and write a test that intentionally passes "WeirdSection" into the system using mocks.

```python
from unittest.mock import patch, MagicMock
from django.test import TestCase
from apps.absenteeism.services.report_service import absenteeism_report

class ReportServiceTests(TestCase):

    @patch("apps.absenteeism.services.report_service.EmployeeMaster.objects")
    def test_absenteeism_report_handles_unknown_sections(self, mock_employee):
        # 1. Setup the Mock to return the problematic "WeirdSection"
        mock_employee.filter.return_value.values.return_value.annotate.return_value = [
            {"section": "Assembly", "count": 50},
            {"section": "WeirdSection", "count": 50},
        ]
        
        # 2. Execute the function
        response = absenteeism_report("ALL", "2023-01-01")
        
        # 3. Assert it handles it gracefully instead of returning a 500 server error
        self.assertEqual(response.status_code, 200)
```

**Run the test:**
```bash
pytest apps/absenteeism/tests/test_report_service.py
```
*Result: The test fails with a `KeyError` (500 Server Error). Perfect! We have successfully reproduced the bug in a controlled test environment.*

### Step 2: Write the Fix (🟢 Green)
Now, go into `apps/absenteeism/services/report_service.py` and implement the safety check to prevent the `KeyError`.

```python
# Old code (Vulnerable):
# count = total_employee_count[item["section"]]

# New code (Safe):
count = total_employee_count.get(item["section"], 0)
```

**Run the test again:**
```bash
pytest apps/absenteeism/tests/test_report_service.py
```
*Result: The test passes (`200 OK`)! The bug is officially fixed.*

### Step 3: Refactor (🛠️)
Look at the code you just wrote. Can it be cleaner? Is there a risk of a `ZeroDivisionError` now if `count` is 0? 

You refactor the code to ensure safety:
```python
count = total_employee_count.get(item["section"], 0)
if count > 0:
    percentage = round((item["count"] / count * 100), 1)
else:
    percentage = 0
```
Run the test one last time to ensure your refactoring didn't break anything. 

---

## 🎭 Mocking Heavy Dependencies

In Domain-Driven Design, services often do heavy lifting (Pandas data transformations, Machine Learning model training, or external API calls). **We do not want our unit tests to execute this heavy logic**, as it will make the CI/CD pipeline unacceptably slow.

Instead, we use `unittest.mock.patch` to bypass them.

### Example: Mocking Machine Learning (`joblib`)
If your function trains and saves a model, intercept `joblib.dump` so it doesn't write real `.pkl` files during tests.

```python
from unittest.mock import patch
from django.test import TestCase
from apps.absenteeism.services.prediction_service import train_dynamic_model, MODEL_PATH

class PredictionServiceTests(TestCase):
    
    # Patch joblib.dump directly where it is imported in the service
    @patch("apps.absenteeism.services.prediction_service.joblib.dump")
    def test_model_saves_to_correct_path(self, mock_dump):
        # ... setup dummy dataframe ...
        
        # Run function
        train_dynamic_model(dummy_df)
        
        # Verify joblib.dump was called with our secure absolute MODEL_PATH
        mock_dump.assert_called_with(mock_dump.call_args[0][0], MODEL_PATH)
```

---

## ✅ TDD Best Practices for Laguna Developers

1. **Test Boundaries, Not Implementation:** Test what a function returns or the side-effects it guarantees, rather than testing *how* it gets there. If you rewrite the internal logic later, the test should still pass.
2. **Never Make Network Calls:** Use `@patch` to intercept requests to RockHR, Optafloor, or Weather APIs. Your tests should run offline instantly.
3. **One Assertion per Test:** While not a strict rule, keeping tests small and focused on a single assertion (or a small set of related assertions) makes it much easier to pinpoint what broke when a test fails.
4. **Name Tests Descriptively:** A test name should explain exactly what it does. 
   - ❌ `test_report()`
   - ✅ `test_absenteeism_report_handles_unknown_sections()`
5. **Run Tests Locally Before Committing:** Run `pytest` on your specific app before pushing code to ensure you didn't accidentally break existing functionality.
