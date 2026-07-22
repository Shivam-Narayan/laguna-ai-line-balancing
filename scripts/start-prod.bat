@echo off
echo Starting production environment...
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
echo Done.
