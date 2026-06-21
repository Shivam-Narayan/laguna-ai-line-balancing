import gzip
import json
import logging
import pandas as pd
import calendar, re, io, os

from rest_framework import status
from django.db import transaction
from collections import defaultdict
from django.http import HttpResponse
from rest_framework.response import Response
from django.utils.encoding import smart_bytes
from datetime import date, timedelta, datetime
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count, Q, Case, When, IntegerField
from rest_framework.decorators import api_view, permission_classes, authentication_classes

from apps.accounts.models import User
from ..prediction import model_prediction
from backend_laguna.utils import truncate_table
from apps.manning_sheet.views import NOTIFICATION_DISPLAY_TITLE
from apps.manning_sheet.models import ManningSheetData, LoadingPlan
from apps.accounts.authentication import MultiSessionTokenAuthentication
from ..models import Absenteeism, PredictionData, AbsenteeismPrediction
from apps.manning_sheet.utils import create_bulk_push_notifications, custom_round
from apps.accounts.utils.response_handlers import error_response, success_response
from apps.data_engine.models import LocalHolidayCalendar, EmployeeMaster, AttendanceMaster
from ..absenteeism_percentage import calculate_line_percentages, get_working_days_around_date
from ..utils import generate_csv, send_email, generate_prediction_data, convert_number, update_sections, merge_duplicates, is_allowed_working_day, sum_section_counts, normalize_sections, write_absenteeism_data_to_csv, export_absenteeism_predictions_excel

logger = logging.getLogger('general')
prediction_response = {}

@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def export_data(request):
    try:
        # Fetching data from the database dynamically
        fields = [field.name for field in LocalHolidayCalendar._meta.get_fields()]  # type: ignore
        queryset = LocalHolidayCalendar.objects.all()
        data = list(queryset.values(*fields))

        # Check if data exists
        if not data:
            return error_response(
                error="No data found to export.",
                status=status.HTTP_404_NOT_FOUND
            )

        # Create DataFrame from recieved data
        try:
            df = pd.DataFrame(data)
        except Exception as e:
            return error_response(
                error=f"Error creating DataFrame: {str(e)}",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Generate and return the CSV file as an HttpResponse
        try:
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="absent.csv"'
            response['Success-Message'] = 'Absent CSV file generated successfully.'
            df.to_csv(response, index=False)  # type: ignore
            return response 
        except Exception as e:
            return error_response(
                error=f"Error generating CSV file: {str(e)}",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    except Exception as e:
        # exception handler for unexpected errors
        return error_response(
            error=f"An unexpected error occurred: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def export_absenteeism_data(request):
    try:
        # Fetch all fields dynamically from the model
        fields = [field.name for field in Absenteeism._meta.get_fields()]  # type: ignore
        queryset = Absenteeism.objects.all()
        data = list(queryset.values(*fields))

        # Check if data exists
        if not data:
            return error_response(
                error= "No data found to export.",
                status=status.HTTP_404_NOT_FOUND
            )

        # Create a DataFrame
        try:
            df = pd.DataFrame(data)
        except Exception as e:
            return error_response(
                error= f"Error creating DataFrame: {str(e)}",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Generate CSV response
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="absent.csv"'
        df.to_csv(response, index=False)  # type: ignore
        return response

    except Exception as e:
        # Handle unexpected errors
        return error_response(
            error= f"An unexpected error occurred: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def send_csv_via_email(request):
    try:
        # Getting the email from the request body
        email = request.data.get("email")
        if not email:
            return error_response(
                error="Email address is required.",
                status=status.HTTP_400_BAD_REQUEST
            )

        # Generate the CSV data in memory in utils function
        csv_data = generate_csv()

        if not csv_data:
            return error_response(
                error="No data found to export.",
                status=status.HTTP_404_NOT_FOUND
            )

        # Sending email with CSV as attachment
        email_subject = "Download Absenteeism CSV File"
        file_name="absent.csv"
        email_body = send_email(email, csv_data, email_subject, file_name=file_name)  # type: ignore

        if not email_body:
            return error_response(
                error="Error sending email, Invalid email address.",
                status=status.HTTP_404_NOT_FOUND
            )

        return success_response(
            message=f"Email sent successfully to {email}.",
            data={"message": "CSV file attached to the email."}
        )

    except Exception as e:
        return error_response(
            error=f"An unexpected error occurred: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def scheduler_prediction_data_email(line_no, forecast_period):
    try:
        # Get today's date
        current_date = datetime.now().date()
        # Check if the filter date is a working day and not a holiday
        isWorkingDay, reason = is_allowed_working_day(current_date)
        if not isWorkingDay:
            return error_response(error=f'Skipping for {current_date} as it is {reason}', status=status.HTTP_400_BAD_REQUEST)

        logger.info(f"*******************************************************************")
        logger.info(f"Running Prediction Data(Scheduler) at {str(datetime.now())} hours!")
        prediction_response = prepare_prediction_data(line_no, forecast_period)
        excel_data = generate_prediction_data(prediction_response.data['data'])

        if prediction_response.data['status'] == 'error':
            logger.info(f"Error ({prediction_response.status_code}) in preparing prediction data: {prediction_response.data['error']}")
            return prediction_response
        
        userEmails = list(User.objects.filter(send_mail=True, status=True).values_list('email', flat=True))

        subject = "Download Absenteeism File"
        file_name = f"Prediction_Data_{line_no}_{forecast_period}.xlsx"
        email_sent = send_email(userEmails, excel_data, subject, "text/excel", file_name)

        if not email_sent:
            logger.info(f"Error in sending email.")
            return error_response(error="Error in sending email.", status=status.HTTP_404_NOT_FOUND)

        return success_response(message=f"Email sent successfully to {userEmails}.", data={"message": "File attached to the email."})
    except Exception as e:
        logger.info(f"Unexpected Error: {e}")
        return error_response(error=f"An unexpected error occurred ({e}).", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
