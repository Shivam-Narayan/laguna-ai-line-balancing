import logging

logger = logging.getLogger(__name__)

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone

scheduler = BackgroundScheduler()
scheduler_started = False  # Global flag to prevent multiple starts


def start():
    from .views import run_generate_employee_master

    global scheduler_started
    if not scheduler_started:
        logger.info("🔄 Starting APScheduler for DataEngine App...")

        # Set the timezone (e.g., for IST - Indian Standard Time)
        ist = timezone("Asia/Kolkata")
        scheduler.add_job(
            run_generate_employee_master,
            CronTrigger(
                hour=22, minute=30, day_of_week="mon-sat", timezone=ist
            ),  # 22:30 (10:30 PM)  # 22:30 (10:30 PM)
            id="employee_master_job_22_30",
            replace_existing=True,
            misfire_grace_time=300,  # 5 minutes
        )
        scheduler.start()
        scheduler_started = True  # Set flag to True after starting
    else:
        logger.info("⚠ APScheduler for DataEngine App is already running!")
