import logging
import pandas as pd

from django.http import HttpResponse

import typing
from django.core.exceptions import ObjectDoesNotExist
from datetime import datetime
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes, authentication_classes

from ..serializers import CalendarSerializer
from apps.manning_sheet.models import ActiveEmployees, EMPFact
from apps.absenteeism.utils import send_email, convert_to_excel_data, is_allowed_working_day
from apps.accounts.authentication import MultiSessionTokenAuthentication
from apps.accounts.utils.response_handlers import success_response, error_response
from ..models import LocalHolidayCalendar, HistoricalWeather, EmployeeMaster, AttendanceMaster, PayableWorkingDays
from backend_laguna.utils import truncate_table

logger = logging.getLogger('general')

@api_view(['GET'])
def get_calendar(request):
    calendar = LocalHolidayCalendar.objects.all()
    if not calendar:
        return Response({'message': 'No data to display'}, status=status.HTTP_200_OK)
    serializer = CalendarSerializer(calendar, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def export_operators_data(request):
    try:
        line_no = request.query_params.get('line', '').strip()

        if not line_no:
            return error_response(
                error='Line is required.',
                status=status.HTTP_400_BAD_REQUEST
            )

        valid_lines = ['line 1', 'line 2', 'line 3', 'line 4', 'line 5', 'line 6', 'line 7', 'line 8', 'line 9', 'line 10', 'all']
        if line_no.lower() not in valid_lines:
            return error_response(
                error='Enter valid line number (Valid Formats: "Line 1" or "line 3" or "LINE 5" or "all")',
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get the actual field names from the EmployeeMaster model
        fields = [field.name for field in EmployeeMaster._meta.get_fields()] # type: ignore
        
        if not fields:
            return error_response(
                error='No fields found in the Employee Master Table',
                status=status.HTTP_404_NOT_FOUND
            )
        
        employee_queryset = EmployeeMaster.objects.all()
        
        if line_no.lower() != 'all':
            employee_queryset = employee_queryset.filter(line__iexact=line_no.lower())

        if not employee_queryset.exists():
            return error_response(
                error=f'No data found for {line_no}',
                status=status.HTTP_200_OK
            )

        # Column name mapping (old_name -> new_name)
        column_mapping = {
            'emp_code': 'Employee Code',
            'emp_name': 'Employee Name',
            'date_of_joining': 'Date of Joining',
            'line': 'Line',
            'section': 'Section',
            'designation': 'Designation',
            'status': 'Status',
            'primary': 'Primary',
            'secondary': 'Secondary',
        }

        # Fetch data and rename columns
        data = [
            {column_mapping.get(key, key): value for key, value in record.items()}
            for record in employee_queryset.values(*fields)
        ]

        excel_data = convert_to_excel_data(data, "Operators Data")
        
        response = HttpResponse(excel_data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="OperatorsData_{line_no}.xlsx"'
        
        return response
    
    except ObjectDoesNotExist:
        return error_response(
            error="Employee Master Model does not exist.",
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return error_response(
            error=f"An error occurred while exporting the data, {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def export_operators_data_email(request):
    try:
        recipient_email = request.query_params.get('email', '').strip()
        line_no = request.query_params.get('line', '').strip()

        if not recipient_email:
            return error_response(
                error='Recipient email is required.',
                status=status.HTTP_400_BAD_REQUEST
            )

        if not line_no:
            return error_response(
                error='Line is required.',
                status=status.HTTP_400_BAD_REQUEST
            )

        valid_lines = ['line 1', 'line 2', 'line 3', 'line 4', 'line 5', 'line 6', 'line 7', 'line 8', 'line 9', 'line 10', 'all']  
        if line_no.lower() not in valid_lines:
            return error_response(
                error='Enter valid line number (Valid Formats: "Line 1" or "line 3" or "LINE 5" or "all")',
                status=status.HTTP_400_BAD_REQUEST
            )
        
        fields = [field.name for field in typing.cast(typing.Any, EmployeeMaster)._meta.get_fields()]
        
        if not fields:
            return error_response(
                error='No fields found in the Employee Master Table',
                status=status.HTTP_404_NOT_FOUND
            )

        employee_queryset = EmployeeMaster.objects.all()
        
        if line_no.lower() != 'all':
            employee_queryset = employee_queryset.filter(line__iexact=line_no.lower())

        if not employee_queryset.exists():
            return error_response(
                error=f'No data found for {line_no}',
                status=status.HTTP_200_OK
            )
        
        # Column name mapping (old_name -> new_name)
        column_mapping = {
            'emp_code': 'Employee Code',
            'emp_name': 'Employee Name',
            'date_of_joining': 'Date of Joining',
            'line': 'Line',
            'section': 'Section',
            'designation': 'Designation',
            'status': 'Status',
            'primary': 'Primary',
            'secondary': 'Secondary',
        }

        # Fetch data and rename columns
        data = [
            {column_mapping.get(key, key): value for key, value in record.items()}
            for record in employee_queryset.values(*fields)
        ]
        
        excel_data = convert_to_excel_data(data, "Operators Data")

        # Send email with CSV file as an attachment
        subject = f"Operators Data List for {line_no}"
        file_name = f'OperatorsData_{line_no}.xlsx'
        data_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        email_sent = send_email(recipient_email, excel_data, subject, data_type, file_name=file_name)

        if email_sent:
            return Response({"message": "Email sent successfully."}, status=status.HTTP_200_OK)
        else:
            return error_response(
                error="Failed to send email.",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    except ObjectDoesNotExist:
        return error_response(
            error="Employee Master Model does not exist.",
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return error_response(
            error=f"An error occurred while exporting the data, {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
