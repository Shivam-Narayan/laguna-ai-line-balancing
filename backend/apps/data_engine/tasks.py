import logging
from celery import shared_task

logger = logging.getLogger(__name__)

@shared_task
def run_generate_employee_master_task():
    logger.info("Executing Celery Task: run_generate_employee_master_task")
    from .views import run_generate_employee_master
    return run_generate_employee_master()
