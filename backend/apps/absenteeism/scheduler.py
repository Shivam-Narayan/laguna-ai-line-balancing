import logging
logger = logging.getLogger(__name__)

from pytz import timezone
from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
scheduler_started = False  # Global flag to prevent multiple starts

def start():
    from .tasks import (
        run_absenteeism_prediction_task,
        scheduler_prediction_data_email_task,
        save_absenteeism_report_task,
        fetch_absenteeism_report_data_task,
        run_absenteeism_report_task
    )
    global scheduler_started
    if not scheduler_started:
        logger.info("🔄 Starting APScheduler for Absenteeism App (Celery Mode)...")

        # Set the timezone (e.g., for IST - Indian Standard Time)
        ist = timezone("Asia/Kolkata")
        scheduler.add_job(run_absenteeism_prediction_task.delay,
                          CronTrigger(hour=3, minute=30, day_of_week='mon-sat', timezone=ist),  # 03:30 (03:30 AM)
                          id="absenteeism_prediction_job_3_30",
                          replace_existing=True,
                          misfire_grace_time=300,  # 5 minutes
                          kwargs={"viaAPI": False}  # Parameter
                        )
        scheduler.add_job(scheduler_prediction_data_email_task.delay,
                          CronTrigger(hour=9, minute=0, day_of_week='mon-sun', timezone=ist),  # 9:00 (09:00 AM)
                          id="scheduler_prediction_data_email_job_9_00",
                          replace_existing=True,
                          misfire_grace_time=300,  # 5 minutes
                          args=["all", 1]  # first parameter is the Lines, second is the forecast period
                        )
        scheduler.add_job(save_absenteeism_report_task.delay,
                          CronTrigger(hour=19, minute=30, day_of_week='mon-sun', timezone=ist),  # 19:30 (09:30 PM)
                          id="save_absenteeism_report_job_19_30",
                          replace_existing=True,
                          misfire_grace_time=300,  # 5 minutes
                        )
        scheduler.add_job(fetch_absenteeism_report_data_task.delay,
                          CronTrigger(hour=13, minute=30, day_of_week='mon-sun', timezone=ist),  # 13:30 (01:30 PM)
                          id="save_absenteeism_report_job_13_30",
                          replace_existing=True,
                          misfire_grace_time=300,  # 5 minutes
                        )
        scheduler.add_job(run_absenteeism_report_task.delay,
                          CronTrigger(hour=18, minute=30, day_of_week='mon-sun', timezone=ist),  # 18:30 (06:30 PM)
                          id="run_absenteeism_report_job_9_30",
                          replace_existing=True,
                          misfire_grace_time=300,  # 5 minutes
                          kwargs={"viaAPI": False}  # Parameter
                        )
        scheduler.start()
        scheduler_started = True  # Set flag to True after starting
    else:
        logger.info("⚠ APScheduler for Absenteeism App is already running!")
