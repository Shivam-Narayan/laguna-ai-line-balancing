import subprocess
import sys

# List of commands to be executed
commands = [
    ["pip", "install", "-r", "requirements.txt"],
    ["python", "manage.py", "makemigrations", "apps.accounts"],
    ["python", "manage.py", "makemigrations", "apps.data_engine"],
    ["python", "manage.py", "makemigrations", "apps.absenteeism"],
    ["python", "manage.py", "makemigrations", "apps.manning_sheet"],
    ["python", "manage.py", "migrate"]
]

for cmd in commands:
    print(f"🚀 Running: {' '.join(cmd)}")
    
    # Run the command and wait for it to finish. 
    # check=True ensures that if a command fails, Python raises an exception and stops.
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Command failed with exit code {e.returncode}: {' '.join(cmd)}")
        sys.exit(1)  # Exit the script completely so later commands don't run

print("✅ All commands executed successfully!")