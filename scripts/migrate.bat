@echo off
echo Running migrations inside the backend container...
docker compose exec backend python manage.py migrate
echo Done.
