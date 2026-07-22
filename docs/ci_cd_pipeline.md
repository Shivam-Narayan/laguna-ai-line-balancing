# Continuous Integration & Delivery (CI/CD)

This document explains the automated deployment and testing pipeline for the Laguna-AI Line Balancing application. We utilize **GitHub Actions** to guarantee that only stable, working code is merged into the production branches.

---

## 1. The Automated Workflow (`.github/workflows/ci.yml`)

The CI pipeline acts as an automated gatekeeper. Every time a developer pushes code or opens a Pull Request against the `main` or `develop` branches, the pipeline triggers a secure, isolated cloud environment to test the application.

### Pipeline Steps:

1. **Environment Provisioning (`runs-on: ubuntu-latest`)**
   - GitHub provisions a clean Linux virtual machine. This ensures the application is not dependent on a specific developer's local machine ("it works on my machine" syndrome).

2. **Service Containers (Postgres & Redis)**
   - The pipeline instantly boots up ephemeral **PostgreSQL** and **Redis** Docker containers. 
   - It runs health checks (e.g., `pg_isready` and `redis-cli ping`) to ensure the databases are fully online before attempting to boot the Django backend.

3. **Code Checkout & Dependency Installation**
   - The virtual machine clones the latest repository code.
   - It sets up Python 3.11.
   - It uses `uv` to execute a lightning-fast installation of all backend dependencies.

4. **Django System Integrity Checks**
   - The pipeline injects test environment variables (`DB_USER`, `SECRET_KEY`, etc.) allowing Django to connect to the ephemeral Postgres/Redis containers.
   - **`python manage.py check`**: Scans the entire Django codebase for syntax errors, missing models, or invalid configurations.
   - **`python manage.py makemigrations --check --dry-run`**: Validates that developers did not modify `models.py` without also generating the corresponding database migration files.

5. **Docker Build Validation (`docker-compose build`)**
   - After the Python code passes, the pipeline executes a full Docker Compose build of the backend image.
   - This guarantees that if the code is deployed to the production server, the Dockerfile will successfully compile without throwing OS-level or package errors.

---

## 2. Merge Protection

If **any** of the steps above fail:
- GitHub marks the commit with a red **❌**.
- The Pull Request is blocked from being merged into `main`.
- The developer receives an email alert with the exact terminal logs showing where the crash occurred.

If all steps pass, the commit receives a green **✅**, signaling it is safe for the DevOps team to pull to the production server.
