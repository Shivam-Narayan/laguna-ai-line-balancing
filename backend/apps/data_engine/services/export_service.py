import logging
import typing

from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse
from rest_framework import status
from rest_framework.response import Response

from apps.absenteeism.utils import (
    convert_to_excel_data,
)
from apps.accounts.utils.response_handlers import error_response

from ..models import (
    EmployeeMaster,
    LocalHolidayCalendar,
)
from ..serializers import CalendarSerializer

logger = logging.getLogger("general")


def run_get_calendar():
    try:
        calendar = LocalHolidayCalendar.objects.all()
        if not calendar:
            return Response(
                {"message": "No data to display"}, status=status.HTTP_200_OK
            )
        serializer = CalendarSerializer(calendar, many=True)
        return Response(serializer.data)
    except Exception as e:
        return error_response(
            error=str(e), status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def run_export_operators_data(line_no):
    try:
        if not line_no:
            return error_response(
                error="Line is required.", status=status.HTTP_400_BAD_REQUEST
            )

        valid_lines = [
            "line 1",
            "line 2",
            "line 3",
            "line 4",
            "line 5",
            "line 6",
            "line 7",
            "line 8",
            "line 9",
            "line 10",
            "all",
        ]
        if line_no.lower() not in valid_lines:
            return error_response(
                error='Enter valid line number (Valid Formats: "Line 1" or "line 3" or "LINE 5" or "all")',
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get the actual field names from the EmployeeMaster model
        fields = [field.name for field in EmployeeMaster._meta.get_fields()]  # type: ignore

        if not fields:
            return error_response(
                error="No fields found in the Employee Master Table",
                status=status.HTTP_404_NOT_FOUND,
            )

        employee_queryset = EmployeeMaster.objects.all()

        if line_no.lower() != "all":
            employee_queryset = employee_queryset.filter(line__iexact=line_no.lower())

        if not employee_queryset.exists():
            return error_response(
                error=f"No data found for {line_no}", status=status.HTTP_200_OK
            )

        # Column name mapping (old_name -> new_name)
        column_mapping = {
            "emp_code": "Employee Code",
            "emp_name": "Employee Name",
            "date_of_joining": "Date of Joining",
            "line": "Line",
            "section": "Section",
            "designation": "Designation",
            "status": "Status",
            "primary": "Primary",
            "secondary": "Secondary",
        }

        # Fetch data and rename columns
        data = [
            {column_mapping.get(key, key): value for key, value in record.items()}
            for record in employee_queryset.values(*fields)
        ]

        excel_data = convert_to_excel_data(data, "Operators Data")

        response = HttpResponse(
            excel_data,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="OperatorsData_{line_no}.xlsx"'
        )

        return response

    except ObjectDoesNotExist:
        return error_response(
            error="Employee Master Model does not exist.",
            status=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        return error_response(
            error=f"An error occurred while exporting the data, {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def run_export_operators_data_email(recipient_email, line_no):
    try:
        if not recipient_email or not line_no:
            return error_response(
                error="Recipient email is required.", status=status.HTTP_400_BAD_REQUEST
            )

        valid_lines = [
            "line 1",
            "line 2",
            "line 3",
            "line 4",
            "line 5",
            "line 6",
            "line 7",
            "line 8",
            "line 9",
            "line 10",
            "all",
        ]
        if line_no.lower() not in valid_lines:
            return error_response(
                error='Enter valid line number (Valid Formats: "Line 1" or "line 3" or "LINE 5" or "all")',
                status=status.HTTP_400_BAD_REQUEST,
            )

        fields = [
            field.name
            for field in typing.cast(typing.Any, EmployeeMaster)._meta.get_fields()
        ]

        if not fields:
            return error_response(
                error="No fields found in the Employee Master Table",
                status=status.HTTP_404_NOT_FOUND,
            )

        employee_queryset = EmployeeMaster.objects.all()

        if line_no.lower() != "all":
            employee_queryset = employee_queryset.filter(line__iexact=line_no.lower())

        if not employee_queryset.exists():
            return error_response(
                error=f"No data found for {line_no}", status=status.HTTP_200_OK
            )

        # Column name mapping (old_name -> new_name)
        column_mapping = {
            "emp_code": "Employee Code",
            "emp_name": "Employee Name",
            "date_of_joining": "Date of Joining",
            "line": "Line",
            "section": "Section",
            "designation": "Designation",
            "status": "Status",
            "primary": "Primary",
            "secondary": "Secondary",
        }

        # Fetch data and rename columns
        data = [
            {column_mapping.get(key, key): value for key, value in record.items()}
            for record in employee_queryset.values(*fields)
        ]

        excel_data = convert_to_excel_data(data, "Operators Data")

        # Send email with CSV file as an attachment
        subject = f"Operators Data List for {line_no}"
        file_name = f"OperatorsData_{line_no}.xlsx"
        data_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        import base64

        from apps.absenteeism.tasks import send_email_task

        encoded_excel = base64.b64encode(excel_data.getvalue()).decode()

        send_email_task.delay(
            recipient_emails=recipient_email,
            encoded_data=encoded_excel,
            subject=subject,
            file_type=data_type,
            file_name=file_name,
        )

        return Response(
            {"message": "Email will be sent successfully in the background."},
            status=status.HTTP_200_OK,
        )

    except ObjectDoesNotExist:
        return error_response(
            error="Employee Master Model does not exist.",
            status=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        return error_response(
            error=f"An error occurred while exporting the data, {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
