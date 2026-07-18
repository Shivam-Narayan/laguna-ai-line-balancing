@echo off
REM Generate a timestamped backup file
set "TIMESTAMP=%date:~-4,4%%date:~-10,2%%date:~-7,2%_%time:~0,2%%time:~3,2%"
set "TIMESTAMP=%TIMESTAMP: =0%"
set "BACKUP_FILE=backup_%TIMESTAMP%.sql"

echo Backing up PostgreSQL database to %BACKUP_FILE%...
docker compose exec db pg_dump -U postgres -d Laguna > %BACKUP_FILE%
echo Backup complete!
