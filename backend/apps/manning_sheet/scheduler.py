from pytz import timezone
from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
scheduler_started = False  # Global flag to prevent multiple starts

def start():
    from .views import run_generate_emp_fact, run_manning_generation, run_dday_generation, fetch_and_transform_empdetails, run_generate_style_ob, run_fetch_wip_data
    from .utils import delete_old_exported_files
    global scheduler_started
    if not scheduler_started:
        print("🔄 Starting APScheduler for ManningSheet App...")

        # Set the timezone (e.g., for IST - Indian Standard Time)
        ist = timezone("Asia/Kolkata")

        # First Job - Generate Style OB Data (7:45 AM IST)
        scheduler.add_job(run_generate_style_ob,
                          CronTrigger(hour=7, minute=45, day_of_week='mon-sat', timezone=ist),  # 07:30 (7:45 AM) Monday to Saturday
                          id="run_generate_style_ob_job_7_45",
                          replace_existing=True,
                          misfire_grace_time=300,  # 5 minutes
                          kwargs={"viaAPI": False}  # Parameter
                        )
        # Second Job - Generate Manning Sheet Data (8:00 AM IST)
        scheduler.add_job(run_manning_generation,
                          CronTrigger(hour=8, minute=0, day_of_week='mon', timezone=ist),  # 08:00 (8:00 AM) Monday to Saturday #added day_of_week='mon' to run only on Mondays
                          id="run_manning_generation_job_8_00",
                          replace_existing=True,
                          misfire_grace_time=300,  # 5 minutes
                          kwargs={"viaAPI": False, "PERIOD": 60}  # Parameter
                        )
        # Third Job - Generate DDay data and send excel files via email (8:50 AM IST)
        scheduler.add_job(run_dday_generation,
                          CronTrigger(hour=8, minute=50, day_of_week='mon-sat', timezone=ist),  # 08:50 (8:50 AM) Monday to Saturday
                          id="run_generate_dday_manning_8_45_job",
                          replace_existing=True,
                          misfire_grace_time=300,  # 5 minutes
                          kwargs={"viaAPI": False}  # Parameter
                        )
        # Fourth Job - Generate DDay data and send excel files via email (12:45 PM IST)
        scheduler.add_job(run_dday_generation,
                          CronTrigger(hour=12, minute=45, day_of_week='mon-sat', timezone=ist),  # 12:45 (12:45 PM) Monday to Saturday
                          id="run_generate_dday_manning_12_45_job",
                          replace_existing=True,
                          misfire_grace_time=300,  # 5 minutes
                          kwargs={"viaAPI": False}  # Parameter
                        )
        # Fifth Job - Generate DDay data and send excel files via email (05:30 PM IST)
        scheduler.add_job(run_dday_generation,
                          CronTrigger(hour=17, minute=30, day_of_week='mon-sat', timezone=ist),  # 17:30 (05:30 PM) Monday to Saturday
                          id="run_generate_dday_manning_17_30_job",
                          replace_existing=True,
                          misfire_grace_time=300,  # 5 minutes
                          kwargs={"viaAPI": False}  # Parameter
                        )
        # Sixth Job - Generate Active Employees Data (09:45 PM)
        scheduler.add_job(fetch_and_transform_empdetails,
                          CronTrigger(hour=21, minute=45, day_of_week='mon-sat', timezone=ist),  # 21:45 (09:45 PM) Monday to Saturday
                          id="fetch_and_transform_empdetails_21_45_job",
                          replace_existing=True,
                          misfire_grace_time=300,  # 5 minutes
                        )
        # Seventh Job - Generate EMP FACT Data (10:00 PM IST)
        scheduler.add_job(run_generate_emp_fact,
                          CronTrigger(hour=22, minute=0, day_of_week='mon-sat', timezone=ist),  # 22:00 (10:00 PM) Monday to Saturday
                          id="run_generate_emp_fact_22_00_job",
                          replace_existing=True,
                          misfire_grace_time=300,  # 5 minutes
                        )
        # Eighth Job - Delete Old XLSX files (09:00 AM IST)
        scheduler.add_job(delete_old_exported_files,
                          CronTrigger(hour=9, minute=0, day_of_week='sun', timezone=ist),  # 09:00 (09:00 AM) Every Sunday
                          id="delete_old_exported_files_9_00_job",
                          replace_existing=True,
                          misfire_grace_time=300,  # 5 minutes
                          kwargs={"days_old": 7, "file_extension": ".xlsx"}  # Parameter
                        )
        # Ninth Job - Fetch WIP Data from OptaFloor API (08:00 AM IST)
        scheduler.add_job(run_fetch_wip_data,
                          CronTrigger(hour=8, minute=50, day_of_week='mon-sat', timezone=ist),
                          id="run_fetch_wip_data_job_8_50",
                          replace_existing=True,
                          misfire_grace_time=300,
                          kwargs={"viaAPI": False}
                        )
        # Tenth Job - Fetch WIP Data from OptaFloor API (12:45 PM IST)
        scheduler.add_job(run_fetch_wip_data,
                          CronTrigger(hour=12, minute=45, day_of_week='mon-sat', timezone=ist),
                          id="run_fetch_wip_data_job_12_45",
                          replace_existing=True,
                          misfire_grace_time=300,
                          kwargs={"viaAPI": False}
                        )
        # Eleventh Job - Fetch WIP Data from OptaFloor API (05:30 PM IST)
        scheduler.add_job(run_fetch_wip_data,
                          CronTrigger(hour=17, minute=30, day_of_week='mon-sat', timezone=ist),
                          id="run_fetch_wip_data_job_17_30",
                          replace_existing=True,
                          misfire_grace_time=300,
                          kwargs={"viaAPI": False}
                        )
        scheduler.start()
        scheduler_started = True  # Set flag to True after starting
    else:
        print("⚠ APScheduler for ManningSheet App is already running!")