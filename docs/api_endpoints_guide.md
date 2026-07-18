# API Endpoints Workflow Guide

The Laguna-AI API is split into four main app domains (`accounts`, `data_engine`, `absenteeism`, `manning_sheet`). While you can call endpoints individually, they are designed to be triggered in a specific sequence to achieve the final "Line Balancing" goal.

Here is how the endpoints interact in a daily factory workflow.

---

## 1. Identity & Access (Root `/`)
*Before any manager or HR rep can do anything, they must authenticate.*

* **`POST /auth/login/`**: Takes email/password and returns JWT access/refresh tokens.
* **`POST /api/auth/google/`**: Takes a Google Access Token for SSO and returns standard JWT access/refresh tokens.
* **`POST /auth/token/refresh/`**: Refreshes an expired access token.
* **`POST /locations/validate/`**: Ensures the manager clocking in is physically at the factory (Geofencing check based on latitude/longitude).
* **`POST /users/create/`**: Registers a new user.

---

## 2. Data Engine (`/data/`)
*The core ETL pipeline for uploading master datasets and calendars.*

* **`POST /data/holiday-calendars/upload/`**: Uploads local holiday schedules.
* **`POST /data/historical-weather/upload/`**: Uploads historical weather data required for the ML model.
* **`POST /data/attendance/upload/`**: Uploads raw attendance files.
* **`GET /data/employees/generate/`**: Generates the consolidated Employee Master record.

---

## 3. Absenteeism AI & Ingestion (`/absenteeism/`)
*Ingests historical data and predicts who won't show up tomorrow.*

* **`POST /absenteeism/upload/`**: Uploads historical absenteeism CSV data for training.
* **`GET /absenteeism/preprocess/`**: Cleans and normalizes the raw CSV data into a format the Machine Learning models understand.
* **`POST /absenteeism/predictions/generate/`**: Runs the actual AI regressions (combining weather, past attendance, etc.) to train the model and generate absentee rates for the upcoming shift.
* **`GET /absenteeism/predictions/`**: Retrieves the generated predictions payload.
* **`GET /absenteeism/reports/today/`**: Returns a summary of exactly how many workers are expected to be missing per department for the current day.

---

## 4. The Manning Sheet Engine (`/manning-sheet/`)
*This is the final step. It combines HR API data (who works here and what are their skills) with the Absenteeism AI (who is missing today) to build the final factory line allocation.*

* **`POST /manning-sheet/employees/rockhr/`**: Fetches the active employee master list directly from the external RockHR API.
* **`POST /manning-sheet/emp-facts/generate/`**: Generates Employee Facts by cross-referencing active employees with their skill matrices from Optafloor.
* **`POST /manning-sheet/attendance/rockhr/`**: Fetches today's real attendance from RockHR.
* **`POST /manning-sheet/style-obs/upload/`**: Uploads the "Style OB" (the specific sequence of operations/machines needed to build today's garment).
* **`POST /manning-sheet/manning-sheets/d-day/generate/`**: **The Core Endpoint.** It takes the required operations, filters out the absent employees (using attendance and predictions), looks at the skill matrix of whoever is left, and automatically assigns people to machines to perfectly balance the line!
* **`GET /manning-sheet/manning-sheets/d-day/`**: Retrieves the final generated D-Day allocation sheet so the manager can view it on the floor.
* **`GET /manning-sheet/employees/unallocated/d-day/`**: Lists workers who showed up but weren't assigned to the core line by the algorithm, allowing the manager to assign them to side tasks.

---

## The Daily Workflow Summary:
1. **Morning (Data Sync):** HR logs in and the system fetches the latest active employees and attendance (`/manning-sheet/employees/rockhr/` & `/manning-sheet/attendance/rockhr/`).
2. **AI Processing:** The system runs the AI to calculate absence probabilities (`/absenteeism/predictions/generate/`). *(Usually handled automatically by the Celery/Scheduler service overnight).*
3. **Execution:** The manager uploads the daily load plan and clicks generate (`/manning-sheet/manning-sheets/d-day/generate/`). The algorithm spits out the perfect line balance, and the factory starts running!
