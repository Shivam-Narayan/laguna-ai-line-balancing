import os
 
# List of commands to be executed
commands = [
    "pip install -r requirements.txt",
    "python manage.py makemigrations apps.accounts",
    "python manage.py makemigrations apps.data_engine",
    "python manage.py makemigrations apps.absenteeism",
    "python manage.py makemigrations apps.manning_sheet",
    "python manage.py migrate"
]
 
# Execute each command
for command in commands:
    os.system(command)