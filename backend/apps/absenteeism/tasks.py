import logging

from celery import shared_task

from .services.export_service import scheduler_prediction_data_email
from .services.prediction_orchestrator import run_absenteeism_prediction
from .services.report_service import (
    fetch_absenteeism_report_data,
    run_absenteeism_report,
    save_absenteeism_report,
)

logger = logging.getLogger(__name__)


@shared_task
def run_absenteeism_prediction_task(viaAPI=False):
    logger.info("Executing Celery Task: run_absenteeism_prediction_task")
    return run_absenteeism_prediction(viaAPI)


@shared_task
def scheduler_prediction_data_email_task(lines, forecast_period):
    logger.info("Executing Celery Task: scheduler_prediction_data_email_task")
    return scheduler_prediction_data_email(lines, forecast_period)


@shared_task
def save_absenteeism_report_task():
    logger.info("Executing Celery Task: save_absenteeism_report_task")
    return save_absenteeism_report()


@shared_task
def fetch_absenteeism_report_data_task():
    logger.info("Executing Celery Task: fetch_absenteeism_report_data_task")
    return fetch_absenteeism_report_data()


@shared_task
def run_absenteeism_report_task(viaAPI=False):
    logger.info("Executing Celery Task: run_absenteeism_report_task")
    return run_absenteeism_report(viaAPI)


@shared_task
def send_email_task(
    recipient_emails, encoded_data, subject, file_type, file_name, test=False
):
    logger.info("Executing Celery Task: send_email_task")
    from .utils.email_utils import send_email

    return send_email(
        recipient_emails=recipient_emails,
        data=None,
        subject=subject,
        type=file_type,
        file_name=file_name,
        test=test,
        encoded_data=encoded_data,
    )
