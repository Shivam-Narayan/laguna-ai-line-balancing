import os
import re

def replace_in_file(filepath):
    if not os.path.exists(filepath):
        return
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Define replacements
    replacements = [
        # In cmd_all
        (r'%DC% --profile dev --profile prod up -d db redis', r'%DC% -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml up -d db redis'),
        (r'%DC% --profile dev --profile prod up -d backend', r'%DC% -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml up -d backend'),
        (r'%DC% --profile prod --profile scheduler up -d celery scheduler', r'%DC% -f docker-compose.yml -f docker-compose.prod.yml up -d celery scheduler'),
        (r'%DC% --profile dev up -d pgadmin', r'%DC% -f docker-compose.yml -f docker-compose.override.yml up -d pgadmin'),
        (r'%DC% --profile prod up -d nginx', r'%DC% -f docker-compose.yml -f docker-compose.prod.yml up -d nginx'),
        (r'%DC% --profile dev --profile prod --profile scheduler up --force-recreate -d', r'%DC% -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml up --force-recreate -d'),
        
        # In cmd_dev
        (r'%DC% --profile dev up -d db redis', r'%DC% -f docker-compose.yml -f docker-compose.override.yml up -d db redis'),
        (r'%DC% --profile dev up -d backend', r'%DC% -f docker-compose.yml -f docker-compose.override.yml up -d backend'),
        (r'%DC% --profile dev up -d pgadmin redis-commander', r'%DC% -f docker-compose.yml -f docker-compose.override.yml up -d pgadmin redis-commander'),
        (r'%DC% --profile dev up --force-recreate -d', r'%DC% -f docker-compose.yml -f docker-compose.override.yml up --force-recreate -d'),
        
        # In cmd_prod
        (r'%DC% --profile prod up -d db redis', r'%DC% -f docker-compose.yml -f docker-compose.prod.yml up -d db redis'),
        (r'%DC% --profile prod up -d backend', r'%DC% -f docker-compose.yml -f docker-compose.prod.yml up -d backend'),
        (r'%DC% --profile prod up -d celery scheduler', r'%DC% -f docker-compose.yml -f docker-compose.prod.yml up -d celery scheduler'),
        (r'%DC% --profile prod up --force-recreate -d', r'%DC% -f docker-compose.yml -f docker-compose.prod.yml up --force-recreate -d'),
        
        # In cmd_down
        (r'%DC% --profile dev --profile prod --profile scheduler down', r'%DC% -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml down'),
        (r'%DC% --profile dev --profile prod --profile scheduler down -v', r'%DC% -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml down -v'),
    ]

    # For ps1 / sh, the variable is $DOCKER_COMPOSE_CMD or $DC
    # Let's generalize it.
    
    # Actually, we can just replace the string '--profile dev --profile prod up' with '-f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml up'
    
    new_content = content
    # Replace profile dev+prod
    new_content = new_content.replace('--profile dev --profile prod up', '-f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml up')
    new_content = new_content.replace('--profile dev --profile prod --profile scheduler up', '-f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml up')
    new_content = new_content.replace('--profile dev --profile prod --profile scheduler down', '-f docker-compose.yml -f docker-compose.override.yml -f docker-compose.prod.yml down')
    
    # Replace prod+scheduler
    new_content = new_content.replace('--profile prod --profile scheduler up', '-f docker-compose.yml -f docker-compose.prod.yml up')
    
    # Replace single dev
    new_content = new_content.replace('--profile dev up', '-f docker-compose.yml -f docker-compose.override.yml up')
    
    # Replace single prod
    new_content = new_content.replace('--profile prod up', '-f docker-compose.yml -f docker-compose.prod.yml up')

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {filepath}")
    else:
        print(f"No changes for {filepath}")

for root, _, files in os.walk('c:/Projects/laguna/laguna-ai-line-balancing/scripts'):
    for f in files:
        if f in ['start.bat', 'start.ps1', 'start.sh']:
            replace_in_file(os.path.join(root, f))
