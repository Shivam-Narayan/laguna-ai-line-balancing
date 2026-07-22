@echo off
REM ============================================================================
REM Laguna AI Line Balancing — Startup Script (Windows CMD)
REM ============================================================================
REM Usage: scripts\start.bat [OPTION]
REM Run with -h or --help for details.
REM ============================================================================

setlocal enabledelayedexpansion

REM ── Project root (one level up from scripts\) ─────────────────────────────
set "PROJECT_ROOT=%~dp0.."
set "BACKEND_DIR=%PROJECT_ROOT%\backend"
set "ENV_FILE=%PROJECT_ROOT%\.env"

REM ── Parse arguments ───────────────────────────────────────────────────────
set "COMMAND="
set "STAGED_MODE=false"
set "RESTORE_FILE="

:parse_args
if "%~1"=="" goto :end_parse
if /i "%~1"=="--staged"          ( set "STAGED_MODE=true"          & shift & goto :parse_args )
if /i "%~1"=="--fast"            ( set "STAGED_MODE=false"         & shift & goto :parse_args )
if /i "%~1"=="--dev"             ( set "COMMAND=dev"               & shift & goto :parse_args )
if /i "%~1"=="--prod"            ( set "COMMAND=prod"              & shift & goto :parse_args )
if /i "%~1"=="--build"           ( set "COMMAND=build"             & shift & goto :parse_args )
if /i "%~1"=="--down"            ( set "COMMAND=down"              & shift & goto :parse_args )
if /i "%~1"=="--clean"           ( set "COMMAND=clean"             & shift & goto :parse_args )
if /i "%~1"=="--logs"            ( set "COMMAND=logs"              & shift & goto :parse_args )
if /i "%~1"=="--status"          ( set "COMMAND=status"            & shift & goto :parse_args )
if /i "%~1"=="--local"           ( set "COMMAND=local"             & shift & goto :parse_args )
if /i "%~1"=="--migrate"         ( set "COMMAND=migrate"           & shift & goto :parse_args )
if /i "%~1"=="--makemigrations"  ( set "COMMAND=makemigrations"    & shift & goto :parse_args )
if /i "%~1"=="--shell"           ( set "COMMAND=shell"             & shift & goto :parse_args )
if /i "%~1"=="--superuser"       ( set "COMMAND=superuser"         & shift & goto :parse_args )
if /i "%~1"=="--test"            ( set "COMMAND=test"              & shift & goto :parse_args )
if /i "%~1"=="--backup"          ( set "COMMAND=backup"            & shift & goto :parse_args )
if /i "%~1"=="--restore"         ( set "COMMAND=restore" & set "RESTORE_FILE=%~2" & shift & shift & goto :parse_args )
if /i "%~1"=="-h"                ( goto :show_help )
if /i "%~1"=="--help"            ( goto :show_help )
echo [ERROR] Unknown option: %~1
call :show_help
exit /b 1
:end_parse

REM ── Banner ────────────────────────────────────────────────────────────────
call :show_banner

REM -- If no command, start all services by default --
if "%COMMAND%"=="" (
    set "COMMAND=all"
)

REM ── Load environment ──────────────────────────────────────────────────────
call :load_env

REM ── Set Compose Files ─────────────────────────────────────────────────────
set "COMPOSE_FILE=docker-compose.yml"

REM ── Route to command ──────────────────────────────────────────────────────
if "%COMMAND%"=="all"             goto :cmd_all
if "%COMMAND%"=="dev"             goto :cmd_dev
if "%COMMAND%"=="prod"            goto :cmd_prod
if "%COMMAND%"=="build"           goto :cmd_build
if "%COMMAND%"=="down"            goto :cmd_down
if "%COMMAND%"=="clean"           goto :cmd_clean
if "%COMMAND%"=="logs"            goto :cmd_logs
if "%COMMAND%"=="status"          goto :cmd_status
if "%COMMAND%"=="local"           goto :cmd_local
if "%COMMAND%"=="migrate"         goto :cmd_migrate
if "%COMMAND%"=="makemigrations"  goto :cmd_makemigrations
if "%COMMAND%"=="shell"           goto :cmd_shell
if "%COMMAND%"=="superuser"       goto :cmd_superuser
if "%COMMAND%"=="test"            goto :cmd_test
if "%COMMAND%"=="backup"          goto :cmd_backup
if "%COMMAND%"=="restore"         goto :cmd_restore
goto :eof

