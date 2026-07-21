import logging
from celery import shared_task

logger = logging.getLogger(__name__)

@shared_task
def run_generate_style_ob_task(viaAPI=False):
    logger.info("Executing Celery Task: run_generate_style_ob_task")
    from .views import run_generate_style_ob
    return run_generate_style_ob(viaAPI)

@shared_task
def run_manning_generation_task(viaAPI=False, PERIOD=60):
    logger.info("Executing Celery Task: run_manning_generation_task")
    from .views import run_manning_generation
    return run_manning_generation(viaAPI, PERIOD)

@shared_task
def run_dday_generation_task(viaAPI=False):
    logger.info("Executing Celery Task: run_dday_generation_task")
    from .views import run_dday_generation
    return run_dday_generation(viaAPI)

@shared_task
def run_fetch_wip_data_task(viaAPI=False):
    logger.info("Executing Celery Task: run_fetch_wip_data_task")
    from .views import run_fetch_wip_data
    return run_fetch_wip_data(viaAPI)

@shared_task
def fetch_and_transform_empdetails_task():
    logger.info("Executing Celery Task: fetch_and_transform_empdetails_task")
    from .views import fetch_and_transform_empdetails
    return fetch_and_transform_empdetails()

@shared_task
def run_generate_emp_fact_task():
    logger.info("Executing Celery Task: run_generate_emp_fact_task")
    from .views import run_generate_emp_fact
    return run_generate_emp_fact()

@shared_task
def delete_old_exported_files_task(days_old=7, file_extension=".xlsx"):
    logger.info("Executing Celery Task: delete_old_exported_files_task")
    from .utils import delete_old_exported_files
    return delete_old_exported_files(days_old, file_extension)
