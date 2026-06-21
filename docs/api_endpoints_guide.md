# API Endpoints Workflow Guide

The Laguna-AI API is split into four distinct sections. While you can call them individually, they are designed to be triggered in a specific sequence to achieve the final "Line Balancing" goal.

Here is how the endpoints interact in a daily factory workflow.

---

## 1. Identity & Access (`/` root or `/accounts/`)
*Before any manager or HR rep can do anything, they must prove who they are.*

* **`POST /login/`**: Takes email/password and returns a `Token`.
* **`POST /location-validator/`**: Ensures the manager clocking in is physically at the factory (Geofencing check based on latitude/longitude).
* **`GET /user-management/users/`**: Retrieves the list of active factory personnel.

---

## 2. Data Ingestion (`/data/`)
*The factory produces massive amounts of Excel/CSV data. This must be uploaded to the engine first so the system knows the state of the factory.*

* **`POST /data/upload_employee_master/`**: Uploads the master list of all employees.
* **`POST /data/upload_skill_matrix/`**: Uploads exactly which employees know how to operate which machines.
* **`POST /data/upload_historical_weather/`**: Uploads past and future weather data (used by the AI to predict absences).
* **`POST /data/upload_load_plan/`**: Uploads what the factory *intends* to build today (e.g., 500 shirts).

---

## 3. Absenteeism AI (`/absenteeism/`)
*Now that the data is in the database, the AI can predict who won't show up tomorrow.*

* **`POST /absenteeism/preporcess_data/`**: Cleans and normalizes the raw CSV data into a format the Machine Learning models understand.
* **`GET /absenteeism/absenteeism_prediction/`**: Runs the actual AI regressions (combining weather, past attendance, etc.) to calculate the expected absentee rate for the upcoming shift.
* **`GET /absenteeism/get_absenteeism_forecast/`**: Returns a JSON payload showing exactly how many workers are expected to be missing per department.

---

## 4. The Manning Sheet Engine (`/manning-sheet/`)
*This is the final step. It combines the Data Engine (who works here and what are their skills) with the Absenteeism AI (who is missing today) to build the final factory line allocation.*

* **`POST /manning-sheet/uploading_styleob_data/`**: Uploads the "Style OB" (the specific sequence of operations/machines needed to build today's garment).
* **`POST /manning-sheet/generate_manning_sheet/`**: **The Core Endpoint.** It takes the required operations, filters out the absent employees, looks at the skill matrix of whoever is left, and automatically assigns people to machines to perfectly balance the line!
* **`GET /manning-sheet/get_manning_data/`**: Retrieves the final generated allocation sheet so the manager can print it out or view it on a tablet on the factory floor.
* **`GET /manning-sheet/get_unallocated_employees/`**: Lists workers who showed up but weren't strictly needed for the core line, so the manager can assign them to side tasks.

---

### The Daily Workflow Summary:
1. **Morning:** HR logs in (`/login/`) and uploads today's raw Excel sheets (`/data/upload_...`).
2. **Processing:** The system runs the AI to figure out who is missing (`/absenteeism/absenteeism_prediction/`).
3. **Execution:** The manager clicks "Generate", which fires (`/manning-sheet/generate_manning_sheet/`). The algorithm spits out the perfect line balance, and the factory starts running!
