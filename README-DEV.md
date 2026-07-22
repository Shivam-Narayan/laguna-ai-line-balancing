# Development Guide

This document describes the development environment setup and best practices for the Laguna AI project.

## 🚀 Local Setup

If you are a new developer setting up the project for the first time, ensure you have **Git**, **Docker Desktop**, **Python 3.10+**, and **Node.js 18+** installed.

### 1. Clone the Repositories
Because the frontend and backend run together in development via Docker Compose, you must clone them into the same parent workspace folder side-by-side:

```bash
mkdir laguna-workspace
cd laguna-workspace
git clone https://github.com/Shivam-Narayan/laguna-ai-line-balancing.git
git clone https://github.com/Shivam-Narayan/laguna-ai-line-balancing-app.git
```

### 2. Configure the Environment
Navigate into the backend and frontend projects and initialize their environment files:
```bash
# Setup Backend Environment
cd laguna-ai-line-balancing
cp .env.example .env

# Setup Frontend Environment
cd ../laguna-ai-line-balancing-app
cp .env.example .env.local
cd ../laguna-ai-line-balancing
```
*(The default values in these environment files are pre-configured to work instantly for local development).*

### 3. Start the Services
Start the environments using our unified startup scripts (which automatically manage the Docker containers and configuration):

**For Development (Strictly Dev):**
- **Windows (Command Prompt):** `scripts\start.bat --dev`
- **Windows (PowerShell):** `.\scripts\start.ps1 -Dev`
- **Mac / Linux:** `bash scripts/start.sh --dev`

**For Production (Strictly Prod):**
- **Windows (Command Prompt):** `scripts\start.bat --prod`
- **Windows (PowerShell):** `.\scripts\start.ps1 -Prod`
- **Mac / Linux:** `bash scripts/start.sh --prod`

#### Important Start Flags (Universal across all platforms):
- **`--dev`**: Starts **Strictly Development**. Merges `docker-compose.yml` and `docker-compose.override.yml`. Runs the database, Redis, Django, React, and local GUI tools (pgAdmin on 5050 & Redis Commander on 8082). It intentionally skips Celery so you can run it manually to see prints/logs in your IDE.
- **`--prod`**: Starts **Strictly Production**. Merges `docker-compose.yml` and `docker-compose.prod.yml`. Runs everything *including* the Nginx reverse proxy, Celery background workers, and the custom Scheduler. It skips all development GUI tools.
- **`(No flag or 'all')`**: Starts **Full-Stack Local Testing**. Merges all three files together, giving you the full production environment (Celery/Nginx) alongside the development GUI tools simultaneously.

#### Utility Flags:
- **`--down`**: Safely stops and removes all containers.
- **`--logs`**: Streams the live terminal output from all running containers.
- **`--shell`**: Drops you into a Django Python shell inside the backend container.