REM ════════════════════════════════════════════════════════════════════════════
REM FUNCTIONS
REM ════════════════════════════════════════════════════════════════════════════

:show_banner
echo.
echo   ======================================================
echo        Laguna AI  -  Line Balancing Platform
echo   ======================================================
echo.
exit /b 0

:show_help
call :show_banner
echo Usage: scripts\start.bat [OPTION]
echo.
echo Docker Commands:
echo   --dev              Start development services  (db + redis + backend + pgadmin)
echo   --prod             Start production services   (db + redis + backend + celery + nginx)
echo   --build            Rebuild Docker images and start dev services
echo   --down             Stop and remove all containers
echo   --clean            Stop containers and remove volumes (DATA LOSS!)
echo   --logs             Tail logs for all running containers
echo   --status           Show status of all containers
echo.
echo Local Development:
echo   --local            Start Django dev server locally (no Docker)
echo   --migrate          Run database migrations
echo   --makemigrations   Create new migration files
echo   --shell            Open Django interactive shell
echo   --superuser        Create a Django superuser
echo   --test             Run the test suite
echo.
echo Database:
echo   --backup           Backup PostgreSQL database to timestamped file
echo   --restore FILE     Restore database from a backup file
echo.
echo Startup Modes (combine with Docker commands):
echo   --staged           Enable staged startup sequence  (default)
echo   --fast             Disable staged startup (quick, parallel start)
echo.
echo Other:
echo   -h, --help         Show this help message
echo.
echo Examples:
echo   scripts\start.bat --dev               Start dev environment with Docker
echo   scripts\start.bat --dev --fast        Quick-start dev (no staged delays)
echo   scripts\start.bat --local             Run Django locally without Docker
echo   scripts\start.bat --prod --staged     Production with staged startup
echo   scripts\start.bat --down              Stop everything
echo.
exit /b 0

:load_env
if exist "%ENV_FILE%" (
    echo [INFO] Loading environment from %ENV_FILE%
    for /f "usebackq tokens=1,* delims==" %%a in ("%ENV_FILE%") do (
        set "line=%%a"
        if not "!line:~0,1!"=="#" (
            if not "%%a"=="" if not "%%b"=="" (
                set "%%a=%%b"
            )
        )
    )
) else if exist "%PROJECT_ROOT%\.env.example" (
    echo [WARN] No .env file found. Copying .env.example to .env
    copy "%PROJECT_ROOT%\.env.example" "%ENV_FILE%" >nul
    call :load_env
) else (
    echo [WARN] No .env file found. Using defaults.
)
exit /b 0

:check_docker
where docker >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not installed.
    exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker daemon is not running. Please start Docker Desktop.
    exit /b 1
)
echo [OK] Docker is available
exit /b 0

:check_python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    exit /b 1
)
for /f "delims=" %%v in ('python --version 2^>^&1') do echo [OK] %%v
exit /b 0

:determine_docker_compose
REM Try 'docker compose' (v2) first, fall back to 'docker-compose' (v1)
docker compose version >nul 2>&1
if not errorlevel 1 (
    set "DC=docker compose"
    exit /b 0
)
where docker-compose >nul 2>&1
if not errorlevel 1 (
    set "DC=docker-compose"
    exit /b 0
)
echo [ERROR] Docker Compose is not installed.
exit /b 1

:activate_venv
if exist "%PROJECT_ROOT%\.venv\Scripts\activate.bat" (
    echo [INFO] Activating virtual environment...
    call "%PROJECT_ROOT%\.venv\Scripts\activate.bat"
) else (
    echo [WARN] No .venv found. Using system Python.
)
exit /b 0

REM ── Docker Commands ───────────────────────────────────────────────────────

:cmd_all
call :check_docker
if errorlevel 1 exit /b 1
call :determine_docker_compose
if errorlevel 1 exit /b 1

