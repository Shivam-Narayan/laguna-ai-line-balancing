# 🛠️ Scripts & Automation Guide

The Laguna-AI project comes with a dedicated `scripts/` folder containing Windows Batch (`.bat`), PowerShell (`.ps1`), and Linux/Mac (`.sh`) scripts. 

These scripts serve as "wrappers" or shortcuts. Their only purpose is to take long, complex Docker and Django terminal commands and bundle them into simple, easy-to-run files. 

**You are never required to use these scripts.** They are entirely optional. If you prefer to type out raw Docker Compose commands (`docker compose up -d`), you can safely ignore this folder.

---

## 1. The Standalone Utility Scripts

For convenience, several single-purpose scripts have been separated out so you can execute them directly without needing to remember any flags.

* **`scripts\start-dev.bat`**
  * **What it does:** Starts your backend and frontend in Development Mode, mounting your local code for instant "Hot Reloading" when you save a file. It also launches developer tools like pgAdmin.
  * **Under the hood:** `docker compose -f docker-compose.yml -f docker-compose.override.yml up -d`

* **`scripts\start-prod.bat`**
  * **What it does:** Starts your app in Production Mode. Disables live-reloading, spins up the robust Gunicorn server, Celery workers, and the Nginx reverse proxy.
  * **Under the hood:** `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`

* **`scripts\build.bat`**
  * **What it does:** Forces Docker to completely rebuild your container images from scratch. You must run this if you install new packages (like modifying `requirements.txt`) or modify a `Dockerfile`.
  * **Under the hood:** `docker compose up --build -d`

* **`scripts\migrate.bat`** (Also available as `.sh` and `.ps1`)
  * **What it does:** Applies Django database migrations securely inside the running database container. Use this whenever you change `models.py`.
  * **Under the hood:** `docker compose exec backend python manage.py migrate`

* **`scripts\backup.bat`**
  * **What it does:** Generates a full `.sql` backup of your PostgreSQL database and saves it into your project folder with a timestamp.
  * **Under the hood:** `docker compose exec db pg_dump -U postgres -d Laguna > backup_YYYYMMDD.sql`

* **`scripts\restore.bat`**
  * **What it does:** Restores a database backup file into the running database. 
  * **Usage:** `scripts\restore.bat my_backup.sql`
  * **Under the hood:** `docker compose exec -T db psql -U postgres -d Laguna < my_backup.sql`

---

## 2. The Master Script (`start.bat`)

The original `start.bat` (and its `.ps1` and `.sh` equivalents) is a massive "Swiss Army Knife" script. Instead of using the individual scripts above, you can use this single script combined with **flags** to control the entire environment.

### Core Environment Commands
| Command | Description |
|---|---|
| `scripts\start.bat --dev` | Starts the development environment. |
| `scripts\start.bat --prod`| Starts the production environment. |
| `scripts\start.bat --build` | Rebuilds the images before starting. |

### Cleanup Commands
| Command | Description |
|---|---|
| `scripts\start.bat --down` | Stops and safely removes all containers. Your database data is kept safe! |
| `scripts\start.bat --clean` | **WARNING:** Stops containers AND deletes your volumes. This completely wipes your database. Use only if you want a fresh start. |

### Utilities
| Command | Description |
|---|---|
| `scripts\start.bat --logs` | Streams live logs from every container to your terminal. |
| `scripts\start.bat --shell` | Opens the interactive Django Python shell inside the container. |
| `scripts\start.bat --superuser`| Automatically provisions an admin account based on your `.env` variables. |
| `scripts\start.bat --test` | Runs the automated `pytest` suite. |

---

## Which one should I use?

It is completely up to your personal preference! 
* If you want a quick shortcut to run a migration without thinking, click the standalone `migrate.bat` file. 
* If you prefer doing everything from your terminal using flags, use the master `start.bat --migrate` script. 

Both methods execute the exact same Docker commands securely under the hood!