### 4. Access Points
Once the script completes and the containers are healthy, you can access your local environment:
- **Frontend Web App:** [http://localhost:5173](http://localhost:5173) (The main user interface)
- **Backend API:** [http://localhost:8000](http://localhost:8000)
- **Swagger API Docs:** [http://localhost:8000/swagger/](http://localhost:8000/swagger/)
- **Database UI (pgAdmin):** [http://localhost:5050](http://localhost:5050) (Login: admin@laguna.com / admin123)

## Backend Architecture & Standards

### 1. API Routing & Middleware
- **RESTful Conventions:** All endpoints must use plural nouns and kebab-case (e.g., `/api/users/`, `/api/data-engine/employees/`).
- **Endpoint Allowlist:** For security, the backend employs a strict `RequestFilterMiddleware` (`backend/backend_laguna/custom_middleware.py`). **Any new endpoints MUST be explicitly added to the allowlist arrays within this middleware**, otherwise they will return a `404 Not Found`.

### 2. Model Standards
All Django models must strictly adhere to the following enterprise standards:
- **BaseModel Inheritance:** All models must inherit from `apps.core.models.BaseModel`. This provides a standard UUID primary key (`id`), and automatically indexed audit timestamps (`created_at`, `updated_at`).
- **Explicit Table Names:** Always explicitly define the table name using `db_table = 'appname_modelname'` inside the `Meta` class.
- **Explicit Indexing:** Set `db_index=True` on fields that are frequently queried or filtered against (e.g., Foreign Keys, dates, emails, status flags).
- **Modern Enum Choices:** Never use raw tuples for choices. Always use `models.TextChoices` or `models.IntegerChoices`.

### 3. Code Quality Tools
This project strictly enforces code quality through automated tools configured in `backend/pyproject.toml`.
Before submitting a pull request, run the following from the `backend/` directory:
- **Linting & Formatting (Ruff)**: 
  - `python -m ruff check .` (finds errors)
  - `python -m ruff format .` (auto-fixes styling)
- **Type Checking (Mypy)**: 
  - `python -m mypy .` (ensures type hints are valid)
- **Testing (Pytest)**: 
  - `pytest --cov=. --cov-report=term-missing` (runs tests and shows coverage)

## Version Management and Collaboration Guide

## Branching Strategy

We follow a modified GitFlow workflow, which helps us manage releases and features effectively.

### Main Branches

- `main`: The production-ready state of the project.
- `develop`: The main branch for development and integration of features.

### Supporting Branches

- Feature branches: `feature/<feature-name>`
- Release branches: `release/<version-number>`
- Hotfix branches: `hotfix/<hotfix-name>`

## Versioning

We use Semantic Versioning (SemVer) for version numbers: MAJOR.MINOR.PATCH

- MAJOR: Incompatible API changes
- MINOR: Backwards-compatible new features
- PATCH: Backwards-compatible bug fixes

## Workflow

### Feature Development

1. Create a feature branch from `develop`:

   ```
   git checkout develop
   git pull origin develop
   git checkout -b feature/new-feature-name
   ```

2. Develop the feature in your branch.

3. Regularly push your work to the same named branch on the server:

   ```
   git push origin feature/new-feature-name
   ```

4. When the feature is complete, create a pull request to merge into `develop`.

5. After code review and approval, merge the feature branch into `develop`.

### Preparing a Release

1. Create a release branch from `develop`:

   ```
   git checkout develop
   git pull origin develop
   git checkout -b release/1.2.0
   ```

2. Update version numbers in relevant files (e.g., `__init__.py`).

3. Commit the version bump:

   ```
   git commit -am "Bump version to 1.2.0"
   ```

4. Push the release branch and create a pull request for final review:

   ```
   git push origin release/1.2.0
   ```

5. After approval, merge the release branch into both `main` and `develop`:

   ```
   git checkout main
   git merge release/1.2.0
   git push origin main

   git checkout develop
   git merge release/1.2.0
   git push origin develop
   ```

6. Tag the release on `main`:
   ```
   git checkout main
   git tag -a v1.2.0 -m "Release version 1.2.0"
   git push origin v1.2.0
   ```

### Hotfixes

1. Create a hotfix branch from `main`:

   ```
   git checkout main
   git checkout -b hotfix/critical-bug-fix
   ```

2. Fix the bug and bump the PATCH version.

3. Commit the changes and version bump:

   ```
   git commit -am "Fix critical bug and bump version to 1.2.1"
   ```

4. Merge the hotfix into both `main` and `develop`:

   ```
   git checkout main
   git merge hotfix/critical-bug-fix
   git push origin main

   git checkout develop
   git merge hotfix/critical-bug-fix
   git push origin develop
   ```

5. Tag the new version on `main`:
   ```
   git checkout main
   git tag -a v1.2.1 -m "Hotfix: Critical bug fix"
   git push origin v1.2.1
   ```

## Best Practices for Collaboration

1. **Commit Often**: Make small, focused commits with clear messages.

2. **Pull Before Push**: Always pull the latest changes before pushing to avoid conflicts.

3. **Code Review**: All changes should be reviewed through pull requests before merging.

4. **Keep Branches Updated**: Regularly merge or rebase your feature branches with `develop`.

5. **Branch Naming**: Use descriptive names for branches (e.g., `feature/add-user-authentication`).

6. **Commit Messages**: Write clear, concise commit messages. Start with a verb in the imperative mood.

7. **Documentation**: Update relevant documentation as part of your changes.

8. **Testing**: Ensure all tests pass before creating a pull request.

9. **CI/CD**: Utilize Continuous Integration to automatically test and validate changes.

10. **Clean Up**: Delete feature branches after merging.

## Release Process

1. Prepare the release branch.
2. Update CHANGELOG.md with the new version and its changes.
3. Update version numbers in relevant files.
4. Conduct final testing and bug fixes in the release branch.
5. Merge to `main` and `develop` as described above.
6. Tag the release on `main`.
7. Build and deploy the new version.
8. Announce the release to the team and relevant stakeholders.

By following these guidelines, we ensure a smooth collaboration process and maintain a clear history of our project's development.
