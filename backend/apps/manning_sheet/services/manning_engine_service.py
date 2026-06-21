import os
import gzip
import pytz
import json
import logging
import requests
import numpy as np
import pandas as pd
import xml.etree.ElementTree as ET

from django.utils import timezone
from django.db import transaction
from collections import defaultdict
from django.utils.encoding import smart_bytes
from django.shortcuts import get_object_or_404
from django.http import HttpResponse, FileResponse
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError, DatabaseError
from django.db.models import Func, FloatField, Count, Sum, Case, When, Q

from io import BytesIO
from rest_framework import status
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, date, time
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes, authentication_classes

from apps.accounts.authentication import MultiSessionTokenAuthentication
from apps.accounts.utils.response_handlers import error_response, success_response

from backend_laguna.utils import truncate_table
from ..loading_plan_optimization import process_df
from ..loading_plan import redistribute_production_plan
from apps.absenteeism.utils import send_email, is_allowed_working_day, convert_number
from ..manning_generation_multiprocessing import run_manning_allocation, filter_by_date_ranges, process_grouped_results, map_factory_floor_for_results, create_manning_dataframes, process_general_info, map_factory_floor
from ..dday_generation import get_ist_time, run_intraday_allocation_enhanced, generate_reallocation_report, analyze_unallocated_patterns, print_unallocated_summary, generate_unallocated_report_safe, analyze_allocation_gaps, perform_final_allocation_pass
from ..utils import fetch_skill_matrix, fetch_operations, merge_dataframe, export_to_excel, export_json_to_excel, fetch_style_ob, merge_machine_sam, process_styles, renaming_columns_style_ob, fetch_wip, custom_round, create_bulk_push_notifications, get_notification_type_by_time, fetch_dday_data, fetch_attendance_data, remove_by_employee_id, transform_unallocated_to_on_hold_from_dict, update_sections, remove_duplicate_employee_dicts, fetchMaxQtyDday

from ..models import PushNotification
from apps.accounts.models import EndpointLock, User
from apps.absenteeism.models import PredictionData, AbsenteeismPrediction
from apps.data_engine.models import AttendanceMaster, EmployeeMaster, LocalHolidayCalendar, PayableWorkingDays
from ..models import StyleOB, LoadingPlan, EMPFact, ManningSheetData, DDayData, ManningGeneralInfo, WIPData, ActiveEmployees, UnallocatedEmployees, EmployeesOnHold

logger = logging.getLogger('general')

CHUNK_SIZE = 1000

os.makedirs("exports", exist_ok=True)
COMPANY_CODE = 843

NOTIFICATION_DISPLAY_TIME = {
    "dday_8_50": "8:50 AM",
    "dday_12_45": "12:45 PM",
    "dday_5_30": "5:30 PM",
}

NOTIFICATION_DISPLAY_TITLE = {
    'dday_8_50': 'D-Day 8:50 AM Allocation Data',
    'dday_12_45': 'D-day 12:45 PM Allocation Data',
    'dday_5_30': 'D-Day 5:30 PM Allocation Data',
    'manning_sheet': 'Manning Sheet Allocation Data',
    'absenteeism_prediction': 'Absenteeism Prediction Data',
}

class Round(Func):
    function = 'ROUND'
    arity = 2
    output_field = FloatField()

