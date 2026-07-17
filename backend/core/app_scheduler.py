from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone

# Initialize scheduler
scheduler = BackgroundScheduler()
_is_started = False  # Private flag to prevent multiple starts

def start_all_schedulers():
    """
    Centralized function to add all jobs and start the scheduler once.
    """
    global _is_started
    if _is_started:
        print("⚠ APScheduler is already running!")
        return

    print("🔄 Initializing and starting APScheduler...")
    ist = timezone("Asia/Kolkata")

    # 1. Add Absenteeism Job
    from apps.absenteeism.views import run_absenteeism_prediction
    scheduler.add_job(
        run_absenteeism_prediction,
        CronTrigger(hour=2, minute=30, timezone=ist),
        id="absenteeism_prediction_job",
        replace_existing=True
    )

    # 2. Add Data Engine Job
    from apps.data_engine.views import run_generate_employee_master
    scheduler.add_job(
        run_generate_employee_master,
        CronTrigger(hour=22, minute=30, timezone=ist),
        id="employee_master_job",
        replace_existing=True
    )

    # 3. Add Manning Sheet Job
    from apps.manning_sheet.views import run_generate_emp_fact
    scheduler.add_job(
        run_generate_emp_fact,
        CronTrigger(hour=22, minute=0, timezone=ist),
        id="emp_fact_job",
        replace_existing=True
    )

    # Start the scheduler ONCE
    scheduler.start()
    _is_started = True
    print("✅ APScheduler started successfully.")