# API Endpoints Workflow Guide

The Laguna-AI API is split into four main app domains (`accounts`, `data_engine`, `absenteeism`, `manning_sheet`). While you can call endpoints individually, they are designed to be triggered in a specific sequence to achieve the final "Line Balancing" goal.

Here is how the endpoints interact in a daily factory workflow.

---

## 1. Identity & Access (Root `/`)
*Before any manager or HR rep can do anything, they must authenticate.*

* **`POST /auth/login/`**: Takes email/password and returns JWT access/refresh tokens.
* **`POST /auth/logout/`**: Blacklists the JWT token and logs the user out.
* **`POST /api/auth/google/`**: Takes a Google Access Token for SSO and returns standard JWT access/refresh tokens.
* **`POST /auth/token/refresh/`**: Refreshes an expired access token using the refresh cookie.
* **`POST /auth/password/reset/request/`**: Sends a password reset link to the user's email.
* **`POST /auth/password/reset/confirm/`**: Resets the password using the token sent via email.
* **`POST /auth/password/change/`**: Changes the password for an authenticated user.
* **`POST /locations/validate/`**: Ensures the manager clocking in is physically at the factory (Geofencing check based on latitude/longitude).
* **`POST /users/create/`**: Registers a new user.
* **`GET /users/`**: Fetches all users (Admin/Authenticated).
* **`GET /users/<user_id>/`**: Fetches a specific user's details.
* **`PUT /users/<user_id>/update/`**: Updates user details.
* **`DELETE /users/<user_id>/delete/`**: Deletes a user account (cascade deletes tokens).

---

## 2. Data Engine (`/data/`)
*The core ETL pipeline for uploading master datasets and calendars.*

* **`POST /data/holiday-calendars/upload/`**: Uploads local holiday schedules.
* **`POST /data/historical-weather/upload/`**: Uploads historical weather data required for the ML model.
* **`POST /data/attendance/upload/`**: Uploads raw attendance files.
* **`GET /data/employees/generate/`**: Generates the consolidated Employee Master record.
* **`GET /data/operators/`**: Fetches processed operator data from the Employee Master.
* **`GET /data/operators/export/csv/`**: Exports operator data as a CSV file.
* **`POST /data/operators/export/email/`**: Sends operator CSV data by email.
* **`POST /data/payable-working-days/`**: Uploads or updates payable working-days configuration.

---

## 3. Absenteeism AI & Ingestion (`/absenteeism/`)
*Ingests historical data and predicts who won't show up tomorrow.*

* **`POST /absenteeism/upload/`**: Uploads historical absenteeism CSV data for training.
* **`GET /absenteeism/preprocess/`**: Cleans and normalizes the raw CSV data into a format the Machine Learning models understand.
* **`POST /absenteeism/predictions/generate/`**: Runs the actual AI regressions (combining weather, past attendance, etc.) to train the model and generate absentee rates for the upcoming shift.
* **`GET /absenteeism/predictions/`**: Retrieves the generated predictions payload.
* **`POST /absenteeism/predictions/upload/`**: Uploads existing prediction results for later retrieval.
* **`GET /absenteeism/forecasts/`**: Retrieves absenteeism forecast details for analysis.
* **`GET /absenteeism/reports/today/`**: Returns a summary of exactly how many workers are expected to be missing per department for the current day.

---

## 4. The Manning Sheet Engine (`/manning-sheet/`)
*This is the final step. It combines HR API data (who works here and what are their skills) with the Absenteeism AI (who is missing today) to build the final factory line allocation.*

> [!IMPORTANT]
> **Safe Retries (Idempotency):** Heavy `POST` endpoints in this section (like `/d-day/generate/`) should be passed a unique `Idempotency-Key` header (e.g., a UUID). This ensures that if a network timeout occurs and the client retries, the server will return the cached result instead of duplicating the heavy allocation logic.

* **`POST /manning-sheet/employees/rockhr/`**: Fetches the active employee master list directly from the external RockHR API.
* **`POST /manning-sheet/emp-facts/generate/`**: Generates Employee Facts by cross-referencing active employees with their skill matrices from Optafloor.
* **`POST /manning-sheet/attendance/rockhr/`**: Fetches today's real attendance from RockHR.
* **`POST /manning-sheet/style-obs/upload/`**: Uploads the "Style OB" (the specific sequence of operations/machines needed to build today's garment).
* **`POST /manning-sheet/loading-plans/upload/`**: Uploads loading plan or OB data for the current shift.
* **`POST /manning-sheet/emp-facts/upload/`**: Uploads employee facts data manually.
* **`POST /manning-sheet/wips/upload-file/`**: Uploads WIP data for production planning.
* **`POST /manning-sheet/manning-sheets/generate/`**: Generates the core manning sheet allocation.
* **`GET /manning-sheet/manning-sheets/`**: Retrieves the current manning sheet data.
* **`GET /manning-sheet/manning-sheets/export/`**: Downloads the current manning sheet data.
* **`POST /manning-sheet/manning-sheets/d-day/generate/`**: **The Core Endpoint.** It takes the required operations, filters out the absent employees (using attendance and predictions), looks at the skill matrix of whoever is left, and automatically assigns people to machines to perfectly balance the line!
* **`GET /manning-sheet/manning-sheets/d-day/`**: Retrieves the final generated D-Day allocation sheet so the manager can view it on the floor.
* **`GET /manning-sheet/employees/unallocated/`**: Lists workers who showed up but were not assigned to the core line.
* **`GET /manning-sheet/employees/unallocated/d-day/`**: Lists workers who showed up but weren't assigned to the core line on D-Day.
* **`POST /manning-sheet/employees/allocated/`**: Updates allocated employee assignments.
* **`POST /manning-sheet/employees/on-hold/`**: Marks an employee as on hold.
* **`POST /manning-sheet/planned-leaves/upload/`**: Uploads planned leave data.
* **`POST /manning-sheet/employees/upload/`**: Uploads active employee data.
* **`GET /manning-sheet/attendance/`**: Retrieves attendance data.
* **`GET /manning-sheet/attendance/export/`**: Downloads attendance and D-Day records.
* **`GET /manning-sheet/employees/rockhr/`**: Fetches active employees from RockHR.
* **`GET /manning-sheet/notifications/`**: Retrieves user notifications.
* **`GET /manning-sheet/notifications/download/`**: Downloads notification reports.
* **`POST /manning-sheet/notifications/mark-read/`**: Marks notifications as read.
* **`POST /manning-sheet/style-obs/generate/`**: Generates the Style OB from uploaded data.
* **`POST /manning-sheet/employees/capacity/`**: Updates employee capacity allocations.
* **`POST /manning-sheet/wips/upload/`**: Uploads WIP data to the system.
* **`POST /manning-sheet/wips/bulk/`**: Uploads bulk WIP rows.

---

## The Daily Workflow Summary:
1. **Morning (Data Sync):** HR logs in and the system fetches the latest active employees and attendance (`/manning-sheet/employees/rockhr/` & `/manning-sheet/attendance/rockhr/`).
2. **AI Processing:** The system runs the AI to calculate absence probabilities (`/absenteeism/predictions/generate/`). *(Usually handled automatically by the Celery/Scheduler service overnight).*
3. **Execution:** The manager uploads the daily load plan and clicks generate (`/manning-sheet/manning-sheets/d-day/generate/`). The algorithm spits out the perfect line balance, and the factory starts running!
