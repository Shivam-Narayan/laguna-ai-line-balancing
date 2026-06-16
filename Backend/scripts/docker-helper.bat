@echo off
REM Docker Compose Helper Script for Laguna AI Backend (Windows)
REM Usage: docker-helper.bat [command]

setlocal enabledelayedexpansion

if "%1"=="" (
    call :show_help
    exit /b 0
)

if /i "%1"=="start" (
    call :start
) else if /i "%1"=="stop" (
    call :stop
) else if /i "%1"=="restart" (
    call :restart
) else if /i "%1"=="logs" (
    call :logs
) else if /i "%1"=="shell" (
    call :shell
) else if /i "%1"=="migrate" (
    call :migrate
) else if /i "%1"=="makemigrations" (
    call :makemigrations
) else if /i "%1"=="superuser" (
    call :superuser
) else if /i "%1"=="test" (
    call :test
) else if /i "%1"=="clean" (
    call :clean
) else if /i "%1"=="backup" (
    call :backup
) else if /i "%1"=="restore" (
    call :restore %2
) else if /i "%1"=="status" (
    call :status
) else if /i "%1"=="rebuild" (
    call :rebuild
) else if /i "%1"=="help" (
    call :show_help
) else (
    echo Unknown command: %1
    call :show_help
    exit /b 1
)
exit /b 0

:show_help
echo Laguna AI - Docker Helper
echo.
echo Usage: docker-helper.bat [command]
echo.
echo Commands:
echo   start          - Start all services
echo   stop           - Stop all services
echo   restart        - Restart all services
echo   logs           - Show logs for all services
echo   shell          - Open Django shell
echo   migrate        - Run database migrations
echo   makemigrations - Create new migrations
echo   superuser      - Create superuser
echo   test           - Run tests
echo   clean          - Remove all containers and volumes
echo   backup         - Backup database
echo   restore file   - Restore database from backup
echo   status         - Show container status
echo   rebuild        - Rebuild Docker images
exit /b 0

:start
echo Starting services...
docker-compose up -d
echo Services started
call :status
exit /b 0

:stop
echo Stopping services...
docker-compose stop
echo Services stopped
exit /b 0

:restart
echo Restarting services...
docker-compose restart
echo Services restarted
exit /b 0

:logs
docker-compose logs -f
exit /b 0

:shell
echo Opening Django shell...
docker-compose exec backend python manage.py shell
exit /b 0

:migrate
echo Running migrations...
docker-compose exec backend python manage.py migrate
echo Migrations complete
exit /b 0

:makemigrations
echo Creating migrations...
docker-compose exec backend python manage.py makemigrations
echo Migrations created
exit /b 0

:superuser
echo Creating superuser...
docker-compose exec backend python manage.py createsuperuser
exit /b 0

:test
echo Running tests...
docker-compose exec backend python manage.py test
exit /b 0

:clean
echo WARNING: This will remove all containers, networks, and volumes
set /p confirm="Continue? (y/N): "
if /i "%confirm%"=="y" (
    echo Cleaning up...
    docker-compose down -v
    echo Cleanup complete
)
exit /b 0

:backup
echo Backing up database...
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set mydate=%%c%%a%%b)
for /f "tokens=1-2 delims=/:" %%a in ('time /t') do (set mytime=%%a%%b)
set BACKUP_FILE=backup_%mydate%_%mytime%.sql
docker-compose exec -T db pg_dump -U postgres Laguna > %BACKUP_FILE%
echo Backup saved to %BACKUP_FILE%
exit /b 0

:restore
if "%2"=="" (
    echo Error: Backup file not specified
    echo Usage: docker-helper.bat restore ^<backup-file^>
    exit /b 1
)
if not exist "%2" (
    echo Error: File %2 not found
    exit /b 1
)
echo Restoring database from %2...
docker-compose exec -T db psql -U postgres Laguna < %2
echo Database restored
exit /b 0

:status
echo Container Status:
docker-compose ps
exit /b 0

:rebuild
echo Rebuilding images...
docker-compose build --no-cache
echo Images rebuilt
exit /b 0