if "%STAGED_MODE%"=="true" (
    echo [INFO] Starting ALL services ^(staged sequence^)...

    echo   Stage 1/4: Core infrastructure ^(db, redis^)...
    %DC% -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml up -d db redis
    echo   Waiting for databases to be healthy...
    timeout /t 10 /nobreak >nul

    echo   Stage 2/4: Backend application...
    %DC% -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml up -d backend
    timeout /t 5 /nobreak >nul

    echo   Stage 3/4: Background workers ^(celery, scheduler^)...
    %DC% -f docker-compose.yml -f docker-compose.prod.yml up -d celery scheduler
    timeout /t 3 /nobreak >nul

    echo   Stage 4/4: Developer tools and reverse proxy ^(pgadmin, nginx^)...
    %DC% -f docker-compose.yml -f docker-compose.override.yml up -d pgadmin
    %DC% -f docker-compose.yml -f docker-compose.prod.yml up -d nginx
) else (
    echo [INFO] Starting ALL services ^(fast mode^)...
    %DC% -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml up --force-recreate -d
)

echo [OK] All services started

if not defined BACKEND_PORT set "BACKEND_PORT=8000"
if not defined PGADMIN_PORT set "PGADMIN_PORT=5050"
echo   Dev Backend:   http://localhost:%BACKEND_PORT%
echo   Swagger:       http://localhost:%BACKEND_PORT%/swagger/
echo   pgAdmin:       http://localhost:%PGADMIN_PORT%
echo   Redis UI:      http://localhost:8082
echo   Prod (nginx):  http://localhost
echo   Grafana:       http://localhost:4000
echo.
goto :eof

:cmd_dev
call :check_docker
if errorlevel 1 exit /b 1
call :determine_docker_compose
if errorlevel 1 exit /b 1

if "%STAGED_MODE%"=="true" (
    echo [INFO] Starting dev services ^(staged sequence^)...

    echo   Stage 1/3: Core infrastructure ^(db, redis^)...
    %DC% -f docker-compose.yml -f docker-compose.override.yml up -d db redis
    echo   Waiting for databases to be healthy...
    timeout /t 8 /nobreak >nul

    echo   Stage 2/3: Backend application...
    %DC% -f docker-compose.yml -f docker-compose.override.yml up -d backend
    timeout /t 5 /nobreak >nul

    echo   Stage 3/3: Developer tools ^(pgadmin^)...
    %DC% -f docker-compose.yml -f docker-compose.override.yml up -d pgadmin
) else (
    echo [INFO] Starting dev services ^(fast mode^)...
    %DC% -f docker-compose.yml -f docker-compose.override.yml up --force-recreate -d
)

echo [OK] All dev services started

if not defined BACKEND_PORT set "BACKEND_PORT=8000"
if not defined PGADMIN_PORT set "PGADMIN_PORT=5050"
echo   Backend:  http://localhost:%BACKEND_PORT%
echo   Swagger:  http://localhost:%BACKEND_PORT%/swagger/
echo   pgAdmin:  http://localhost:%PGADMIN_PORT%
echo   Redis UI: http://localhost:8082
echo   Grafana:  http://localhost:4000
echo.
goto :eof

:cmd_prod
call :check_docker
if errorlevel 1 exit /b 1
call :determine_docker_compose
if errorlevel 1 exit /b 1

if "%STAGED_MODE%"=="true" (
    echo [INFO] Starting production services ^(staged sequence^)...

    echo   Stage 1/4: Core infrastructure ^(db, redis^)...
    %DC% -f docker-compose.yml -f docker-compose.prod.yml up -d db redis
    timeout /t 10 /nobreak >nul

    echo   Stage 2/4: Backend application...
    %DC% -f docker-compose.yml -f docker-compose.prod.yml up -d backend
    timeout /t 8 /nobreak >nul

    echo   Stage 3/4: Background workers ^(celery^)...
    %DC% -f docker-compose.yml -f docker-compose.prod.yml up -d celery
    timeout /t 5 /nobreak >nul

    echo   Stage 4/4: Reverse proxy ^(nginx^)...
    %DC% -f docker-compose.yml -f docker-compose.prod.yml up -d nginx
) else (
    echo [INFO] Starting production services ^(fast mode^)...
    %DC% -f docker-compose.yml -f docker-compose.prod.yml up --force-recreate -d
)

echo [OK] All production services started

echo   Application: http://localhost (via nginx)
echo   Grafana:     http://localhost:4000
echo.
goto :eof

:cmd_build
call :check_docker
if errorlevel 1 exit /b 1
call :determine_docker_compose
if errorlevel 1 exit /b 1

echo [INFO] Rebuilding Docker images...
%DC% -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml build --no-cache
echo [OK] Images rebuilt

goto :cmd_all