@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated]) 
def manning_sheet_generation(request):
    try:
        ManningSheetData.objects.all().delete()
        manning_sheet_df = {}

        queryset_lp = LoadingPlan.objects.all().values()
        # Convert QuerySet to DataFrame
        df_load_plan_transformed = pd.DataFrame.from_records(queryset_lp)
        
        df_unique_smv = df_load_plan_transformed.drop_duplicates(subset=["style", "buyer"])
        df_unique_smv = df_unique_smv[["style", "buyer", "smv"]]
        
        #Loading StyleOB data
        queryset_style = StyleOB.objects.all().values()
        df_Style_OB = pd.DataFrame.from_records(queryset_style)
        df_Style_OB['code'] = df_Style_OB['code'].str.replace(" ", "", regex=True)
        
        #Loading StyleOB data
        queryset_empfact = EMPFact.objects.all().values()
        emp_fact_df = pd.DataFrame.from_records(queryset_empfact)
        emp_fact_df['code'] = emp_fact_df['code'].str.replace(" ", "", regex=True)

        # df_active_employees = pd.read_csv('csv_files/Active_Employees.csv')
        active_employees_queryset = ActiveEmployees.objects.all().values()
        df_active_employees = pd.DataFrame(list(active_employees_queryset))
        df_active_employees.rename(columns={'employee_id': 'Emp No', 'employee_name': 'Employee name', 'line': 'Line', 'section': 'Section', 'designation': 'Designation'}, inplace=True)

        emp_fact_df = emp_fact_df[emp_fact_df["employee_id"].isin(df_active_employees["Emp No"])]
        emp_fact_df = emp_fact_df[emp_fact_df["type"].isin(["Primary", "Secondary"])]

        df_load_plan_transformed["planned_dates"] = pd.to_datetime(df_load_plan_transformed["planned_dates"]).dt.normalize()
        
        # Define today's date
        today = datetime.today().date()

        # Define future date thresholds
        date_thresholds = {
            "60_days": (today + timedelta(days=60)),
            "30_days": (today + timedelta(days=30)),
            "7_days": (today + timedelta(days=7)),
            "1_day": (today + timedelta(days=1)),
        }
        df_load_plan_transformed["planned_dates"] = pd.to_datetime(df_load_plan_transformed["planned_dates"], errors='coerce')
        df_load_plan_transformed["planned_dates"] = df_load_plan_transformed["planned_dates"].dt.date    # Create four separate filtered DataFrames

        # Exclude today from all except df_0_day
        df_60_days = df_load_plan_transformed[
            (df_load_plan_transformed["planned_dates"] > today) &  # Changed `>=` to `>`
            (df_load_plan_transformed["planned_dates"] <= date_thresholds["60_days"])
        ]
        df_30_days = df_load_plan_transformed[
            (df_load_plan_transformed["planned_dates"] > today) &  # Changed `>=` to `>`
            (df_load_plan_transformed["planned_dates"] <= date_thresholds["30_days"])
        ]
        df_7_days = df_load_plan_transformed[
            (df_load_plan_transformed["planned_dates"] > today) &  # Changed `>=` to `>`
            (df_load_plan_transformed["planned_dates"] <= date_thresholds["7_days"])
        ]
        df_1_day = df_load_plan_transformed[
            (df_load_plan_transformed["planned_dates"] > today) &  # Changed `>=` to `>`
            (df_load_plan_transformed["planned_dates"] <= date_thresholds["1_day"])
        ]

        # today = pd.Timestamp.today().normalize()
        df_0_day = df_load_plan_transformed[df_load_plan_transformed["planned_dates"] == today]

        # Group by ORDER NO, MERCHANT, STYLE and sum Planned Qty for each period
        result_60_days = df_60_days.groupby(["oc_no", "order_no", "buyer", "style", "fabric_article", "line", "week", "planned_dates"], as_index=False)["planned_qty"].sum()
        result_60_days = result_60_days.rename(columns={'fabric_article': 'color'})
        result_30_days = df_30_days.groupby(["oc_no", "order_no", "buyer", "style", "fabric_article", "line", "week", "planned_dates"], as_index=False)["planned_qty"].sum()
        result_30_days = result_30_days.rename(columns={'fabric_article': 'color'})
        result_7_days = df_7_days.groupby(["oc_no", "order_no", "buyer", "style", "fabric_article", "line", "week", "planned_dates"], as_index=False)["planned_qty"].sum()
        result_7_days = result_7_days.rename(columns={'fabric_article': 'color'})
        result_1_day = df_1_day.groupby(["oc_no", "order_no", "buyer", "style", "fabric_article", "line", "week", "planned_dates"], as_index=False)["planned_qty"].sum()
        result_1_day = result_1_day.rename(columns={'fabric_article': 'color'})
        result_0_day = df_0_day.groupby(["oc_no", "order_no", "buyer", "style", "fabric_article", "line", "week", "planned_dates"], as_index=False)["planned_qty"].sum()
        result_0_day = result_0_day.rename(columns={'fabric_article': 'color'})

        # Define Factory & Floor Mapping
        factory_floor_mapping = {
            "Line 1": ("Factory 1", "Floor 1"),
            "Line 2": ("Factory 1", "Floor 1"),
            "Line 3": ("Factory 2", "Floor 1"),
            "Line 4": ("Factory 2", "Floor 1"),
            "Line 5": ("Factory 3", "Floor 2"),
            "Line 6": ("Factory 3", "Floor 2"),
            "Line 7": ("Factory 4", "Floor 2"),
            "Line 8": ("Factory 4", "Floor 2"),
            "Line 9": ("Factory 5", "Floor 2"),
            "Line 10": ("Factory 5", "Floor 2")
        }

        # Function to map factory and floor
        def map_factory_floor(line):
            return factory_floor_mapping.get(line, ("Unknown", "Unknown"))

        # Apply mapping, ensuring empty DataFrames also have "FACTORY" and "FLOOR" columns
        for df in [result_0_day, result_1_day, result_7_days, result_30_days, result_60_days]:
            if not df.empty:
                df[["FACTORY", "FLOOR"]] = pd.DataFrame(df["line"].apply(map_factory_floor).tolist(), index=df.index)
            else:
                df[["FACTORY", "FLOOR"]] = [["Unknown", "Unknown"]]  # ✅ Assign default values to empty DataFrames

        # Add Workdays column
        for df in [result_0_day, result_1_day, result_7_days, result_30_days, result_60_days]:
            df["Workdays"] = 6

        # MERGING 7,30,60 1 LOAD PLAN WITH STYLE OB

        #################manning_7########################

        # Merge with Style OB table based on exact match and drop unmatched rows
        manning_7 = result_7_days.merge(
            df_Style_OB, left_on=["style", "color"], right_on=["style", "color"], how="inner")

        # Ensure sorting by STYLE, section, and op_seq first, then by OC NO, ORDER NO, Line
        manning_7 = manning_7.sort_values(by=["style", "color", "section", "op_seq", "oc_no", "order_no", "line"])

        # Drop Matched Style and style columns
        manning_7 = manning_7.drop(columns=["Matched Style", "UNNAMED: 0"], errors='ignore')

        manning_7 = manning_7.groupby(
            ["oc_no", "order_no", "buyer", "style", "color", "line", "section"], as_index=False
        ).apply(lambda x: x.sort_values(by=["planned_dates", "op_seq"])).reset_index(drop=True)

        manning_7.columns = manning_7.columns.str.upper()

        #################manning_30########################

        # Merge with Style OB table based on exact match and drop unmatched rows
        manning_30 = result_30_days.merge(
            df_Style_OB, left_on=["style", "color"], right_on=["style", "color"], how="inner")

        # Ensure sorting by STYLE, section, and op_seq first, then by OC NO, ORDER NO, Line
        manning_30 = manning_30.sort_values(by=["style", "color", "section", "op_seq", "oc_no", "order_no", "line"])

        # Drop Matched Style and style columns
        manning_30 = manning_30.drop(columns=["Matched Style", "UNNAMED: 0"], errors='ignore')

        manning_30 = manning_30.groupby(
            ["oc_no", "order_no", "buyer", "style", "color", "line", "section"], as_index=False
        ).apply(lambda x: x.sort_values(by=["planned_dates", "op_seq"])).reset_index(drop=True)

        manning_30.columns = manning_30.columns.str.upper()


        ##################manning_60########################

        # Merge with Style OB table based on exact match and drop unmatched rows
        manning_60 = result_60_days.merge(
            df_Style_OB, left_on=["style", "color"], right_on=["style", "color"], how="inner")

        # Ensure sorting by STYLE, section, and op_seq first, then by OC NO, ORDER NO, Line
        manning_60 = manning_60.sort_values(by=["style", "color", "section", "op_seq", "oc_no", "order_no", "line"])

        # Drop Matched Style and style columns
        manning_60 = manning_60.drop(columns=["Matched Style", "UNNAMED: 0"], errors='ignore')

        manning_60 = manning_60.groupby(
            ["oc_no", "order_no", "buyer", "style", "color", "line", "section"], as_index=False
        ).apply(lambda x: x.sort_values(by=["planned_dates", "op_seq"])).reset_index(drop=True)

        manning_60.columns = manning_60.columns.str.upper()


        #####################manning_1########################

        # Merge with Style OB table based on exact match and drop unmatched rows
        manning_1 = result_1_day.merge(
            df_Style_OB, left_on=["style", "color"], right_on=["style", "color"], how="inner")

        # Ensure sorting by STYLE, section, and op_seq first, then by OC NO, ORDER NO, Line
        manning_1 = manning_1.sort_values(by=["style", "color", "section", "op_seq", "oc_no", "order_no", "line"])

        # Drop Matched Style and style columns
        manning_1 = manning_1.drop(columns=["Matched Style", "UNNAMED: 0"], errors='ignore')
    
        manning_1 = manning_1.groupby(
            ["oc_no", "order_no", "buyer", "style", "color", "line", "section"], as_index=False
        ).apply(lambda x: x.sort_values(by=["planned_dates", "op_seq"])).reset_index(drop=True)

        manning_1.columns = manning_1.columns.str.upper()
        
        #####################manning_0########################

        # Merge with Style OB table based on exact match and drop unmatched rows
        manning_0 = result_0_day.merge(
            df_Style_OB, left_on=["style", "color"], right_on=["style", "color"], how="inner")

        # Ensure sorting by STYLE, section, and op_seq first, then by OC NO, ORDER NO, Line
        manning_0 = manning_0.sort_values(by=["style", "color", "section", "op_seq", "oc_no", "order_no", "line"])

        # Drop Matched Style and style columns
        manning_0 = manning_0.drop(columns=["Matched Style", "UNNAMED: 0"], errors='ignore')

        manning_0 = manning_0.groupby(
            ["oc_no", "order_no", "buyer", "style", "color", "line", "section"], as_index=False
        ).apply(lambda x: x.sort_values(by=["planned_dates", "op_seq"])).reset_index(drop=True)

        manning_0.columns = manning_0.columns.str.upper()

    #======================================================================

        manning_7_df = manning_7.copy()
        manning_30_df = manning_30.copy()
        manning_60_df = manning_60.copy()
        manning_1_df = manning_1.copy()
        manning_0_df = manning_0.copy()
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # List of manning dataframes to process
        manning_dataframes = [
            {"name": manning_0_df, "suffix": "0", "period": 0},
            {"name": manning_1_df, "suffix": "1", "period": 1},
            {"name": manning_7_df, "suffix": "7", "period": 7},
            {"name": manning_30_df, "suffix": "30", "period": 30},
            {"name": manning_60_df, "suffix": "60", "period": 60}
        ]
        
        emp_fact_df = emp_fact_df[emp_fact_df["type"].isin(["Primary", "Secondary"])]
        
        # Function to fetch prioritized employees based on constraints
        def get_prioritized_employees(emp_df, line=None, code=None, section=None):
            query = (emp_df["remaining_capacity"] > 0)

            if line:
                query &= (emp_df["line"] == line)
            if code:  # Ensure employee only works on assigned CODE
                query &= (emp_df["code"] == code)
            if section:
                query &= (emp_df["section"] == section)
            

            return emp_df[query].sort_values(by=["type", "remaining_capacity"], ascending=[True, False])  # Prioritize Primary first
        
        # Process each manning dataframe
        all_processed_dfs = []  # To store all processed dataframes for consolidation

        for df_info in manning_dataframes:
            df_name = df_info['name']

            try:
                logger.info(f"Processing {df_info['suffix']}...")

                # Get the dataframe using the appropriate method
                # Directly access the dataframe from the dictionary without checking
                manning_df = df_name.copy()

                # Convert planned dates to datetime for accurate merging
                manning_df["PLANNED_DATES"] = pd.to_datetime(manning_df["PLANNED_DATES"])

                # Create a new dataframe to store the split order lines
                updated_manning_df = pd.DataFrame(columns=manning_df.columns)

                # Add allocation columns in manning
                allocation_columns = [
                    "ALLOCATED EMP ID", "ALLOCATED EMP NAME", "ALLOCATED CAPACITY",
                    "ALLOCATED_FRM_LINE", "ALLOCATED_FRM_FACTORY", "ALLOCATED_FRM_FLOOR",
                    "SKILL_TYPE", "MACHINE_EMP_FACT", "SHORTAGE_FLAG", "SHORTAGE_REASON", "DESIGNATION",
                    "TARGET@100%", "TARGET@90%", "SPLIT_ORDER_ID", "PERIOD"
                ]

                for col in allocation_columns:
                    if col not in manning_df.columns:
                        if col in ["ALLOCATED CAPACITY", "TARGET@100%", "TARGET@90%"]:
                            manning_df[col] = 0.0
                        elif col == "SHORTAGE_FLAG":
                            manning_df[col] = "Fulfilled"
                        elif col == "SHORTAGE_REASON":
                            manning_df[col] = ""
                        elif col == "SPLIT_ORDER_ID":
                            manning_df[col] = ""
                        elif col == "PERIOD":
                            manning_df[col] = df_info["period"]
                        else:
                            manning_df[col] = None

                # Reset daily capacity for each planned date
                unique_dates = manning_df["PLANNED_DATES"].unique()

                # Perform allocation with strict prioritization for each date
                for date in sorted(unique_dates):
                    # Reset daily capacity and round to 2 decimal places to avoid floating point issues
                    emp_fact_df["remaining_capacity"] = emp_fact_df["average_capacity"].copy()
                    emp_fact_df["remaining_capacity"] = emp_fact_df["remaining_capacity"].round(2)

                    # Add validation to ensure no negative initial capacities
                    if (emp_fact_df["remaining_capacity"] < 0).any():
                        logger.info(f"WARNING: Found negative initial capacities on {date}!")
                        # Fix any negative values by setting to 0
                        emp_fact_df.loc[emp_fact_df["remaining_capacity"] < 0, "remaining_capacity"] = 0

                    # Filter orders for the current date
                    daily_orders = manning_df[manning_df["PLANNED_DATES"] == date].copy()

                    # Create a new list to collect all new rows (including splits)
                    new_rows = []

                    for index, row in daily_orders.iterrows():
                        line, section, code, planned_qty = row["LINE"], row["SECTION"], row["CODE"], row["PLANNED_QTY"]
                        original_row = row.copy()  # Keep a copy of the original row

                        # Only check for employees in the same line and code/section
                        available_employees = get_prioritized_employees(emp_fact_df, line=line, code=code, section=section)

                        if available_employees.empty:
                            # If no employees match line, code and section criteria
                            # Mark as shortage if no employee found
                            original_row["SHORTAGE_FLAG"] = "Shortage Unresolved"

                            # Add shortage reason
                            # Check if any employees with matching code exist in any line
                            any_matching_code = False
                            for emp in emp_fact_df.iterrows():
                                if emp[1]["code"] == code:
                                    any_matching_code = True
                                    break

                            if not any_matching_code:
                                original_row["SHORTAGE_REASON"] = f"No employees with CODE={code} found in any line"
                            else:
                                # Check if there are employees with the code but in different lines
                                other_lines = []
                                for emp in emp_fact_df.iterrows():
                                    if emp[1]["code"] == code and emp[1]["line"] != line:
                                        other_lines.append(emp[1]["line"])

                                if other_lines:
                                    original_row["SHORTAGE_REASON"] = f"CODE={code} found only in lines: {', '.join(set(other_lines))}"
                                else:
                                    # Check if there are employees in this line but with zero capacity
                                    zero_capacity = False
                                    for emp in emp_fact_df.iterrows():
                                        if (emp[1]["code"] == code and emp[1]["line"] == line
                                            and emp[1]["remaining_capacity"] == 0):
                                            zero_capacity = True
                                            break

                                    if zero_capacity:
                                        original_row["SHORTAGE_REASON"] = f"Employees with CODE={code} in LINE={line} have no remaining capacity"
                                    else:
                                        original_row["SHORTAGE_REASON"] = f"No matching employees for LINE={line} and CODE={code}"
                                        original_row["SPLIT_ORDER_ID"] = ""  # No split for unresolved shortages

                            new_rows.append(original_row)
                            continue  # Skip to next order line

                        # Try to fulfill the order by assigning multiple employees if needed
                        remaining_qty = planned_qty
                        first_allocation = True
                        split_count = 0
                        split_order_id = f"{row['ORDER_NO']}_{row['STYLE']}_{line}_{code}_{date.strftime('%Y%m%d')}"

                        while remaining_qty > 0 and not available_employees.empty:
                            emp = available_employees.iloc[0]
                            
                            # Add logging for debugging capacity issues
                            old_capacity = emp["remaining_capacity"]

                            # Calculate allocation
                            allocation = min(remaining_qty, emp["remaining_capacity"])

                            # Calculate new capacity with tolerance for floating-point errors
                            new_capacity = old_capacity - allocation

                            # If new capacity is very close to zero (within 0.001), set it to exactly 0
                            if abs(new_capacity) < 0.001:
                                new_capacity = 0

                            # Ensure capacity is never negative due to floating-point errors
                            if new_capacity < 0:
                                logger.info(f"Fixing floating-point error: {new_capacity} set to 0")
                                new_capacity = 0

                            # Update employee's capacity
                            emp_fact_df.loc[emp_fact_df["employee_id"] == emp["employee_id"], "remaining_capacity"] = new_capacity

                            # Update remaining quantity
                            remaining_qty -= allocation

                            # Create a new row or update the existing one
                            if first_allocation:
                                current_row = original_row.copy()
                                first_allocation = False
                                current_row["SPLIT_ORDER_ID"] = f"{split_order_id}_part1"
                                current_row["PERIOD"] = df_info["period"]  # Ensure PERIOD is set
                                split_count = 1
                            else:
                                # Create a new split row with the same order details but different allocation
                                current_row = original_row.copy()
                                split_count += 1
                                current_row["SPLIT_ORDER_ID"] = f"{split_order_id}_part{split_count}"
                                current_row["PERIOD"] = df_info["period"]  # Ensure PERIOD is set

                            # Assign employee details
                            current_row["ALLOCATED EMP ID"] = emp["employee_id"]
                            current_row["ALLOCATED EMP NAME"] = emp["employee_name"]
                            current_row["ALLOCATED CAPACITY"] = float(allocation)
                            current_row["ALLOCATED_FRM_LINE"] = emp["line"]
                            current_row["ALLOCATED_FRM_FACTORY"] = emp["factory"]
                            current_row["ALLOCATED_FRM_FLOOR"] = emp["floor"]
                            current_row["SKILL_TYPE"] = emp["type"]
                            current_row["MACHINE_EMP_FACT"] = emp["machine"]
                            current_row["DESIGNATION"] = emp["designation"]
                            current_row["TARGET@100%"] = float(allocation)
                            current_row["TARGET@90%"] = float(allocation) * 0.9
                            current_row["PLANNED_QTY"] = float(allocation)  # Update planned qty for the split PLANNED_QTY

                            # Add the row to our new rows collection
                            new_rows.append(current_row)

                            # Refresh the available employees list for the same line and code
                            available_employees = get_prioritized_employees(emp_fact_df, line=line, code=code, section=section)

                            # If still no employees available and we have remaining quantity, mark as partial shortage
                            if available_employees.empty and remaining_qty > 0:
                                shortage_row = original_row.copy()
                                shortage_row["SHORTAGE_FLAG"] = "Partial Shortage"
                                shortage_row["PLANNED_QTY"] = float(remaining_qty) # PLANNED_QTY
                                shortage_row["ALLOCATED CAPACITY"] = 0
                                shortage_row["TARGET@100%"] = 0
                                shortage_row["TARGET@90%"] = 0
                                shortage_row["SPLIT_ORDER_ID"] = f"{split_order_id}_shortage"
                                shortage_row["PERIOD"] = df_info["period"]  # Ensure PERIOD is set

                                # Add shortage reason for partial shortage
                                capacity_in_line = 0
                                for emp in emp_fact_df.iterrows():
                                    if emp[1]["line"] == line and emp[1]["code"] == code:
                                        # Ensure we never add negative capacity to our sum
                                        capacity = max(0, emp[1]["remaining_capacity"])
                                        capacity_in_line += capacity

                                if capacity_in_line == 0:
                                    shortage_row["SHORTAGE_REASON"] = f"All employees with CODE={code} in LINE={line} are fully allocated"
                                else:
                                    # Modified to prevent showing negative capacity
                                    shortage_row["SHORTAGE_REASON"] = f"Insufficient capacity: Still needed {remaining_qty} units but only {capacity_in_line} available"

                                new_rows.append(shortage_row)
                                break

                    # Check for any employees with negative capacity at the end of processing each date
                    neg_capacity_emps = emp_fact_df[emp_fact_df["remaining_capacity"] < 0]
                    if not neg_capacity_emps.empty:
                        logger.info(f"ERROR: Found {len(neg_capacity_emps)} employees with negative capacity on {date}:")
                        for _, neg_emp in neg_capacity_emps.iterrows():
                            logger.info(f"  - Employee {neg_emp['employee_id']}: {neg_emp['remaining_capacity']}")
                        # Fix negative capacities
                        emp_fact_df.loc[emp_fact_df["remaining_capacity"] < 0, "remaining_capacity"] = 0

                    # Create DataFrame from new rows and concatenate with updated_manning_df
                    if new_rows:
                        date_df = pd.DataFrame(new_rows)
                        updated_manning_df = pd.concat([updated_manning_df, date_df], ignore_index=True)

                # Identify unallocated employees
                # unallocated_employees = emp_fact_df[emp_fact_df["remaining_capacity"] == emp_fact_df["average_capacity"]]
                # unallocated_employees = unallocated_employees[["employee_id", "employee_name", "line", "section", "code", "average_capacity"]]

                # Save the unallocated employees
                # unallocated_output_path = f"/content/drive/MyDrive/Laguna Docs/unallocated_employees_{df_info['suffix']}.csv"
                # unallocated_employees.to_csv(unallocated_output_path, index=False)

                # Try to merge with SMV data if available
                try:
                    updated_manning_df = updated_manning_df.merge(df_unique_smv[['style','smv']], left_on='STYLE', right_on='style', how='left')
                    # Ensure NaN values are replaced with None
                    updated_manning_df = updated_manning_df.where(pd.notna(updated_manning_df), None)

                    # List to store model instances
                    data_list = [
                        ManningSheetData(
                            oc_no=row['OC_NO'],
                            order_no=row['ORDER_NO'],
                            buyer=row['BUYER'],
                            style=row['STYLE'],
                            line=row['LINE'],
                            week=row['WEEK'],
                            planned_dates=row['PLANNED_DATES'],
                            planned_qty=row['PLANNED_QTY'],
                            factory=row['FACTORY'],
                            floor=row['FLOOR'],
                            workdays=row['WORKDAYS'],
                            section=row['SECTION'],
                            op_seq=row['OP_SEQ'],
                            operation=row['OPERATION'],
                            code=row['CODE'],
                            sam=row['SAM'],
                            smv=row['smv'],
                            allocated_emp_id=int(row['ALLOCATED EMP ID']) if pd.notna(row['ALLOCATED EMP ID']) else 0,  # Convert NaN to 0
                            allocated_emp_name=row['ALLOCATED EMP NAME'],
                            allocated_capacity=row['ALLOCATED CAPACITY'],
                            allocated_frm_line=row['ALLOCATED_FRM_LINE'],
                            allocated_frm_factory=row['ALLOCATED_FRM_FACTORY'],
                            allocated_frm_floor=row['ALLOCATED_FRM_FLOOR'],
                            skill_type=row['SKILL_TYPE'],
                            machine=row['MACHINE_EMP_FACT'],
                            shortage_flag=row['SHORTAGE_FLAG'],
                            shortage_reason=row['SHORTAGE_REASON'],
                            designation=row['DESIGNATION'],
                            target_100=row['TARGET@100%'],
                            target_90=row['TARGET@90%'],
                            split_order_id=row['SPLIT_ORDER_ID'],
                            forecast_period=row['PERIOD'],  
                            # buyer_y=row.get('BUYER', None),  # If 'BUYER' appears twice, resolve conflict
                            machinist=row['MACHINIST'],
                            machine_type=row['MACHINE_TYPE'],
                            color=row['COLOR']
                        )
                        for _, row in updated_manning_df.iterrows()
                    ]
                    

                    # Insert in chunks
                    for i in range(0, len(data_list), CHUNK_SIZE):
                        with transaction.atomic():  # Ensure bulk insert is atomic
                            ManningSheetData.objects.bulk_create(data_list[i:i + CHUNK_SIZE])
                except Exception as e:
                    # print(f"SMV data error in {df_name}: {str(e)}")
                    # print(f"Error occurred at: {traceback.format_exc()}")
                    return error_response(error=f"SMV data error. Message: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                    

                manning_sheet_df[str(df_info['suffix'])] = updated_manning_df

                # Store the updated dataframe in the dictionary
                # df_unique_smv[f"updated_{df_name}"] = updated_manning_df

                # Add to our collection for consolidation
                all_processed_dfs.append(updated_manning_df)
                

            except Exception as e:
                return error_response(error=f"Failed to generate manning sheet. Message: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        
        df_results = []
        
        for period, manning in manning_sheet_df.items():
            df_manning = pd.DataFrame(manning)

            if 'ALLOCATED CAPACITY' in df_manning.columns:

                # Ensure PLANNED_QTY and ALLOCATED CAPACITY are integers and fill missing values
                df_manning['PLANNED_QTY'] = df_manning['PLANNED_QTY'].fillna(0).astype(int)
                df_manning['ALLOCATED CAPACITY'] = df_manning['ALLOCATED CAPACITY'].fillna(0).astype(int)

                # Group by STYLE, LINE, SECTION, CODE and MACHINE_TYPE
                df_manning = df_manning.groupby(['STYLE', 'LINE', 'SECTION', 'CODE', 'MACHINE_TYPE'], as_index=False)[['PLANNED_QTY', 'ALLOCATED CAPACITY']].sum()
                df_manning['SHORTAGE CAPACITY'] = df_manning['PLANNED_QTY'] - df_manning['ALLOCATED CAPACITY']

                # Assign `Manning_Sheet_Period` AFTER grouping to prevent data loss
                df_manning["Manning_Sheet_Period"] = period

            # Filter only Primary and Secondary operations from Employee Fact Data
            df_emp_fact_filtered = emp_fact_df[emp_fact_df["type"].isin(["Primary", "Secondary"])]

            # Compute Median Capacity per CODE, LINE, and SECTION
            df_median_capacity = df_emp_fact_filtered.groupby(["code", "line", "section"], as_index=False)["average_capacity"].median()
            df_median_capacity.rename(columns={"average_capacity": "Median_Average_Capacity"}, inplace=True)

            # Compute Median Section Capacity in case CODE-level data is missing
            df_section_avg_capacity = df_emp_fact_filtered.groupby(["section", "line"], as_index=False)["average_capacity"].median()
            df_section_avg_capacity.rename(columns={"average_capacity": "Section_Average_Capacity"}, inplace=True)

            # Compute Total Active Operators per CODE, LINE, and SECTION
            df_total_active_operators = df_emp_fact_filtered.groupby(["code", "line", "section"], as_index=False)["employee_id"].count()
            df_total_active_operators.rename(columns={"employee_id": "Total_Active_Operators"}, inplace=True)

            # Compute Total Machinist and Non-Machinist Available
            df_machinist_count = df_emp_fact_filtered[df_emp_fact_filtered["designation"] == "Machinist"].groupby(["code", "line", "section"], as_index=False)["employee_id"].count()
            df_machinist_count.rename(columns={"employee_id": "Total_Machinist_Available"}, inplace=True)

            df_non_machinist_count = df_emp_fact_filtered[df_emp_fact_filtered["designation"] != "Machinist"].groupby(["code", "line", "section"], as_index=False)["employee_id"].count()
            df_non_machinist_count.rename(columns={"employee_id": "Total_Non_Machinist_Available"}, inplace=True)

            # Merge data with manning data
            df_merged_filtered = df_manning.merge(df_median_capacity,left_on=["CODE", "LINE", "SECTION"], right_on=["code", "line", "section"], how="left")
            df_merged_filtered = df_merged_filtered.merge(df_section_avg_capacity, on=["section", "line"], how="left")
            df_merged_filtered = df_merged_filtered.merge(df_total_active_operators, on=["code", "line", "section"], how="left")
            df_merged_filtered = df_merged_filtered.merge(df_machinist_count, on=["code", "line", "section"], how="left")
            df_merged_filtered = df_merged_filtered.merge(df_non_machinist_count, on=["code", "line", "section"], how="left")

            # Fill missing capacity values
            df_merged_filtered["Median_Average_Capacity"].fillna(df_merged_filtered["Section_Average_Capacity"], inplace=True)
            df_merged_filtered["Median_Average_Capacity"].replace(0, 1, inplace=True)  # Avoid division by zero

            # Fill missing operator counts with 0
            df_merged_filtered[["Total_Active_Operators", "Total_Machinist_Available", "Total_Non_Machinist_Available"]] = df_merged_filtered[["Total_Active_Operators", "Total_Machinist_Available", "Total_Non_Machinist_Available"]].fillna(0)

            # Compute Total Operators Required based on Planned Qty and Median Capacity
            df_merged_filtered["Total_Operators_Required"] = (
                df_merged_filtered["PLANNED_QTY"] / df_merged_filtered["Median_Average_Capacity"]
            ).apply(lambda x: round(x, 1))

            # Compute Machinist and Non-Machinist Requirements
            df_merged_filtered["Machinist_Required"] = df_merged_filtered.apply(
                lambda row: round(row["Total_Operators_Required"], 1) if row["code"] in df_emp_fact_filtered[df_emp_fact_filtered["designation"] == "Machinist"]["code"].values else 0, axis=1
            )
            df_merged_filtered["Non_Machinist_Required"] = df_merged_filtered.apply(
                lambda row: round(row["Total_Operators_Required"], 1) if row["code"] not in df_emp_fact_filtered[df_emp_fact_filtered["designation"] == "Machinist"]["code"].values else 0, axis=1
            )

            # Merge Machine information
            machine_data = df_emp_fact_filtered.groupby("code")["machine"].unique().reset_index()
            machine_data["machine"] = machine_data["machine"].apply(lambda x: ', '.join([m for m in x if m not in ["Unknown", "-"]]))

            #machine_data["MACHINE"] = machine_data["MACHINE"].apply(lambda x: ', '.join(x))
            df_merged_filtered = df_merged_filtered.merge(machine_data, on="code", how="left")

            df_results.append(df_merged_filtered)
            
        df_final_Information = pd.concat(df_results, ignore_index=True)
        df_final_Information = df_final_Information.where(pd.notna(df_final_Information), None)


        data_list = [
            ManningGeneralInfo(
                style=row['STYLE'],
                line=row['LINE'],
                section=row['SECTION'],
                code=row['CODE'],
                planned_qty=row['PLANNED_QTY'],
                allocated_capacity=row['ALLOCATED CAPACITY'],
                shortage_capacity=row['SHORTAGE CAPACITY'],
                forecast_period=row['Manning_Sheet_Period'],
                median_average_capacity=row['Median_Average_Capacity'],
                section_average_capacity=row['Section_Average_Capacity'],
                total_active_operators=row['Total_Active_Operators'],
                machinist_available=row['Total_Machinist_Available'],
                non_machinist_available=row['Total_Non_Machinist_Available'],
                total_operators_required=row['Total_Operators_Required'],
                machinist_required=row['Machinist_Required'],
                non_machinist_required=row['Non_Machinist_Required'],
                machine=row['MACHINE_TYPE']
            )
            for _, row in df_final_Information.iterrows()
        ]

        ManningGeneralInfo.objects.all().delete()

        # Insert in chunks
        for i in range(0, len(data_list), CHUNK_SIZE):
            with transaction.atomic():  # Ensure bulk insert is atomic
                ManningGeneralInfo.objects.bulk_create(data_list[i:i + CHUNK_SIZE])
            
        return success_response(message="Successfully generated manning data", status=status.HTTP_200_OK)
    
    except Exception as e:
        return error_response(error=f"Failed in manning sheet generation. {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def generate_emp_fact(request):
    try:
        return run_generate_emp_fact()  # Call the function without needing a request
    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)


def run_generate_emp_fact():
    try:
        # Get today's date
        current_date = datetime.now().date()
        # Check if the filter date is a working day and not a holiday
        isWorkingDay, reason = is_allowed_working_day(current_date)
        if not isWorkingDay:
            return error_response(error=f'Skipping for {current_date} as it is {reason}', status=status.HTTP_400_BAD_REQUEST)

        # Allowed values
        allowed_values = ['Back', 'Collar', 'Sleeve', 'Cuff', 'Front', 'Assembly']
        logger.info(f"*******************************************************************")
        logger.info(f"Running EMP Fact generation at {str(datetime.now())} hours!")
        df_skill_matrix = fetch_skill_matrix()
        df_operations = fetch_operations()

        # Keeping only those employees who are machinist
        df_skill_matrix = df_skill_matrix[df_skill_matrix['machinist'] == True]

        active_employees_queryset = ActiveEmployees.objects.all().values()
        df_active_employees = pd.DataFrame(list(active_employees_queryset))
        df_active_employees.rename(columns={'employee_id': 'Emp No', 'employee_name': 'Employee name', 'line': 'Line', 'section': 'Section', 'designation': 'Designation'}, inplace=True)

        # Convert Emp No and EMPLOYEE ID to numeric
        df_active_employees["Emp No"] = pd.to_numeric(df_active_employees["Emp No"], errors="coerce")
        df_skill_matrix["employeeId"] = pd.to_numeric(df_skill_matrix["employeeId"], errors="coerce")

        df_skill_matrix = df_skill_matrix[
            df_skill_matrix["employeeId"].isin(df_active_employees["Emp No"])
        ]

        df_emp_fact = merge_dataframe(df_skill_matrix, df_operations)

        # Keep only rows where 'operation' is in allowed_values
        df_emp_fact = df_emp_fact[df_emp_fact['SECTION'].isin(allowed_values)]

        df_emp_fact = df_emp_fact.merge(
            df_active_employees[['Emp No', 'Designation']],
            left_on='EMPLOYEE ID',
            right_on='Emp No',
            how='left'
        )

        records = [
            EMPFact(
                employee_id=int(row['EMPLOYEE ID']) if row['EMPLOYEE ID'] else 0,
                employee_name=row['EMPLOYEE NAME'] if row['EMPLOYEE NAME'] else 'N/A',
                line=row['LINE'] if row['LINE'] else 'N/A',
                factory=row['FACTORY'] if row['FACTORY'] else 'N/A',
                floor=row['FLOOR'] if row['FLOOR'] else 'N/A',
                section=row['SECTION'] if row['SECTION'] else 'N/A',
                designation=row['Designation'] if row['Designation'] else 'N/A',
                code=row['CODE'] if row['CODE'] else 'N/A',
                operation=row['OPERATION'] if row['OPERATION'] else 'N/A',
                type=row['TYPE'] if row['TYPE'] else 'N/A',
                sam=float(row['SAM']) if row['SAM'] else 0,
                peak_capacity=int(row['PEAK CAPACITY']) if row['PEAK CAPACITY'] else 0,
                average_capacity=int(row['AVERAGE CAPACITY']) if row['AVERAGE CAPACITY'] else 0,
                machine=row['MACHINE'] if row['MACHINE'] else 'N/A',
                status=row['STATUS']
            ) for _, row in df_emp_fact.iterrows()
        ]
        truncate_table(EMPFact)
        EMPFact.objects.bulk_create(records)

        logger.info(f"Data saved successfully at {str(datetime.now())} hours!")
        logger.info(f"***************************************************\n\n")

        return success_response(message="Data processed and uploaded to Database", status=status.HTTP_200_OK)
    except Exception as e:
        logger.info(f"Error in run_generate_emp_fact: {str(e)}")
        logger.error(f"Error in run_generate_emp_fact: {str(e)} at {datetime.now()} hours!", exc_info=True)
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated]) 
def manning_allocation(request):
    try:
        # Attempt to acquire lock
        # EndpointLock.acquire_lock('data_update', request.user, 'generate_manning_sheet')
        try:
            viaAPI=True
            # Get and validate period parameter
            PERIOD = request.query_params.get('period', 60)
            return run_manning_generation(viaAPI, PERIOD)  # Call the function without needing a request
        except Exception as e:
            return error_response(error=f"Failed in manning sheet generation. {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        # finally:
        #     # Always attempt to release the lock
        #     EndpointLock.release_lock('data_update', request.user, 'generate_manning_sheet')
    except ValidationError as ve:
        return error_response(error=f"{str(ve)}", status=status.HTTP_423_LOCKED)


def run_manning_generation(viaAPI, PERIOD):
    try:
        today = datetime.today().date()
        # Check if the filter date is a working day and not a holiday
        isWorkingDay, reason = is_allowed_working_day(today)
        if not isWorkingDay:
            return error_response(error=f'Skipping for {today} as it is {reason}', status=status.HTTP_400_BAD_REQUEST)

        current_time = datetime.now()
        if not viaAPI:
            logger.info(f"*******************************************************************")
            logger.info(f"Running Manning Sheet generation at {str(current_time)} hours!")

        try:
            PERIOD = int(PERIOD)
        except ValueError:
            return error_response(error="Period must be an integer", status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Load DB and CSV data concurrently
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_lp = executor.submit(lambda: list(LoadingPlan.objects.values().iterator()))
            future_style = executor.submit(lambda: list(StyleOB.objects.values().iterator()))
            future_empfact = executor.submit(lambda: list(EMPFact.objects.values().iterator()))
            future_active_employees = executor.submit(lambda: list(ActiveEmployees.objects.values().iterator()))

            df_load_plan_transformed = pd.DataFrame(future_lp.result())
            df_style_ob = pd.DataFrame(future_style.result())
            emp_fact_df = pd.DataFrame(future_empfact.result())
            df_active_employees = pd.DataFrame(future_active_employees.result())

        df_active_employees.rename(columns={'employee_id': 'Emp No', 'employee_name': 'Employee name', 'line': 'Line', 'section': 'Section', 'designation': 'Designation'}, inplace=True)

        # Filter employee facts
        emp_fact_df = emp_fact_df[
            emp_fact_df["employee_id"].isin(df_active_employees["Emp No"]) &
            emp_fact_df["type"].isin(["Primary", "Secondary"]) &
            emp_fact_df["designation"].isin(["Machinist"])
        ]

        # Clean and prepare loading plan
        df_load_plan_transformed["planned_dates"] = pd.to_datetime(df_load_plan_transformed["planned_dates"], errors='coerce').dt.date

        # Read data from DB
        date_thresholds = {
            f"{PERIOD}_days": today + timedelta(days=PERIOD)
        }
        df_load_plan_transformed["planned_dates"] = pd.to_datetime(df_load_plan_transformed["planned_dates"], errors='coerce')
        df_load_plan_transformed["planned_dates"] = df_load_plan_transformed["planned_dates"].dt.date    # Create four separate filtered DataFrames

        filtered_dfs = filter_by_date_ranges(df_load_plan_transformed, today, date_thresholds, PERIOD)
        result_dfs = process_grouped_results(filtered_dfs[f'{PERIOD}_days'])
        result_dfs = map_factory_floor_for_results(result_dfs)


        # Merge with Style OB and create manning dataframes
        manning_df = create_manning_dataframes(result_dfs, df_style_ob)

        # from .manning_generation_single_threading_v6 import filter_by_date_ranges_v6, process_single_manning_df_v6, run_manning_allocation_v6
        # filtered_dfs = filter_by_date_ranges_v6(df_load_plan_transformed, today, date_thresholds, PERIOD)
        # manning_df = process_single_manning_df_v6(filtered_dfs, df_style_ob)

        consolidated_manning_df = []
        all_unallocated_employees = []

        for item in df_load_plan_transformed['line'].unique():
            logger.info(item)
            updated_manning = manning_df[manning_df["LINE"] == item]
            df_load_plan_transformed_updated = df_load_plan_transformed[df_load_plan_transformed['line'] == item]
            emp_fact_df_updated = emp_fact_df[emp_fact_df['line'] == item]
            results = run_manning_allocation(
                PERIOD,
                updated_manning,
                emp_fact_df_updated,
                df_load_plan_transformed_updated
            )
            consolidated_manning_df.append(results["consolidated_manning_df"])
            all_unallocated_employees.append(results["all_unallocated_employees"])

        # Combine all collected DataFrames
        consolidated_manning_df = pd.concat(consolidated_manning_df, ignore_index=True)
        # Optionally, save or return
        # consolidated_manning_df.to_csv("csv_files/consolidated_manning_df.csv", index=False)


        # Combine all collected DataFrames
        all_unallocated_employees = pd.concat(all_unallocated_employees, ignore_index=True)
        # Drop duplicates ignoring REASON, CATEGORY, and PERIOD
        all_unallocated_employees.drop_duplicates(subset=[col for col in all_unallocated_employees.columns if col not in ['REASON', 'CATEGORY', 'PERIOD']], inplace=True, ignore_index=True)
        all_unallocated_employees.drop_duplicates(inplace=True, ignore_index=True)
        # Optionally, save or return
        # all_unallocated_employees.to_csv("csv_files/all_unallocated_employees.csv", index=False)


        truncate_table(UnallocatedEmployees)
        insert_all_unallocated_employees(all_unallocated_employees, df_active_employees)
        truncate_table(ManningSheetData)
        insert_consolidated_df(consolidated_manning_df)


        manning_df = results[f'updated_manning_{PERIOD}_df']

        # Process general information
        process_general_info(consolidated_manning_df, emp_fact_df, PERIOD)

        if not viaAPI:
            notification_type="manning_sheet"
            create_bulk_push_notifications(
                notification_type=notification_type,
                title=NOTIFICATION_DISPLAY_TITLE.get(notification_type, "Unknown"),
                message=f"Kindly review the Manning Sheet generated at {str(current_time.strftime('%B %d, %Y %I:%M %p'))}",
                users=User.objects.filter(status=True),  # only active users
            )
            logger.info(f"Data saved successfully at {str(datetime.now())} hours!")
            logger.info(f"***************************************************\n\n")

        return success_response(message="Successfully generated manning data", status=status.HTTP_200_OK)

    except Exception as e:
        logger.info("Error", e)
        return error_response(error=f"Failed in manning sheet generation. {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def generate_dday_manning_data(request):
    try:
        viaAPI=True
        return run_dday_generation(viaAPI)  # Call the function without needing a request
    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)


def run_dday_generation(viaAPI):
    try:
        # Get today's date
        current_date = datetime.now().date()
        # Check if the filter date is a working day and not a holiday
        isWorkingDay, reason = is_allowed_working_day(current_date)
        if not isWorkingDay:
            return error_response(error=f'Skipping for {current_date} as it is {reason}', status=status.HTTP_400_BAD_REQUEST)

        # Define time thresholds
        MIDDAY_THRESHOLD = time(12, 45) # 12:45 PM
        END_OF_DAY_THRESHOLD = time(17, 30) # 05:30 PM

        # Fetch current time
        current_time = get_ist_time()

        # Default type
        run_type = "noon"

        # Determine run_type based on thresholds
        if current_time.time() < MIDDAY_THRESHOLD:
            run_type = "morning"
        elif current_time.time() >= END_OF_DAY_THRESHOLD:
            run_type = "evening"

        try:
            fetch_and_transform_emp_attendance(run_type)
        except Exception as e:
            return error_response(error=f"Error in fetching and transforming attendance data: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Convert to timestamp for processing
        allocation_date = pd.Timestamp(current_date)

        try:
            attendance_queryset = AttendanceMaster.objects.filter(attendance_date=allocation_date).values()
            emp_fact_queryset = EMPFact.objects.all().values()
            Act_Employees_queryset = EmployeeMaster.objects.all().values()
            wip_queryset = WIPData.objects.all().values()

            attendance_df = pd.DataFrame(list(attendance_queryset))
            emp_fact_df = pd.DataFrame(list(emp_fact_queryset))
            Act_Employees = pd.DataFrame(list(Act_Employees_queryset))
            wip_df = pd.DataFrame(list(wip_queryset))
            
            emp_fact_df = emp_fact_df[emp_fact_df["employee_id"].isin(Act_Employees["emp_code"])]
            emp_fact_df = emp_fact_df[emp_fact_df["type"].isin(["Primary", "Secondary"])]

        except DatabaseError as db_err:
            logger.info(f"Database Error: {db_err}")
            return error_response(error="Database error occurred.", status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # from .dday_generation_v2 import get_run_type_for_testing
        # run_type = get_run_type_for_testing(use_fake_time=True, fake_time_str="08:50")

        logger.info(f"\nPerforming {run_type} allocation run for {current_date}")
        manning, stats, tracking = run_intraday_allocation_enhanced(
            allocation_date,
            attendance_df,
            emp_fact_df,
            wip_df,
            run_type=run_type
        )

        manning['preferred_employees'] = (
            manning['preferred_employees']
            .astype(str)                            # convert everything to string
            .str.strip()                            # remove leading/trailing whitespace
            .replace(['', 'nan', 'NaN', 'None'], np.nan)  # replace string empty cases with actual NaN
            .fillna('Not Applicable')               # now fill all NaN
        )

        # Calculate initial allocation completeness for comparison
        initial_planned = manning['planned_qty'].sum()
        initial_allocated = manning['allocated_capacity'].fillna(0).sum()
        initial_completeness = (initial_allocated / initial_planned * 100) if initial_planned > 0 else 0

        logger.info(f"\nINITIAL ALLOCATION RESULTS:")
        logger.info(f"- Total Planned: {initial_planned:.2f}")
        logger.info(f"- Initial Allocated: {initial_allocated:.2f}")
        logger.info(f"- Initial Completeness: {initial_completeness:.2f}%")

        # STEP 2: NEW - Perform final allocation pass to maximize planned quantity fulfillment
        logger.info("\n" + "="*60)
        logger.info("PERFORMING FINAL ALLOCATION OPTIMIZATION PASS")
        logger.info("="*60)

        # Get absent employees for the final pass
        attendance_df_temp = attendance_df.copy()
        attendance_df_temp['attendance_date'] = pd.to_datetime(attendance_df_temp['attendance_date'])
        daily_attendance = attendance_df_temp[attendance_df_temp['attendance_date'] == allocation_date]

        current_absent = []
        if not daily_attendance.empty:
            if 'last_updated' in daily_attendance.columns:
                daily_attendance['last_updated'] = pd.to_datetime(daily_attendance['last_updated'], format='%Y-%m-%d %H:%M:%S', errors='coerce')
                latest_attendance = daily_attendance.sort_values('last_updated').groupby('employee_id').last()
            else:
                latest_attendance = daily_attendance.groupby('employee_id').first()

            current_absent = latest_attendance[
                (latest_attendance['status'] == 'A') |
                (latest_attendance['early_departure'] == True)
            ].index.tolist()

            try:
                current_absent = [float(emp_id) for emp_id in current_absent]
            except ValueError:
                pass

        absent_set = set(current_absent)

        # NEW: Perform the final optimization pass
        optimized_manning = perform_final_allocation_pass(manning, emp_fact_df, absent_set)

        # Calculate enhanced allocation completeness
        final_allocated = optimized_manning['allocated_capacity'].fillna(0).sum()
        final_completeness = (final_allocated / initial_planned * 100) if initial_planned > 0 else 0
        improvement = final_completeness - initial_completeness

        logger.info(f"\nFINAL ALLOCATION RESULTS:")
        logger.info(f"- Final Allocated: {final_allocated:.2f}")
        logger.info(f"- Final Completeness: {final_completeness:.2f}%")
        logger.info(f"- Improvement: +{improvement:.2f}%")

        # Generate report (keeping your existing logic)
        report = generate_reallocation_report(stats, tracking)
        logger.info(report)

        # Check for over-allocation (keeping your existing logic)
        over_allocated = emp_fact_df[emp_fact_df["remaining_capacity"] < 0]
        if not over_allocated.empty:
            logger.info(f"WARNING: {len(over_allocated)} employees have been over-allocated!")
            logger.info(over_allocated[["employee_id", "employee_name", "remaining_capacity"]])

        # FIXED: Generate unallocated report using the safe version
        logger.info("\nGenerating Unallocated Employees Report...")
        unallocated_report = generate_unallocated_report_safe(
            emp_fact_df,
            allocation_date,
            attendance_df,
            optimized_manning  # Changed from 'manning' to 'optimized_manning'
        )

        # NEW: Analyze allocation gaps - but only if we have capacity data
        logger.info("\n" + "="*60)
        logger.info("ALLOCATION GAP ANALYSIS")
        logger.info("="*60)

        # For gap analysis, we need a capacity-based report, so let's create a simple one
        try:
            # Create a simple capacity report for gap analysis
            capacity_report = pd.DataFrame()
            for emp_id in emp_fact_df['employee_id'].unique():
                emp_records = emp_fact_df[emp_fact_df['employee_id'] == emp_id]
                for _, emp_record in emp_records.iterrows():
                    remaining_cap = emp_record.get('remaining_capacity', 0)
                    if remaining_cap > 0:  # Only include if has remaining capacity
                        capacity_report = pd.concat([capacity_report, pd.DataFrame([{
                            'employee_id': emp_id,
                            'code': emp_record['code'],
                            'remaining_capacity': remaining_cap
                        }])], ignore_index=True)

            gap_analysis = analyze_allocation_gaps(optimized_manning, capacity_report)

            if 'message' in gap_analysis:
                logger.info(gap_analysis['message'])
            else:
                logger.info(f"Operations with unmet quantities: {gap_analysis['unmet_operations_count']}")
                logger.info(f"Total unmet quantity: {gap_analysis['total_unmet_quantity']:.2f}")
                logger.info(f"Potential additional allocation: {gap_analysis['total_potential_additional_allocation']:.2f}")

                if gap_analysis['potential_matches']:
                    logger.info("\nTop 5 Skills with Unmet Demand vs Available Capacity:")
                    logger.info("-" * 60)
                    for skill, data in list(gap_analysis['potential_matches'].items())[:5]:
                        logger.info(f"Skill {skill}:")
                        logger.info(f"  Unmet: {data['unmet_quantity']:.1f}, Available: {data['available_capacity']:.1f}")
                        logger.info(f"  Potential fulfillment: {data['potential_fulfillment']:.1f} ({data['fulfillment_percentage']:.1f}%)")
                        logger.info()
        except Exception as e:
            logger.info(f"Gap analysis skipped due to error: {e}")

        # FIXED: Analyze unallocated patterns with new structure
        analysis_summary = analyze_unallocated_patterns(unallocated_report)

        # FIXED: Print summary with new structure
        print_unallocated_summary(analysis_summary)

        # # Save the manning sheet (now saving the OPTIMIZED version)
        # date_str = current_date.strftime('%Y%m%d')
        # output_path = f'exports/dday_{run_type}_manning_ENHANCED_{date_str}.csv'  # Added "ENHANCED" to filename
        # optimized_manning.to_csv(output_path, index=False)  # Changed from 'manning' to 'optimized_manning'
        # print(f"Enhanced Manning sheet saved to: {output_path}")

        # # Also save the original manning for comparison
        # original_output_path = f'exports/dday_{run_type}_manning_ORIGINAL_{date_str}.csv'
        # manning.to_csv(original_output_path, index=False)
        # print(f"Original Manning sheet saved to: {original_output_path}")

        # FIXED: Save unallocated report (works with new structure)
        if not unallocated_report.empty:
            unallocated_output_path = f'exports/unallocated_report_dday.csv'
            unallocated_report.to_csv(unallocated_output_path, index=False)
            logger.info(f"Enhanced Unallocated report saved to: {unallocated_output_path}")
        else:
            logger.info("No unallocated employees found - all employees have been allocated!")

        # FIXED: Display first few rows of unallocated report with correct columns
        if not unallocated_report.empty:
            logger.info(f"\nSample of Unallocated Employees Report:")
            logger.info("-" * 120)
            # Use only columns that exist in the new structure
            available_columns = ['employee_id', 'employee_name', 'line', 'code', 'type', 'reason']
            display_columns = [col for col in available_columns if col in unallocated_report.columns]
            sample_report = unallocated_report.head(10)[display_columns]
            logger.info(sample_report.to_string(index=False))
        else:
            logger.info("\nNo unallocated employees to display - all employees have been allocated!")

        # FIXED: Show summary statistics with new structure
        if not unallocated_report.empty:
            logger.info(f"\nUnallocated Employees Statistics:")
            logger.info(f"Total Unallocated Records: {len(unallocated_report)}")
            logger.info(f"Unique Unallocated Employees: {unallocated_report['employee_id'].nunique()}")

            # Show breakdown by reason
            if 'reason' in unallocated_report.columns:
                reason_counts = unallocated_report['reason'].value_counts()
                logger.info(f"Breakdown by Reason:")
                for reason, count in reason_counts.items():
                    logger.info(f"  {reason}: {count}")
        else:
            logger.info(f"\nUnallocated Employees Statistics:")
            logger.info(f"All employees have been allocated successfully!")

        # NEW: Show enhanced allocations made
        enhanced_allocations = optimized_manning[optimized_manning['reallocation_level'].isin(['final_optimization', 'final_optimization_addition', 'final_optimization_additional_row'])]

        if not enhanced_allocations.empty:
            logger.info(f"\n" + "="*60)
            logger.info("ENHANCED ALLOCATIONS SUMMARY")
            logger.info("="*60)
            logger.info(f"Additional allocations made: {len(enhanced_allocations)}")

            # Calculate additional capacity more safely
            try:
                # Get the indices that exist in both dataframes
                common_indices = enhanced_allocations.index.intersection(manning.index)
                if len(common_indices) > 0:
                    original_capacity = manning.loc[common_indices, 'allocated_capacity'].fillna(0).sum()
                    enhanced_capacity = enhanced_allocations.loc[common_indices, 'allocated_capacity'].fillna(0).sum()
                    additional_capacity = enhanced_capacity - original_capacity
                else:
                    additional_capacity = enhanced_allocations['allocated_capacity'].fillna(0).sum()

                logger.info(f"Additional capacity allocated: {additional_capacity:.2f}")
            except Exception as e:
                logger.info(f"Additional capacity calculation: {enhanced_allocations['allocated_capacity'].fillna(0).sum():.2f}")

            logger.info(f"\nSample of Enhanced Allocations:")
            logger.info("-" * 120)
            display_cols = ['line', 'operation', 'code', 'planned_qty', 'allocated_capacity', 'allocated_emp_name', 'shortage_flag']
            available_cols = [col for col in display_cols if col in enhanced_allocations.columns]
            sample_enhanced = enhanced_allocations[available_cols].head(5)
            logger.info(sample_enhanced.to_string(index=False))
        else:
            logger.info(f"\n" + "="*60)
            logger.info("No additional allocations were made - your original allocation was already optimal!")
            logger.info("="*60)

        # Final summary
        logger.info(f"\n" + "="*80)
        logger.info("FINAL SUMMARY")
        logger.info("="*80)
        logger.info(f"🎯 Allocation Improvement: {initial_completeness:.2f}% → {final_completeness:.2f}% (+{improvement:.2f}%)")
        logger.info(f"📊 Total Planned Quantity: {initial_planned:.2f}")
        logger.info(f"📈 Additional Capacity Allocated: {final_allocated - initial_allocated:.2f}")
        logger.info(f"👥 Enhanced Allocations Made: {len(enhanced_allocations) if not enhanced_allocations.empty else 0}")
        if not unallocated_report.empty:
            logger.info(f"❌ Unallocated Employees: {unallocated_report['employee_id'].nunique()}")
        else:
            logger.info(f"✅ All Employees Allocated Successfully!")
        logger.info("="*80)

        # manning = optimized_manning #Comment as it is not required
        if 'raw_style' in manning.columns:
            manning['style'] = manning['raw_style'].str.upper()
        for col in manning.columns:
            if col in ['raw_oc_no', 'raw_style', 'raw_color', 'estimated_completed_time', 'completed_qty', 'additional_employees']:
                manning.drop(columns=[col], inplace=True)

        # List of columns to process
        emp_id_columns = ['allocated_emp_id', 'original_emp', 'new_emp']
        emp_name_columns = ['allocated_emp_name', 'original_emp_name', 're_allocated_employee']

        # Loop through the employee columns and update the corresponding name columns
        for id_col, name_col in zip(emp_id_columns, emp_name_columns):
            # Convert to integer and fill NaN with 0
            manning[id_col] = manning[id_col].fillna(0).astype(int)
            
            # Merge to get employee names
            manning = manning.merge(
                emp_fact_df[['employee_id', 'employee_name']],
                how='left',
                left_on=id_col,
                right_on='employee_id',
                suffixes=('', '_from_emp_fact')
            )
            
            # Update the name column with employee name and drop unnecessary columns
            manning[name_col] = manning['employee_name']
            manning.drop(columns=['employee_id', 'employee_name'], inplace=True)
            
            # Set the name to None if emp_id is 0
            manning.loc[manning[id_col] == 0, name_col] = None


        # Convert to dict format for DB insertion
        manning_records = manning.to_dict(orient="records")

        # Delete existing records before inserting new ones
        try:
            if not manning_records:
                return success_response(message=f"No records generated for DDay", status=status.HTTP_200_OK)
            truncate_table(DDayData)
        except DatabaseError as db_err:
            logger.info(f"Error deleting old records: {db_err}")
            return error_response(error="Failed to clear old data.", status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Insert data in chunks
        try:
            if len(manning_records) > 0:
                for i in range(0, len(manning_records), CHUNK_SIZE):
                    chunk = manning_records[i : i + CHUNK_SIZE]  
                    manning_data = [DDayData(**row) for row in chunk]  

                    # Bulk insert in transaction
                    with transaction.atomic():
                        DDayData.objects.bulk_create(manning_data, ignore_conflicts=True) 

        except IntegrityError as int_err:
            logger.info(f"Integrity Error: {int_err}")
            return error_response(error="Data integrity issue.", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except DatabaseError as db_err:
            logger.info(f"Database Error during bulk insert: {db_err}")
            return error_response(error="Failed to insert data.", status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        logger.info(f"D-Day Manning Allocation Completed Successfully.")

        if not viaAPI:
            get_dday_data()

            logger.info(f"Data saved successfully at {str(datetime.now())} hours!")
            logger.info(f"***************************************************\n\n")
        return success_response(message=f"Successfully generated DDay data", status=status.HTTP_200_OK)

    except Exception as e:
        logger.info(e)
        return error_response(error=f"An unexpected error occurred. {e}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def generate_style_ob(request):
    try:
        viaAPI=True
        return run_generate_style_ob(viaAPI)  # Call the function without needing a request
    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)


def run_generate_style_ob(viaAPI):
    try:
        today = datetime.today().date()
        # Check if the filter date is a working day and not a holiday
        isWorkingDay, reason = is_allowed_working_day(today)
        if not isWorkingDay:
            return error_response(error=f'Skipping for {today} as it is {reason}', status=status.HTTP_400_BAD_REQUEST)

        if not viaAPI:
            logger.info(f"*******************************************************************")
            logger.info(f"Running Style OB generation at {str(datetime.now())} hours!")

        df_operations = fetch_operations()
        df_style_ob_seq = fetch_style_ob()

        # Operation Code null droppings
        df_style_ob_seq = df_style_ob_seq.dropna(subset=['Operation Code'])
        df_style_ob_seq = df_style_ob_seq.reset_index(drop=True)


        df_merged = merge_machine_sam(df_style_ob_seq, df_operations)
        df_final = process_styles(df_merged)

        df_Style_OB = renaming_columns_style_ob(df_final)

        df_Style_OB.dropna(subset=['code'], inplace=True)
        df_Style_OB['code'] = df_Style_OB['code'].str.replace(r'\s+', ' ', regex=True).str.strip()
        df_Style_OB['code'] = df_Style_OB['code'].str.replace(' ', '', regex=True)
        df_Style_OB = df_Style_OB[df_Style_OB['department'] == 'Sewing']


        df_Style_OB['style'] = df_Style_OB['style'].str.lower().str.strip()
        df_Style_OB['style'] = df_Style_OB['style'].str.replace(r'\s+', ' ', regex=True).str.strip()
        df_Style_OB['style'] = df_Style_OB['style'].str.replace(' ', '', regex=True)

        df_Style_OB = df_Style_OB.drop(columns=['created_at', 'department', 'type', 'Product Group', 'Product','Dependencies','Operation Sequence (Overall)'])
        df_Style_OB = df_Style_OB[df_Style_OB['section'] != 'Matching']

        df_Style_OB = df_Style_OB.drop_duplicates(subset=['style', 'section','op_seq', 'operation', 'code'], keep='first')
        df_Style_OB.dropna(subset = ["style","section","op_seq","operation","code"])

        df_Style_OB = df_Style_OB.sort_values(by=['style', 'section','op_seq']).groupby(['style', 'section'], as_index=False).apply(lambda x: x.sort_values(by=['op_seq'], ascending=True)).reset_index(drop=True)

        df_Style_OB = df_Style_OB[df_Style_OB['machinist'] == True]
        # df_Style_OB['style'] = df_Style_OB['style'].str.replace(r'[^a-z0-9]', '', regex=True) # Commented as it will remove special characters
        def row_to_dict(row):
            return {
                'style': row['style'],
                'section': row['section'],
                'op_seq': int(row['op_seq']),
                'operation': row['operation'],
                'code': row['code'],
                'sam': float(row['sam']),
                'machine_type': row['machine_type'],
                'machinist': row['machinist']
            }
        
        # Use ThreadPoolExecutor to convert rows to dicts
        with ThreadPoolExecutor(max_workers=10) as executor:
            data_dicts = list(executor.map(row_to_dict, [row for _, row in df_Style_OB.iterrows()]))

        
        # Chunked insert to DB using threads
        def insert_chunk(chunk_dicts):
            instances = [StyleOB(**d) for d in chunk_dicts]
            with transaction.atomic():
                StyleOB.objects.bulk_create(instances)

        chunked_data = [data_dicts[i:i + CHUNK_SIZE] for i in range(0, len(data_dicts), CHUNK_SIZE)]

        truncate_table(StyleOB)
        logger.info(f"Inserting {len(data_dicts)} unallocated records in {len(chunked_data)} chunks...")
        with ThreadPoolExecutor(max_workers=10) as executor:
            executor.map(insert_chunk, chunked_data)

        if not viaAPI:
            logger.info(f"Data saved successfully at {str(datetime.now())} hours!")
            logger.info(f"***************************************************\n\n")

        return success_response(message="Data processed and uploaded to Database", status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error in run_generate_style_ob: {str(e)} at {datetime.now()} hours!", exc_info=True)
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)
