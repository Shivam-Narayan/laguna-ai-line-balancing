import os

from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("laguna")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Set the timezone to IST
app.conf.timezone = 'Asia/Kolkata'

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Celery Beat Schedule
app.conf.beat_schedule = {
    # ------------------ ABSENTEEISM JOBS ------------------
    'absenteeism_prediction_job': {
        'task': 'apps.absenteeism.tasks.run_absenteeism_prediction_task',
        'schedule': crontab(hour=3, minute=30, day_of_week='mon-sat'),
        'kwargs': {"viaAPI": False},
    },
    'scheduler_prediction_data_email_job': {
        'task': 'apps.absenteeism.tasks.scheduler_prediction_data_email_task',
        'schedule': crontab(hour=9, minute=0, day_of_week='*'),
        'args': ["all", 1],
    },
    'fetch_absenteeism_report_data_job': {
        'task': 'apps.absenteeism.tasks.fetch_absenteeism_report_data_task',
        'schedule': crontab(hour=13, minute=30, day_of_week='*'),
    },
    'run_absenteeism_report_job': {
        'task': 'apps.absenteeism.tasks.run_absenteeism_report_task',
        'schedule': crontab(hour=18, minute=30, day_of_week='*'),
        'kwargs': {"viaAPI": False},
    },
    'save_absenteeism_report_job': {
        'task': 'apps.absenteeism.tasks.save_absenteeism_report_task',
        'schedule': crontab(hour=19, minute=30, day_of_week='*'),
    },

    # ------------------ MANNING SHEET JOBS ------------------
    'run_generate_style_ob_job': {
        'task': 'apps.manning_sheet.tasks.run_generate_style_ob_task',
        'schedule': crontab(hour=7, minute=45, day_of_week='mon-sat'),
        'kwargs': {"viaAPI": False},
    },
    'run_manning_generation_job': {
        'task': 'apps.manning_sheet.tasks.run_manning_generation_task',
        'schedule': crontab(hour=8, minute=0, day_of_week='mon'),
        'kwargs': {"viaAPI": False, "PERIOD": 60},
    },
    'run_generate_dday_manning_8_50_job': {
        'task': 'apps.manning_sheet.tasks.run_dday_generation_task',
        'schedule': crontab(hour=8, minute=50, day_of_week='mon-sat'),
        'kwargs': {"viaAPI": False},
    },
    'run_fetch_wip_data_job_8_50': {
        'task': 'apps.manning_sheet.tasks.run_fetch_wip_data_task',
        'schedule': crontab(hour=8, minute=50, day_of_week='mon-sat'),
        'kwargs': {"viaAPI": False},
    },
    'run_generate_dday_manning_12_45_job': {
        'task': 'apps.manning_sheet.tasks.run_dday_generation_task',
        'schedule': crontab(hour=12, minute=45, day_of_week='mon-sat'),
        'kwargs': {"viaAPI": False},
    },
    'run_fetch_wip_data_job_12_45': {
        'task': 'apps.manning_sheet.tasks.run_fetch_wip_data_task',
        'schedule': crontab(hour=12, minute=45, day_of_week='mon-sat'),
        'kwargs': {"viaAPI": False},
    },
    'run_generate_dday_manning_17_30_job': {
        'task': 'apps.manning_sheet.tasks.run_dday_generation_task',
        'schedule': crontab(hour=17, minute=30, day_of_week='mon-sat'),
        'kwargs': {"viaAPI": False},
    },
    'run_fetch_wip_data_job_17_30': {
        'task': 'apps.manning_sheet.tasks.run_fetch_wip_data_task',
        'schedule': crontab(hour=17, minute=30, day_of_week='mon-sat'),
        'kwargs': {"viaAPI": False},
    },
    'fetch_and_transform_empdetails_job': {
        'task': 'apps.manning_sheet.tasks.fetch_and_transform_empdetails_task',
        'schedule': crontab(hour=21, minute=45, day_of_week='mon-sat'),
    },
    'run_generate_emp_fact_job': {
        'task': 'apps.manning_sheet.tasks.run_generate_emp_fact_task',
        'schedule': crontab(hour=22, minute=0, day_of_week='mon-sat'),
    },
    'delete_old_exported_files_job': {
        'task': 'apps.manning_sheet.tasks.delete_old_exported_files_task',
        'schedule': crontab(hour=9, minute=0, day_of_week='sun'),
        'kwargs': {"days_old": 7, "file_extension": ".xlsx"},
    },

    # ------------------ DATA ENGINE JOBS ------------------
    'employee_master_job': {
        'task': 'apps.data_engine.tasks.run_generate_employee_master_task',
        'schedule': crontab(hour=22, minute=30, day_of_week='mon-sat'),
    },
}
