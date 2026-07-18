Write-Host "Running migrations inside the backend container..."
docker compose exec backend python manage.py migrate
Write-Host "Done."
