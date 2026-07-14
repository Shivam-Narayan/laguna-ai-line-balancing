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
from .prediction_service import model_prediction
from config.utils import truncate_table
from apps.manning_sheet.models import ManningSheetData, LoadingPlan
from apps.accounts.api.authentication import CookieJWTAuthentication
from ..models import Absenteeism, PredictionData, AbsenteeismPrediction
from apps.manning_sheet.utils import create_bulk_push_notifications, custom_round
from apps.accounts.utils.response_handlers import error_response, success_response
from apps.data_engine.models import LocalHolidayCalendar, EmployeeMaster, AttendanceMaster
from .prediction_service import model_prediction
from .absenteeism_percentage_service import calculate_line_percentages, get_working_days_around_date
from ..utils import generate_csv, send_email, generate_prediction_data, convert_number, update_sections, merge_duplicates, is_allowed_working_day, sum_section_counts, normalize_sections, write_absenteeism_data_to_csv, export_absenteeism_predictions_excel

logger = logging.getLogger('general')
prediction_response = {}

@api_view(['GET'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_today_absenteeism_report(request):
    try:
        viaAPI=True
        excel_data, file_name = run_absenteeism_report(viaAPI)  # Call the function without needing a request
        response = HttpResponse(excel_data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')  # type: ignore
        response['Content-Disposition'] = f'attachment; filename="{file_name}"'
        return response
    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def run_absenteeism_report(viaAPI):
    try:
        # Get today's date
        current_date = datetime.now().date()
        # Check if the filter date is a working day and not a holiday
        isWorkingDay, reason = is_allowed_working_day(current_date)
        if not isWorkingDay:
            return error_response(error=f'Skipping for {current_date} as it is {reason}', status=status.HTTP_400_BAD_REQUEST)

        if not viaAPI:
            logger.info(f"*******************************************************************")
            logger.info(f"Running Absenteeism Report generation at {str(datetime.now())} hours!")

        # Main execution
        today = date.today()
        formatted_date = today.strftime("%Y_%m_%d")
        file_name=f"Absenteeism_Report_{formatted_date}.csv"

        # Define the path to the absenteeism report file
        absenteeism_report = "exports/absenteeism_data.json"

        # Check if the absenteeism report file exists
        if not os.path.exists(absenteeism_report):
            return error_response(error='Absenteeism report not found.', status=status.HTTP_404_NOT_FOUND)

        # Load the absenteeism report data
        with open(absenteeism_report, "r") as f:
            allLineData = json.load(f)
        csv_buffer, file_name = write_absenteeism_data_to_csv(allLineData, file_name)

        if not viaAPI:
            # userEmails = list(User.objects.filter(send_mail=True, status=True).values_list('email', flat=True))
            userEmails = [
                # Laguna email ids
                "smithas@laguna-clothing.com", 
                "manish_sinha@laguna-clothing.com", 
                "sundaram_bm@laguna-clothing.com", 
                "sadashiv_naik@laguna-clothing.com", 
                "ravi.prakash@cieltextile.com", 
                "alok_kumar@laguna-clothing.com", 
                "naveen_kumar@laguna-clothing.com",

                # Ascendum email ids
                "amrendra.pathak@ascendum.com",
                # "vatsal.vohera@ascendum.com",
                "nayankumar.ghosh@ascendum.com",
                "raghavendra.nadgir@ascendum.com",
                "kavyashree.v@ascendum.com"
            ]

            subject = "Download Absenteeism Report"
            # email_sent = send_email(userEmails, excel_data, subject, "text/excel", file_name)
            email_sent = send_email(userEmails, csv_buffer, subject, "text/csv", file_name)

            if not email_sent:
                logger.info(f"Error in sending email.")
                return error_response(error="Error in sending email.", status=status.HTTP_404_NOT_FOUND)

            logger.info(f"Data sent via mail successfully at {str(datetime.now())} hours!")
            logger.info(f"***************************************************\n\n")

            return success_response(message="Absenteeism Report sent via mail successfully.", status=status.HTTP_200_OK)
        else:
            return csv_buffer, file_name
    except Exception as e:
        logger.info(f"Error in run_absenteeism_report: {str(e)}")
        logger.error(f"Error in run_absenteeism_report: {str(e)} at {datetime.now()} hours!", exc_info=True)
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)


def save_absenteeism_report():
    try:
        next_day = datetime.now().date() + timedelta(days=1)  # Start from tomorrow
        # Keep incrementing until a valid working day is found
        while True:
            isWorkingDay, reason = is_allowed_working_day(next_day)
            if isWorkingDay:
                break
            next_day += timedelta(days=1)

        allLinesData = {
            'prediction_date': next_day.strftime("%Y-%m-%d"),
            'generated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        for line in range(1, 11):
            individual_line = f"line {line}"
            # Call recursively but don't return, just store results
            response_data = prepare_prediction_data(individual_line, 1)
            response_data = response_data.data

            # If the response is valid, extract the prediction data
            if isinstance(response_data, tuple):
                continue  # Skip invalid responses

            if 'data' in response_data:
                absenteeism_percentage = response_data['data'].get('absenteeism_percentage', 0)
                total_operators = response_data['data'].get('total_operators', [])
                total_employee_count = {item['section']: item['count'] for item in total_operators}
                total_operators_gap = response_data['data'].get('total_operators_gap', [])
                allLinesData[individual_line] = {  # type: ignore
                    'predicted_absenteeism_percentage': absenteeism_percentage,
                    'total_employee_count': total_employee_count,
                    'predicted_absent_count': total_operators_gap
                }

        with open("exports/absenteeism_data.json", "w") as f:
            json.dump(allLinesData, f, indent=2)

        return success_response(message="Absenteeism Report saved successfully.", status=status.HTTP_200_OK)
    except Exception as e:
        logger.info(f"Error in run_absenteeism_report: {str(e)}")
        logger.error(f"Error in run_absenteeism_report: {str(e)} at {datetime.now()} hours!", exc_info=True)
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)


def fetch_absenteeism_report_data():
    try:
        today = date.today()

        # Define the path to the absenteeism report file
        absenteeism_report = "exports/absenteeism_data.json"

        # Check if the absenteeism report file exists
        if not os.path.exists(absenteeism_report):
            return error_response(error='Absenteeism report not found.', status=status.HTTP_404_NOT_FOUND)

        # Load the absenteeism report data
        with open(absenteeism_report, "r") as f:
            absenteeism_data = json.load(f)

        # Check if the data is empty
        if not absenteeism_data:
            return error_response(error='No absenteeism data found.', status=status.HTTP_404_NOT_FOUND)
        
        section_order = ['Assembly', 'Back', 'Collar', 'Cuff', 'Front', 'Sleeve']

        attendance_filter = {'attendance_date': today}

        for line in range(1, 11):
            individual_line = f"line {line}"
            attendance_filter['line'] = individual_line.title()  # type: ignore

            attendance_summary = (
                AttendanceMaster.objects
                .filter(**attendance_filter)
                .exclude(section='nan')
                .values('section')
                .annotate(
                    present=Count(Case(When(status='P', then=1), output_field=IntegerField())),
                    absent=Count(Case(When(~Q(status='P'), then=1), output_field=IntegerField())),
                )
            )
            actual_present_count = []
            actual_absent_count = []

            for entry in attendance_summary:
                actual_present_count.append({'section': entry['section'], 'count': entry['present']})
                actual_absent_count.append({'section': entry['section'], 'count': entry['absent']})

            actual_present_count = sorted(actual_present_count, key=lambda x: section_order.index(x['section']))
            actual_absent_count = sorted(actual_absent_count, key=lambda x: section_order.index(x['section']))

            present_emp_count = sum(item['count'] for item in actual_present_count)
            absent_emp_count = sum(item['count'] for item in actual_absent_count)
            total_emp_count = present_emp_count + absent_emp_count

            # Avoid division by zero
            if total_emp_count > 0:
                actual_absenteeism_percentage = round(((absent_emp_count / total_emp_count) * 100), 1)
            else:
                actual_absenteeism_percentage = 0


            absenteeism_data[individual_line]['actual_absent_count'] = actual_absent_count
            absenteeism_data[individual_line]['actual_absenteeism_percentage'] = actual_absenteeism_percentage

        with open("exports/absenteeism_data.json", "w") as f:
            json.dump(absenteeism_data, f, indent=2)

        return success_response(message='Absenteeism report data fetched successfully.', data=absenteeism_data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.info(f"Error in fetch_absenteeism_report_data: {str(e)}")
        logger.error(f"Error in fetch_absenteeism_report_data: {str(e)} at {datetime.now()} hours!", exc_info=True)
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)


def absenteeism_report(line_no, today):
    try:
        section_order = ['Assembly', 'Back', 'Collar', 'Cuff', 'Front', 'Sleeve']

        absenteeism_filter = {'datetime': today, 'forecast_period': 7}
        attendance_filter = {'attendance_date': today}
        employee_filter = Q()

        if line_no.lower() != 'all':
            absenteeism_filter['line'] = line_no.upper()
            attendance_filter['line'] = line_no.title()
            employee_filter = Q(line=line_no.upper())

        total_emp_count = EmployeeMaster.objects.filter(employee_filter).count()
        if total_emp_count == 0:
            return None, None, error_response(error='No employees found.', status=status.HTTP_404_NOT_FOUND)


        total_employee_queryset = (
            EmployeeMaster.objects
            .filter(employee_filter)
            .values('section')
            .annotate(count=Count('emp_code'))
        )
        total_employee_list = list(total_employee_queryset)
        total_employee_list = sorted(total_employee_list, key=lambda x: section_order.index(x['section']))

        total_employee_count = {
            item['section']: item['count']
            for item in total_employee_list
        }

        predicted_absent_queryset = (
            AbsenteeismPrediction.objects
            .filter(**absenteeism_filter)
            .exclude(section='nan')
            .values('section')
            .annotate(count=Sum('predicted_absent_count'))
        )
        # Convert 'section' to title case
        for item in predicted_absent_queryset:
            item['section'] = item['section'].title()
        predicted_absent_count = sorted(predicted_absent_queryset, key=lambda x: section_order.index(x['section']))

        # Calculate absenteeism percentage by section
        predicted_absenteeism_percentage = {
            item['section']: round((item['count'] / total_employee_count[item['section']] * 100), 1) if total_emp_count else 0
            for item in predicted_absent_queryset
        }

        actual_absent_queryset = (
            AttendanceMaster.objects
            .filter(**attendance_filter)
            .exclude(section='nan')  # Optional: ignore 'nan' values
            .values('section')
            .annotate(
                count=Count(Case(When(~Q(status='P'), then=1)))
            )
        )
        actual_absent_count = sorted(actual_absent_queryset, key=lambda x: section_order.index(x['section']))

        # Calculate absenteeism percentage by section
        actual_absenteeism_percentage = {
            item['section']: round((item['count'] / total_employee_count[item['section']] * 100), 1) if total_emp_count else 0
            for item in actual_absent_count
        }

        response = {
            "total_employee_count": total_employee_count,
            "predicted_absent_count": predicted_absent_count,
            "predicted_absenteeism_percentage": predicted_absenteeism_percentage,
            "actual_absent_count": actual_absent_count,
            "actual_absenteeism_percentage": actual_absenteeism_percentage
        }

        return success_response(message='Data fetched successfully', data=response, status=status.HTTP_200_OK)

    except Exception as e:
        logger.info(f"Error in prepare_prediction_data: {str(e)}")
        return error_response(error=f"Unknown error: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
