@echo off
if "%~1"=="" (
    echo Usage: scripts\restore.bat backup_file.sql
    exit /b 1
)

echo Restoring database from %~1...
docker compose exec -T db psql -U postgres -d Laguna < "%~1"
echo Restore complete!
