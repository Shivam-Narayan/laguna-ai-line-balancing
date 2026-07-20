import base64
import logging
from datetime import datetime

import pandas as pd
from django.http import HttpResponse
from rest_framework import status

from apps.accounts.models import User
from apps.accounts.utils.response_handlers import error_response, success_response
from apps.data_engine.models import LocalHolidayCalendar

from ..models import Absenteeism
from ..utils import (
    generate_csv,
    generate_prediction_data,
    is_allowed_working_day,
    send_email,
)
from .prediction_orchestrator import prepare_prediction_data

logger = logging.getLogger("general")


def run_export_data():
    try:
        # Fetching data from the database dynamically
        fields = [field.name for field in LocalHolidayCalendar._meta.get_fields()]  # type: ignore
        queryset = LocalHolidayCalendar.objects.all()
        data = list(queryset.values(*fields))

        # Check if data exists
        if not data:
            return error_response(
                error="No data found to export.", status=status.HTTP_404_NOT_FOUND
            )

        # Create DataFrame from recieved data
        try:
            df = pd.DataFrame(data)
        except Exception as e:
            return error_response(
                error=f"Error creating DataFrame: {str(e)}",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Generate and return the CSV file as an HttpResponse
        try:
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = 'attachment; filename="absent.csv"'
            df.to_csv(response, index=False)  # type: ignore
            return response
        except Exception as e:
            return error_response(
                error=f"Error generating CSV file: {str(e)}",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    except Exception as e:
        # exception handler for unexpected errors
        return error_response(
            error=f"An unexpected error occurred: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def run_export_absenteeism_data():
    try:
        # Fetch all fields dynamically from the model
        fields = [field.name for field in Absenteeism._meta.get_fields()]  # type: ignore
        queryset = Absenteeism.objects.all()
        data = list(queryset.values(*fields))

        # Check if data exists
        if not data:
            return error_response(
                error="No data found to export.", status=status.HTTP_404_NOT_FOUND
            )

        # Create a DataFrame
        try:
            df = pd.DataFrame(data)
        except Exception as e:
            return error_response(
                error=f"Error creating DataFrame: {str(e)}",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Generate CSV response
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="absent.csv"'
        df.to_csv(response, index=False)  # type: ignore
        return response

    except Exception as e:
        # Handle unexpected errors
        return error_response(
            error=f"An unexpected error occurred: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def run_send_csv_via_email(email):
    try:
        # Getting the email
        if not email:
            return error_response(
                error="Email address is required.", status=status.HTTP_400_BAD_REQUEST
            )

        # Generate the CSV data in memory in utils function
        csv_data = generate_csv()

        if not csv_data:
            return error_response(
                error="No data found to export.", status=status.HTTP_404_NOT_FOUND
            )

        # Sending email with CSV as attachment
        email_subject = "Download Absenteeism CSV File"
        file_name = "absent.csv"

        from apps.absenteeism.tasks import send_email_task

        encoded_csv = base64.b64encode(csv_data.getvalue()).decode()

        send_email_task.delay(
            recipient_emails=email,
            encoded_data=encoded_csv,
            subject=email_subject,
            file_type="text/csv",
            file_name=file_name,
        )

        return success_response(
            message=f"Email is being sent to {email} in the background.",
            data={"message": "CSV file will be attached to the email."},
        )

    except Exception as e:
        return error_response(
            error=f"An unexpected error occurred: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def scheduler_prediction_data_email(line_no, forecast_period):
    try:
        # Get today's date
        current_date = datetime.now().date()
        # Check if the filter date is a working day and not a holiday
        isWorkingDay, reason = is_allowed_working_day(current_date)
        if not isWorkingDay:
            return error_response(
                error=f"Skipping for {current_date} as it is {reason}",
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info(
            "*******************************************************************"
        )
        logger.info(
            f"Running Prediction Data(Scheduler) at {str(datetime.now())} hours!"
        )
        prediction_response = prepare_prediction_data(line_no, forecast_period)

        if prediction_response.data.get("status") == "error":
            logger.info(
                f"Error ({prediction_response.status_code}) in preparing prediction data: {prediction_response.data.get('error')}"
            )
            return prediction_response
            
        excel_data = generate_prediction_data(prediction_response.data.get("data", {}))

        userEmails = list(
            User.objects.filter(send_mail=True, status=True).values_list(
                "email", flat=True
            )
        )

        subject = "Download Absenteeism File"
        file_name = f"Prediction_Data_{line_no}_{forecast_period}.xlsx"
        email_sent = send_email(
            userEmails, excel_data, subject, "text/excel", file_name
        )

        if not email_sent:
            logger.info("Error in sending email.")
            return error_response(
                error="Error in sending email.", status=status.HTTP_404_NOT_FOUND
            )

        return success_response(
            message=f"Email sent successfully to {userEmails}.",
            data={"message": "File attached to the email."},
        )
    except Exception as e:
        logger.info(f"Unexpected Error: {e}")
        return error_response(
            error=f"An unexpected error occurred ({e}).",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
