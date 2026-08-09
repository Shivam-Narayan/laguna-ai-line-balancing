import logging
from datetime import datetime
import pandas as pd
from django.core.exceptions import ObjectDoesNotExist

from apps.absenteeism.utils import is_allowed_working_day
from apps.manning_sheet.models import ActiveEmployees, EMPFact
from config.utils import truncate_table
from ..models import EmployeeMaster

logger = logging.getLogger("general")


class EmployeeServiceError(Exception):
    """Custom exception for employee service errors."""
    pass


class EmployeeService:
    @staticmethod
    def get_operators_data(line_no):
        if not line_no:
            raise ValueError("Line is required.")

        valid_lines = [
            "line 1", "line 2", "line 3", "line 4", "line 5",
            "line 6", "line 7", "line 8", "line 9", "line 10", "all",
        ]
        if line_no.lower() not in valid_lines:
            raise ValueError('Enter valid line number(Valid Formats: "Line 1" or "line 3" or "LINE 5" or "all")')

        try:
            employee_queryset = EmployeeMaster.objects.all()

            if line_no.lower() != "all":
                employee_queryset = employee_queryset.filter(line__iexact=line_no.lower())

            if not employee_queryset.exists():
                return []

            return list(employee_queryset.values())
        except ObjectDoesNotExist:
            raise EmployeeServiceError("Employee Master Model does not exist.")
        except Exception as e:
            raise EmployeeServiceError(f"An error occured while fetching the data, {str(e)}")


class EmployeeMasterGenerator:
    def __init__(self):
        self.logger = logging.getLogger("general")

    def generate(self):
        current_date = datetime.now().date()
        is_working_day, reason = is_allowed_working_day(current_date)
        if not is_working_day:
            raise ValueError(f"Skipping for {current_date} as it is {reason}")

        self.logger.info("*******************************************************************")
        self.logger.info(f"Running Employee Master generation at {str(datetime.now())} hours!")

        try:
            active_employees_queryset = ActiveEmployees.objects.all().values()
            df_active_employees = pd.DataFrame(list(active_employees_queryset))
            df_active_employees.rename(
                columns={
                    "employee_id": "Emp No",
                    "employee_name": "Employee name",
                    "line": "Line",
                    "section": "Section",
                    "designation": "Designation",
                },
                inplace=True,
            )

            queryset = EMPFact.objects.all().values()
            df_emp_fact = pd.DataFrame(list(queryset))

            if df_active_employees.empty:
                df_active_employees = pd.DataFrame(
                    columns=["Emp No", "Employee name", "Line", "Section", "Designation"]
                )
            if df_emp_fact.empty:
                df_emp_fact = pd.DataFrame(
                    columns=["employee_id", "section", "line", "type", "operation"]
                )

            df_emp_fact["employee_id"] = pd.to_numeric(df_emp_fact["employee_id"], errors="coerce")
            df_emp_fact["section"] = df_emp_fact["section"].str.lower()
            df_emp_fact["line"] = df_emp_fact["line"].str.lower()

            df_merged = df_active_employees.merge(
                df_emp_fact, left_on=["Emp No"], right_on=["employee_id"], how="left"
            )

            df_merged["type"] = df_merged["type"].str.lower()
            df_merged["primary"] = df_merged["operation"].where(df_merged["type"] == "primary", "-").fillna("-")
            df_merged["secondary"] = df_merged["operation"].where(df_merged["type"] == "secondary", "-").fillna("-")

            df_grouped = df_merged[
                ["Emp No", "Employee name", "Line", "Section", "Designation", "primary", "secondary"]
            ].copy()

            df_grouped.rename(
                columns={
                    "Emp No": "emp_code",
                    "Employee name": "name",
                    "Line": "line",
                    "Designation": "designation",
                    "Section": "section",
                },
                inplace=True,
            )

            df_grouped["status"] = "active"
            df_grouped["line"] = df_grouped["line"].str.title()
            df_grouped["section"] = df_grouped["section"].str.title()
            df_grouped.fillna("", inplace=True)

            df_employee_master = df_grouped.groupby(
                ["emp_code", "name", "line", "designation", "section", "status"],
                as_index=False,
            ).agg(
                {
                    "primary": lambda x: ", ".join([str(v) for v in x if str(v) != "-" and str(v).lower() != "nan"]),
                    "secondary": lambda x: ", ".join([str(v) for v in x if str(v) != "-" and str(v).lower() != "nan"]),
                }
            )

            df_employee_master[["primary", "secondary"]] = df_employee_master[["primary", "secondary"]].replace("", "-")

            current_date_str = datetime.now().strftime("%Y-%m-%d")
            df_employee_master["date_of_joining"] = current_date_str
            df_employee_master["designation"] = df_employee_master["designation"].str.lower()

            records = [
                EmployeeMaster(
                    emp_code=row["emp_code"],
                    emp_name=row["name"],
                    date_of_joining=row["date_of_joining"] if row["date_of_joining"] else None,
                    line=row.get("line", "").upper(),
                    section=row.get("section", ""),
                    designation=row["designation"],
                    status=row["status"] if row["status"] in ["active", "inactive"] else "active",
                    primary=row["primary"],
                    secondary=row["secondary"],
                )
                for row in df_employee_master.to_dict("records")
            ]
            
            from django.db import transaction
            
            with transaction.atomic():
                EmployeeMaster.objects.all().delete()
                EmployeeMaster.objects.bulk_create(records, batch_size=1000)

            self.logger.info(f"Data saved successfully at {str(datetime.now())} hours!")
            self.logger.info("***************************************************\n\n")

            return len(records)
        except Exception as e:
            self.logger.error(
                f"Error in EmployeeMasterGenerator: {str(e)} at {datetime.now()} hours!",
                exc_info=True,
            )
            raise EmployeeServiceError(str(e))


# Kept for backward compatibility if other modules depend on it, 
# but they should be migrated to use the classes directly.
def run_operators_data(line_no):
    from apps.accounts.utils.response_handlers import error_response, success_response
    from rest_framework import status
    try:
        data = EmployeeService.get_operators_data(line_no)
        if not data:
             return error_response(
                 error=f"No data found for {line_no}", status=status.HTTP_200_OK
             )
        return success_response(
            message=f"Data for {line_no} fetched successfully.",
            data=data,
            status=status.HTTP_200_OK,
        )
    except ValueError as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
    except EmployeeServiceError as e:
        return error_response(error=str(e), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def run_generate_employee_master():
    from apps.accounts.utils.response_handlers import error_response, success_response
    from rest_framework import status
    try:
        generator = EmployeeMasterGenerator()
        generator.generate()
        return success_response(
            message="Employee Master data is generated successfully.",
            status=status.HTTP_200_OK,
        )
    except ValueError as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
    except EmployeeServiceError as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
