import logging
from datetime import datetime

import pandas as pd
from django.core.exceptions import ObjectDoesNotExist
from rest_framework import status

from apps.absenteeism.utils import (
    is_allowed_working_day,
)
from apps.accounts.utils.response_handlers import error_response, success_response
from apps.manning_sheet.models import ActiveEmployees, EMPFact
from config.utils import truncate_table

from ..models import (
    EmployeeMaster,
)

logger = logging.getLogger("general")


def run_operators_data(line_no):
    try:
        if not line_no:
            return error_response(
                error="Line is required.", status=status.HTTP_400_BAD_REQUEST
            )

        # validating the line number
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
                error='Enter valid line number(Valid Formats: "Line 1" or "line 3" or "LINE 5" or "all")',
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Query all the data from the Employee Master table
        employee_queryset = EmployeeMaster.objects.all()

        # Filtering based on the line
        if line_no.lower() != "all":
            employee_queryset = employee_queryset.filter(line__iexact=line_no.lower())

        # Handling the case where no record is present in the table
        if not employee_queryset.exists():
            return error_response(
                error=f"No data found for {line_no}", status=status.HTTP_200_OK
            )

        # converting the queryset to a list of dictionaries with specified fields
        data = list(employee_queryset.values())

        return success_response(
            message=f"Data for {line_no} fetched successfully.",
            data=data,
            status=status.HTTP_200_OK,
        )

    except ObjectDoesNotExist:
        return error_response(
            error="Employee Master Model does not exist.",
            status=status.HTTP_404_NOT_FOUND,
        )
    except Exception as e:
        return error_response(
            error=f"An error occured while fetching the data, {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def run_generate_employee_master():
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
            f"Running Employee Master generation at {str(datetime.now())} hours!"
        )
        # df_active_employees = pd.read_csv('csv_files/Active_Employees.csv')
        active_employees_queryset = ActiveEmployees.objects.all().values()  # type: ignore
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

        # Fetch data from Django model
        queryset = (
            EMPFact.objects.all().values()
        )  # Convert QuerySet to a list of dictionaries # type: ignore

        # Convert QuerySet to Pandas DataFrame
        df_emp_fact = pd.DataFrame(list(queryset))

        if df_active_employees.empty:
            df_active_employees = pd.DataFrame(
                columns=["Emp No", "Employee name", "Line", "Section", "Designation"]
            )
        if df_emp_fact.empty:
            df_emp_fact = pd.DataFrame(
                columns=["employee_id", "section", "line", "type", "operation"]
            )

        # Convert Emp No and EMPLOYEE ID to numeric
        # df_active_employees["Emp No"] = pd.to_numeric(df_active_employees["Emp No"], errors="coerce")
        df_emp_fact["employee_id"] = pd.to_numeric(
            df_emp_fact["employee_id"], errors="coerce"
        )

        # Converting values to lower case
        # df_active_employees["Department"] = df_active_employees["Department"].str.lower() # Ensure department is lowercase
        df_emp_fact["section"] = df_emp_fact[
            "section"
        ].str.lower()  # Ensure section is lowercase
        df_emp_fact["line"] = df_emp_fact[
            "line"
        ].str.lower()  # Ensure line is lowercase

        # ✅ Split "Department" into "Line" and "Section"
        # df_active_employees[["Line", "Section"]] = df_active_employees["Department"].str.extract(r"(?i)^(line \d+)\s*(.*)$", expand=True)

        # ✅ Merge using multiple conditions with lowercase values
        df_merged = df_active_employees.merge(
            df_emp_fact, left_on=["Emp No"], right_on=["employee_id"], how="left"
        )

        # Normalize operation type to lowercase
        df_merged["type"] = df_merged["type"].str.lower()

        # Assign primary and secondary operations
        df_merged["primary"] = (
            df_merged["operation"]
            .where(df_merged["type"] == "primary", "-")
            .fillna("-")
        )
        df_merged["secondary"] = (
            df_merged["operation"]
            .where(df_merged["type"] == "secondary", "-")
            .fillna("-")
        )

        # Rename and select relevant columns
        df_grouped = df_merged[
            [
                "Emp No",
                "Employee name",
                "Line",
                "Section",
                "Designation",
                "primary",
                "secondary",
            ]
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

        # Add a default status column
        df_grouped["status"] = "active"

        # Convert columns to title case
        df_grouped["line"] = df_grouped["line"].str.title()
        df_grouped["section"] = df_grouped["section"].str.title()

        df_grouped.fillna("", inplace=True)

        # Group and aggregate primary & secondary operations
        df_employee_master = df_grouped.groupby(
            ["emp_code", "name", "line", "designation", "section", "status"],
            as_index=False,
        ).agg(
            {
                "primary": lambda x: ", ".join(
                    [str(v) for v in x if str(v) != "-" and str(v).lower() != "nan"]
                ),
                "secondary": lambda x: ", ".join(
                    [str(v) for v in x if str(v) != "-" and str(v).lower() != "nan"]
                ),
            }
        )

        # Replace empty values with "-"
        df_employee_master[["primary", "secondary"]] = df_employee_master[
            ["primary", "secondary"]
        ].replace("", "-")

        current_date = datetime.now().strftime("%Y-%m-%d")
        # Convert date format to YYYY-MM-DD
        df_employee_master["date_of_joining"] = current_date
        df_employee_master["designation"] = df_employee_master[
            "designation"
        ].str.lower()

        # Process and save the data
        records = [
            EmployeeMaster(
                emp_code=row["emp_code"],
                emp_name=row["name"],
                date_of_joining=row["date_of_joining"]
                if row["date_of_joining"]
                else None,
                line=row.get(
                    "line", ""
                ).upper(),  # ✅ Convert to uppercase before adding,
                section=row.get("section", ""),
                designation=row["designation"],
                status=row["status"]
                if row["status"] in ["active", "inactive"]
                else "active",
                primary=row["primary"],
                secondary=row["secondary"],
            )
            for row in df_employee_master.to_dict("records")
        ]
        truncate_table(EmployeeMaster)
        EmployeeMaster.objects.bulk_create(records, batch_size=1000)

        logger.info(f"Data saved successfully at {str(datetime.now())} hours!")
        logger.info("***************************************************\n\n")

        return success_response(
            message="Employee Master data is generated successfully.",
            status=status.HTTP_200_OK,
        )
    except Exception as e:
        logger.error(
            f"Error in run_generate_employee_master: {str(e)} at {datetime.now()} hours!",
            exc_info=True,
        )
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
