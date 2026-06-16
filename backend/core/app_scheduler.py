from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone

scheduler = BackgroundScheduler()
scheduler_started = False  # Global flag to prevent multiple starts

def absenteeismScheduler():
    from apps.absenteeism.views import run_absenteeism_prediction
    global scheduler_started
    if not scheduler_started:
        print("🔄 Starting APScheduler for Absenteeism App...")

        # Set the timezone (e.g., for IST - Indian Standard Time)
        ist = timezone("Asia/Kolkata")
        scheduler.add_job(run_absenteeism_prediction,
                          CronTrigger(hour=2, minute=30,  timezone=ist),  # 02:30 (02:30 AM)
                          id="absenteeis_prediction_job",
                          replace_existing=True
                        )
        scheduler.start()
        scheduler_started = True  # Set flag to True after starting
    else:
        print("⚠ APScheduler for Absenteeism App is already running!")




def dataEngineScheduler():
    from apps.dataEngine.views import run_generate_employee_master
    global scheduler_started
    if not scheduler_started:
        print("🔄 Starting APScheduler for DataEngine App...")

        # Set the timezone (e.g., for IST - Indian Standard Time)
        ist = timezone("Asia/Kolkata")
        scheduler.add_job(run_generate_employee_master,
                          CronTrigger(hour=22, minute=30, timezone=ist),  # 22:30 (10:30 PM)
                          id="employee_master_job",
                          replace_existing=True
                        )
        scheduler.start()
        scheduler_started = True  # Set flag to True after starting
    else:
        print("⚠ APScheduler for DataEngine App is already running!")



def manningSheetScheduler():
    from apps.manning_sheet.views import run_generate_emp_fact
    global scheduler_started
    if not scheduler_started:
        print("🔄 Starting APScheduler for ManningSheet App...")

        # Set the timezone (e.g., for IST - Indian Standard Time)
        ist = timezone("Asia/Kolkata")
        scheduler.add_job(run_generate_emp_fact,
                          CronTrigger(hour=22, minute=0, timezone=ist),  # 22:00 (10 PM)
                          id="emp_fact_job",
                          replace_existing=True
                        )
        scheduler.start()
        scheduler_started = True  # Set flag to True after starting
    else:
        print("⚠ APScheduler for ManningSheet App is already running!")