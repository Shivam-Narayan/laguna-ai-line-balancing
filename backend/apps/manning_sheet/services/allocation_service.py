import json
import logging
import os

from django.db.models import FloatField, Func
from django.shortcuts import get_object_or_404
from rest_framework import status

from apps.accounts.utils.response_handlers import error_response, success_response

from ..models import (
    DDayData,
    EmployeesOnHold,
    ManningSheetData,
)
from ..utils import (
    remove_by_employee_id,
)

logger = logging.getLogger("general")

CHUNK_SIZE = 1000

os.makedirs("exports", exist_ok=True)
COMPANY_CODE = 843

NOTIFICATION_DISPLAY_TIME = {
    "dday_8_50": "8:50 AM",
    "dday_12_45": "12:45 PM",
    "dday_5_30": "5:30 PM",
}

NOTIFICATION_DISPLAY_TITLE = {
    "dday_8_50": "D-Day 8:50 AM Allocation Data",
    "dday_12_45": "D-day 12:45 PM Allocation Data",
    "dday_5_30": "D-Day 5:30 PM Allocation Data",
    "manning_sheet": "Manning Sheet Allocation Data",
    "absenteeism_prediction": "Absenteeism Prediction Data",
}


class Round(Func):
    function = "ROUND"
    arity = 2
    output_field = FloatField()


def run_update_allocated_employees(final_allocation, dday_id):
    try:
        dday_instance = get_object_or_404(DDayData, pk=dday_id)
        dday_instance.final_allocation = final_allocation
        dday_instance.save()
        return success_response(
            message="Successully updated the allocation employee.",
            status=status.HTTP_200_OK,
        )
    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)


def run_update_employee_on_hold_individual(
    preferred_employee, allocated_capacity, manning_id
):
    try:
        employee_name = None
        employee_id = 0

        if preferred_employee:
            for emp_id, emp_name in preferred_employee.items():
                employee_id = emp_id
                employee_name = emp_name

        manning_instance = get_object_or_404(ManningSheetData, pk=manning_id)

        try:
            employees_on_hold_instance = EmployeesOnHold.objects.get(
                line=manning_instance.line,
                section=manning_instance.section,
                date=manning_instance.planned_dates,
            )

            manning_instance.allocated_emp_id = employee_id
            manning_instance.allocated_emp_name = employee_name
            if allocated_capacity:
                manning_instance.allocated_capacity = allocated_capacity

            preferred_employees = json.loads(
                employees_on_hold_instance.preferred_employees
            )
            if preferred_employee in preferred_employees:
                preferred_employees = remove_by_employee_id(
                    preferred_employees, employee_id
                )
                employees_on_hold_instance.preferred_employees = json.dumps(
                    preferred_employees
                )
                employees_on_hold_instance.count = (
                    len(preferred_employees) if preferred_employees else 0
                )
                manning_instance.save()
                employees_on_hold_instance.save()
                return success_response(
                    message="Successully updated the allocation of an employee.",
                    status=status.HTTP_200_OK,
                )
            else:
                return error_response(
                    error="Employee not found in the preferred employees list.",
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except EmployeesOnHold.DoesNotExist:
            return error_response(
                error="No EmployeesOnHold instance found for the given line, section, and date.",
                status=status.HTTP_404_NOT_FOUND,
            )

    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)


def run_update_employee_on_hold(multiple_ids):
    try:
        if not multiple_ids:
            return error_response(
                error="No data found in multiple_IDs.",
                status=status.HTTP_400_BAD_REQUEST,
            )

        manning_ids = [
            entry.get("manning_id") for entry in multiple_ids if entry.get("manning_id")
        ]
        manning_instances = ManningSheetData.objects.in_bulk(manning_ids)
        manning_to_update = []

        for entry in multiple_ids:
            preferred_employee = entry.get("preferred_employee")
            allocated_capacity = entry.get("allocated_capacity")
            manning_id = entry.get("manning_id")

            if not (preferred_employee and manning_id):
                continue  # Skip this entry if essential data is missing

            employee_name = None
            employee_id = 0

            for emp_id, emp_name in preferred_employee.items():
                employee_id = emp_id
                employee_name = emp_name

            manning_instance = manning_instances.get(manning_id)
            if not manning_instance:
                return error_response(
                    error=f"ManningSheetData with id {manning_id} not found.",
                    status=status.HTTP_404_NOT_FOUND,
                )

            try:
                employees_on_hold_instance = EmployeesOnHold.objects.get(
                    line=manning_instance.line,
                    section=manning_instance.section,
                    date=manning_instance.planned_dates,
                )

                manning_instance.allocated_emp_id = employee_id
                manning_instance.allocated_emp_name = employee_name
                if allocated_capacity:
                    manning_instance.allocated_capacity = allocated_capacity

                preferred_employees = json.loads(
                    employees_on_hold_instance.preferred_employees
                )

                if any(
                    str(employee_id) == str(eid)
                    for eid in map(
                        str, [list(emp.keys())[0] for emp in preferred_employees]
                    )
                ):
                    manning_to_update.append(manning_instance)
                else:
                    return error_response(
                        error=f"Employee {employee_id} not found in preferred employees list for manning_id {manning_id}.",
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            except EmployeesOnHold.DoesNotExist:
                return error_response(
                    error=f"No EmployeesOnHold instance found for manning_id {manning_id}.",
                    status=status.HTTP_404_NOT_FOUND,
                )

        if manning_to_update:
            ManningSheetData.objects.bulk_update(
                manning_to_update,
                ["allocated_emp_id", "allocated_emp_name", "allocated_capacity"],
            )

        return success_response(
            message="Successfully updated the allocation of all employees.",
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)


def run_update_allocated_capacity(allocated_capacity, manning_id):
    try:
        # Validate required fields
        if not allocated_capacity or not manning_id:
            return error_response(
                error='"allocated_capacity" and "manning_id" are required.',
                status=status.HTTP_400_BAD_REQUEST,
            )

        manning_instance = get_object_or_404(ManningSheetData, pk=manning_id)

        try:
            manning_instance.allocated_capacity = allocated_capacity
            manning_instance.save()
            return success_response(
                message="Successully updated the allocated capacity of an employee.",
                status=status.HTTP_200_OK,
            )
        except EmployeesOnHold.DoesNotExist:
            return error_response(
                error="Error in allocating capacity to an employee.",
                status=status.HTTP_404_NOT_FOUND,
            )

    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