:cmd_down
call :check_docker
if errorlevel 1 exit /b 1
call :determine_docker_compose
if errorlevel 1 exit /b 1

echo [INFO] Stopping and removing all containers...
%DC% -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml down
echo [OK] All containers stopped and removed
goto :eof

:cmd_clean
call :check_docker
if errorlevel 1 exit /b 1
call :determine_docker_compose
if errorlevel 1 exit /b 1

echo [WARNING] This will remove all containers AND volumes (database data will be lost!)
set /p confirm="Continue? (y/N): "
if /i "%confirm%"=="y" (
    %DC% -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml down -v
    echo [OK] Containers and volumes removed
) else (
    echo   Cancelled.
)
goto :eof

:cmd_logs
call :determine_docker_compose
if errorlevel 1 exit /b 1
echo [INFO] Tailing logs (Ctrl+C to stop)...
%DC% logs -f
goto :eof

:cmd_status
call :determine_docker_compose
if errorlevel 1 exit /b 1
echo [INFO] Container status:
%DC% ps -a
goto :eof

:cmd_backup
call :determine_docker_compose
if errorlevel 1 exit /b 1

for /f "tokens=2-4 delims=/ " %%a in ('date /t') do set "mydate=%%c%%a%%b"
for /f "tokens=1-2 delims=/:" %%a in ('time /t') do set "mytime=%%a%%b"
set "BACKUP_FILE=%PROJECT_ROOT%\backup_%mydate%_%mytime: =0%.sql"

echo [INFO] Backing up database...
if not defined DB_USER set "DB_USER=postgres"
if not defined DB_NAME set "DB_NAME=Laguna"
%DC% exec -T db pg_dump -U %DB_USER% %DB_NAME% > "%BACKUP_FILE%"
echo [OK] Backup saved to %BACKUP_FILE%
goto :eof

:cmd_restore
call :determine_docker_compose
if errorlevel 1 exit /b 1

if "%RESTORE_FILE%"=="" (
    echo [ERROR] Backup file not specified.
    echo   Usage: scripts\start.bat --restore ^<backup-file.sql^>
    exit /b 1
)
if not exist "%RESTORE_FILE%" (
    echo [ERROR] File not found: %RESTORE_FILE%
    exit /b 1
)

echo [INFO] Restoring database from %RESTORE_FILE%...
if not defined DB_USER set "DB_USER=postgres"
if not defined DB_NAME set "DB_NAME=Laguna"
%DC% exec -T db psql -U %DB_USER% %DB_NAME% < "%RESTORE_FILE%"
echo [OK] Database restored
goto :eof

REM ── Local Commands ────────────────────────────────────────────────────────

:cmd_local
call :check_python
if errorlevel 1 exit /b 1
call :activate_venv

echo [INFO] Starting Django development server...
echo   Backend dir: %BACKEND_DIR%
echo.
echo   Server:   http://127.0.0.1:8000
echo   Swagger:  http://127.0.0.1:8000/swagger/
echo   Redoc:    http://127.0.0.1:8000/redoc/
echo.
cd /d "%BACKEND_DIR%"
python manage.py runserver
goto :eof

:cmd_migrate
call :check_python
if errorlevel 1 exit /b 1
call :activate_venv

echo [INFO] Running database migrations...
cd /d "%BACKEND_DIR%"
python manage.py migrate
echo [OK] Migrations applied
goto :eof

:cmd_makemigrations
call :check_python
if errorlevel 1 exit /b 1
call :activate_venv

echo [INFO] Creating migration files...
cd /d "%BACKEND_DIR%"
python manage.py makemigrations
echo [OK] Migration files created
goto :eof

:cmd_shell
call :check_python
if errorlevel 1 exit /b 1
call :activate_venv

echo [INFO] Opening Django shell...
cd /d "%BACKEND_DIR%"
python manage.py shell
goto :eof

:cmd_superuser
call :check_python
if errorlevel 1 exit /b 1
call :activate_venv

echo [INFO] Creating superuser...
cd /d "%BACKEND_DIR%"
python manage.py createsuperuser
goto :eof

:cmd_test
call :check_python
if errorlevel 1 exit /b 1
call :activate_venv

echo [INFO] Running test suite...
cd /d "%BACKEND_DIR%"
pytest --cov=. --cov-report=term-missing
echo [OK] Tests complete
goto :eof
