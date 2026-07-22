import json
import logging
import os
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

import numpy as np
import pandas as pd
import requests
from django.db import transaction
from django.db.models import FloatField, Func
from rest_framework import status

from apps.absenteeism.models import PredictionData
from apps.absenteeism.utils import is_allowed_working_day
from apps.accounts.utils.response_handlers import error_response, success_response
from apps.data_engine.models import (
    AttendanceMaster,
    LocalHolidayCalendar,
    PayableWorkingDays,
)
from config.utils import truncate_table

from ..loading_plan import redistribute_production_plan
from ..loading_plan_optimization import process_df
from ..manning_generation_multiprocessing import (
    map_factory_floor,
)
from ..models import (
    ActiveEmployees,
    EMPFact,
    LoadingPlan,
    ManningSheetData,
    StyleOB,
    UnallocatedEmployees,
    WIPData,
)
from ..utils import (
    fetch_wip,
    transform_unallocated_to_on_hold_from_dict,
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


def run_styleob_file_upload(file):
    if True:
        if not file:
            return error_response(
                error="File is required", status=status.HTTP_400_BAD_REQUEST
            )

        try:
            df_Style_OB = pd.read_excel(file)
            df_Style_OB.dropna(subset=["code"], inplace=True)
            df_Style_OB = df_Style_OB.drop(
                columns=["color"], errors="ignore"
            )  # Removed color column
            df_Style_OB["code"] = (
                df_Style_OB["code"].str.replace(r"\s+", " ", regex=True).str.strip()
            )
            df_Style_OB["code"] = df_Style_OB["code"].str.replace(" ", "", regex=True)
            df_Style_OB = df_Style_OB[df_Style_OB["department"] == "Sewing"]

            ######new lines######################
            df_Style_OB["style"] = df_Style_OB["style"].str.lower().str.strip()
            df_Style_OB["style"] = (
                df_Style_OB["style"].str.replace(r"\s+", " ", regex=True).str.strip()
            )
            df_Style_OB["style"] = df_Style_OB["style"].str.replace(" ", "", regex=True)
            # df_Style_OB['color'] = df_Style_OB['color'].str.lower().str.strip()
            # df_Style_OB['color'] = df_Style_OB['color'].str.replace(r'\s+', ' ', regex=True).str.strip()
            # df_Style_OB['color'] = df_Style_OB['color'].str.replace(' ', '', regex=True)

            df_Style_OB = df_Style_OB.drop(
                columns=["created_at", "department", "type", "po_ref"]
            )
            df_Style_OB = df_Style_OB.drop_duplicates(
                subset=["style", "section", "code"], keep="first"
            )  # Removed color and op_seq
            df_Style_OB.dropna(
                subset=["style", "section", "op_seq", "operation", "code"]
            )  # Removed color

            # arrange in ascending order by op_seq
            df_Style_OB = (
                df_Style_OB.sort_values(by=["style", "section", "op_seq"])
                .groupby(["style", "section"], as_index=False)
                .apply(lambda x: x.sort_values(by=["op_seq"], ascending=True))
                .reset_index(drop=True)
            )

            # Delete all old entries before inserting new data
            StyleOB.objects.all().delete()

            records = [
                StyleOB(
                    style=row["style"],
                    section=row["section"],
                    op_seq=int(row["op_seq"]),
                    operation=row["operation"],
                    code=row["code"],
                    sam=float(row["sam"]),
                    color="BLACK",
                    machine_type=row["machine_type"],
                    machinist=row["machinist"],
                )
                for row in df_Style_OB.to_dict("records")
            ]

            # Delete all old entries before inserting new data
            truncate_table(StyleOB)

            # Insert data in chunks
            for i in range(0, len(records), CHUNK_SIZE):
                StyleOB.objects.bulk_create(records[i : i + CHUNK_SIZE])

            return success_response(
                message="File processed and data saved successfully",
                status=status.HTTP_201_CREATED,
            )
        except Exception as e:
            return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)

    return error_response(error="Invalid request", status=status.HTTP_400_BAD_REQUEST)


def run_loading_plan_file_upload(file):
    if True:
        if not file:
            return error_response(
                error="File is required", status=status.HTTP_400_BAD_REQUEST
            )

        try:
            df_load_plan = pd.read_excel(file, sheet_name=None)

            # Get last date of current year
            last_date_of_year = date(datetime.today().year, 12, 31)

            # Load the LocalHolidayCalendar data from the database
            queryset_local_holiday_calender = (
                LocalHolidayCalendar.objects.all().values()
            )
            local_holiday_calender_df = pd.DataFrame.from_records(
                queryset_local_holiday_calender
            )
            local_holiday_calender_df["date"] = pd.to_datetime(
                local_holiday_calender_df["date"]
            ).dt.date
            holiday_dates = set(local_holiday_calender_df["date"])

            # Get all payable working days from the database for the date range
            payable_dates = PayableWorkingDays.objects.all().values()
            payable_dates_df = pd.DataFrame.from_records(payable_dates)
            payable_dates_df["date"] = pd.to_datetime(payable_dates_df["date"]).dt.date
            payable_dates = set(payable_dates_df["date"])

            sheet_names_to_extract = [
                sheet for sheet in df_load_plan if sheet.startswith("KPR")
            ]
            sheets_dict = {
                sheet: df_load_plan[sheet] for sheet in sheet_names_to_extract
            }

            df_load_plan_all = []
            # final_df_all = [] # Commenting as not needed as of now

            for sheet_name, df in sheets_dict.items():
                logger.info(f"\nProcessing sheet: {sheet_name}")
                df["sheet_name"] = sheet_name
                df_load_plan, final_df_new = process_df(
                    df, holiday_dates, last_date_of_year, payable_dates
                )
                # Collect for later concatenation
                df_load_plan_all.append(df_load_plan)
                # final_df_all.append(final_df_new) # Commenting as not needed as of now

            # Concatenate after loop
            df_load_plan_combined = pd.concat(df_load_plan_all, ignore_index=True)
            # final_df_combined = pd.concat(final_df_all, ignore_index=True) # Commenting as not needed as of now

            # Insert data in chunks
            records = [
                LoadingPlan(
                    oc_no=row["OC NO"],
                    order_no=row["ORDER NO"],
                    cfm_date=row["CFM DATE"] if pd.notna(row["CFM DATE"]) else None,
                    merchant=row["MERCHANT"],
                    style=row["STYLE"],
                    buyer=row["BUYER"],
                    ls_ss=row["L/S-S/S"],
                    fabric_article=row["FABRIC ARTICLE"],
                    smv=row["SMV"],
                    del_date=row["DEL DATE"] if pd.notna(row["DEL DATE"]) else None,
                    month_code=row["MONTH CODE"],
                    qty_order=row["QTY ORDER"],
                    sheet_name=row["sheet_name"],
                    line=row["Line"],
                    week=row["Week"],
                    planned_qty=row["Planned Qty"],
                    date_start=row["Date_Start"]
                    if pd.notna(row["Date_Start"])
                    else None,
                    date_end=row["Date_End"] if pd.notna(row["Date_End"]) else None,
                    planned_dates=row["Planned_Dates"]
                    if pd.notna(row["Planned_Dates"])
                    else None,
                    raw_oc_no=row["raw_oc_no"],
                    raw_style=row["raw_style"],
                    raw_fabric_article=row["raw_fabric_article"],
                )
                for row in df_load_plan_combined.to_dict("records")
            ]

            with transaction.atomic():
                # Delete old data before inserting new records
                truncate_table(LoadingPlan)

                for i in range(0, len(records), CHUNK_SIZE):
                    LoadingPlan.objects.bulk_create(records[i : i + CHUNK_SIZE])

            run_generate_style_ob(viaAPI=False)

            return success_response(
                message="File processed and data saved successfully",
                status=status.HTTP_201_CREATED,
            )
        except Exception as e:
            return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
    return error_response(error="Invalid request", status=status.HTTP_400_BAD_REQUEST)


def run_loading_plan_file_upload_old(file, max_styles_per_day, custom_line_capacities):
    if True:
        if not file:
            return error_response(
                error="File is required", status=status.HTTP_400_BAD_REQUEST
            )

        try:
            df_load_plan = pd.read_excel(file, sheet_name=None)

            # Load the LocalHolidayCalendar data from the database
            queryset_local_holiday_calender = (
                LocalHolidayCalendar.objects.all().values()
            )
            local_holiday_calender_df = pd.DataFrame.from_records(
                queryset_local_holiday_calender
            )
            local_holiday_calender_df["date"] = pd.to_datetime(
                local_holiday_calender_df["date"]
            ).dt.date
            holiday_dates = set(local_holiday_calender_df["date"])

            sheet_names_to_extract = [
                sheet for sheet in df_load_plan if sheet.startswith("KPR")
            ]
            sheets_dict = {
                sheet: df_load_plan[sheet] for sheet in sheet_names_to_extract
            }

            # Combine all selected sheets into a single DataFrame and add a sheet name column
            df_load_plan = pd.concat(
                [df.assign(sheet_name=sheet) for sheet, df in sheets_dict.items()],
                ignore_index=True,
            )

            # Save the 'sheet_name' column separately before modifying headers
            sheet_name_column = df_load_plan["sheet_name"].copy()

            # Remove the first 5 rows (assuming header is on row 6)
            df_load_plan = df_load_plan.iloc[5:].reset_index(drop=True)

            # Step 9: Set the first row as the new column headers
            df_load_plan.columns = df_load_plan.iloc[0]  # Use the first row as header
            df_load_plan = df_load_plan.iloc[1:].reset_index(
                drop=True
            )  # Drop the first row after setting headers

            # Reattach the 'sheet_name' column correctly aligned
            df_load_plan["sheet_name"] = sheet_name_column.iloc[5:].reset_index(
                drop=True
            )  # Ensures proper alignment

            # Drop unnamed or unnecessary columns (like 'KPR L1' and 'NaN' columns)
            # columns_to_drop = [col for col in df_load_plan.columns if 'KPR L' in str(col) or str(col) == 'NaN']
            # df_load_plan = df_load_plan.drop(columns=columns_to_drop, errors='ignore')

            df_load_plan.dropna(how="all", inplace=True)
            df_load_plan = df_load_plan.iloc[2:].reset_index(drop=True)
            df_load_plan = df_load_plan.drop(
                columns=[
                    col
                    for col in df_load_plan.columns
                    if "KPR L" in str(col)
                    or str(col) == "NaN"
                    or col
                    in [
                        "Unnamed",
                        "FABRIC",
                        "FABRIC TYPE",
                        "REMARKS",
                        "IN HOUSE",
                        "NEW INH HOUSE",
                        "APPROVAL OF FIT/PP",
                        "Release of Production file & approved sample",
                        "Revised F/R",
                        "LC received",
                        "TRIMS AVAILABILITY",
                        "BAL TO LOAD",
                    ]
                ],
                errors="ignore",
            )
            df_load_plan = df_load_plan.drop(
                columns=[
                    col
                    for col in df_load_plan.columns
                    if str(col).strip().lower() == "nan"
                ],
                errors="ignore",
            )
            df_load_plan = df_load_plan.dropna(axis=1, how="all")  # 44444444444444
            df_load_plan = df_load_plan[
                df_load_plan.drop(columns=["sheet_name"], errors="ignore")
                .notna()
                .any(axis=1)
            ]

            df_load_plan = df_load_plan[df_load_plan["OC NO"].notna()]
            df_load_plan["OC NO"] = df_load_plan["OC NO"].astype(str).str.strip()
            unwanted_patterns = ["KANAKPURA", "LINE", "DATE", "OC"]
            df_load_plan = df_load_plan[
                ~df_load_plan["OC NO"].str.contains(
                    "|".join(unwanted_patterns), case=False, na=False
                )
            ]
            # df_load_plan['Line'] = df_load_plan['sheet_name'].str.extract(r'(\d+)$').astype(float).astype('Int64')
            df_load_plan["Line"] = (
                df_load_plan["sheet_name"]
                .str.strip()
                .str.extract(r"(\d+)$")
                .astype(float)
                .astype("Int64")
            )
            df_load_plan["Line"] = "Line " + df_load_plan["Line"].astype(str)

            # Identify columns that start with 'wk'
            wk_columns = [
                col
                for col in df_load_plan.columns
                if isinstance(col, str) and col.startswith("wk")
            ]

            # Replace 'FAB', 'DEL', NaN, and empty strings in 'wk%' columns with 0
            df_load_plan[wk_columns] = df_load_plan[wk_columns].replace(
                ["FAB", "DEL", np.nan, ""], 0
            )

            ############################################################################################################

            # Convert 'wk%' columns to integers
            # df_load_plan[wk_columns] = df_load_plan[wk_columns].apply(pd.to_numeric, errors='coerce').fillna(0).astype(int)

            # Drop rows where all 'wk%' columns contain only 0
            # df_load_plan = df_load_plan[~(df_load_plan[wk_columns] == 0).all(axis=1)]

            # Melt the dataframe to transform 'wk' columns into rows
            df_load_plan = df_load_plan.melt(
                id_vars=[col for col in df_load_plan.columns if col not in wk_columns],
                value_vars=wk_columns,
                var_name="Week",
                value_name="Planned Qty",
            )

            # Extract the Week Number as an integer
            df_load_plan["Week"] = (
                df_load_plan["Week"].str.extract(r"wk (\d+)")[0].astype(int)
            )

            # Create a mapping of Week Number to Date Range from the column names
            week_date_mapping = {
                int(col.split()[1]): col.split(" ", 2)[-1]
                for col in wk_columns
                if col.startswith("wk")
            }

            # Map the extracted week number to its corresponding date range
            df_load_plan["Dates"] = df_load_plan["Week"].map(week_date_mapping)

            # Remove rows where 'Planned Qty' is 0 or NaN
            df_load_plan = df_load_plan[df_load_plan["Planned Qty"] > 0]

            ###########################################################################################################

            # Convert 'CFM DATE' to datetime

            df_load_plan["CFM DATE"] = pd.to_datetime(
                df_load_plan["CFM DATE"], errors="coerce"
            )

            # Replace 'DEL DATE' with 'NEW DEL' where 'NEW DEL' has a valid date
            df_load_plan["DEL DATE"] = df_load_plan["NEW DEL"].combine_first(
                df_load_plan["DEL DATE"]
            )

            # Drop the 'NEW DEL' column
            df_load_plan.drop(columns=["NEW DEL"], inplace=True)

            # Get the current year
            current_year = datetime.now().year

            # Split the Dates column by '-'
            df_load_plan[["Date_Start", "Date_End"]] = df_load_plan["Dates"].str.split(
                "-", expand=True
            )

            # Trim whitespace
            df_load_plan["Date_Start"] = df_load_plan["Date_Start"].str.strip()
            df_load_plan["Date_End"] = df_load_plan["Date_End"].str.strip()

            # Append the current year and format as dd/mm/yy
            df_load_plan["Date_Start"] = df_load_plan["Date_Start"] + f"/{current_year}"
            df_load_plan["Date_End"] = df_load_plan["Date_End"] + f"/{current_year}"

            # Convert to datetime format and reformat as string dd/mm/yy
            df_load_plan["Date_Start"] = pd.to_datetime(
                df_load_plan["Date_Start"], format="%d/%m/%Y"
            ).dt.strftime("%d/%m/%y")
            df_load_plan["Date_End"] = pd.to_datetime(
                df_load_plan["Date_End"], format="%d/%m/%Y"
            ).dt.strftime("%d/%m/%y")

            # Drop the original Dates column
            df_load_plan.drop(columns=["Dates"], inplace=True)

            ##############################################################################################################

            sl_columns = ["OC NO", "ORDER NO", "STYLE", "FABRIC ARTICLE"]

            #####################New lines#############
            for col in sl_columns:
                if col in df_load_plan.columns:
                    df_load_plan[col] = df_load_plan[col].astype(str).str.strip()
                    df_load_plan[col] = df_load_plan[col].str.replace(
                        r"\s+", " ", regex=True
                    )
                    df_load_plan[col] = df_load_plan[col].str.replace(
                        " ", "", regex=True
                    )
                    df_load_plan[col] = df_load_plan[col].str.lower()

            # Convert Date_Start and Date_End to datetime format
            df_load_plan["Date_Start"] = pd.to_datetime(
                df_load_plan["Date_Start"], format="%d/%m/%y", errors="coerce"
            )
            df_load_plan["Date_End"] = pd.to_datetime(
                df_load_plan["Date_End"], format="%d/%m/%y", errors="coerce"
            )

            # Create an empty list to store expanded data
            expanded_rows = []

            def is_included_saturday(date):
                if date.weekday() == 5:  # 5 = Saturday
                    first_saturday = date.replace(day=1) + pd.DateOffset(
                        days=(5 - date.replace(day=1).weekday() + 7) % 7
                    )
                    fifth_saturday = first_saturday + pd.DateOffset(
                        weeks=4
                    )  # Calculate 5th Saturday (if exists)
                    return date == first_saturday or (
                        fifth_saturday.month == date.month and date == fifth_saturday
                    )
                return False

            # Iterate through each row to generate dates and distribute planned quantity
            for row in df_load_plan.to_dict("records"):
                start_date = row["Date_Start"]
                end_date = row["Date_End"]

                # Generate full date range
                full_date_range = pd.date_range(start=start_date, end=end_date)
                # Remove holidays from the date range
                full_date_range = full_date_range[~full_date_range.isin(holiday_dates)]

                # Filter out Sundays and 1st & 5th Saturdays
                # working_days = [date for date in full_date_range if date.weekday() != 6 and not is_excluded_saturday(date)]

                # Keep only weekdays + 1st & 5th Saturdays (drop other Saturdays & Sundays)
                working_days = [
                    date
                    for date in full_date_range
                    if date.weekday() != 6
                    and (date.weekday() != 5 or is_included_saturday(date))
                ]

                # Number of working days after filtering
                num_working_days = len(working_days)

                # Calculate distributed quantity only for working days
                planned_qty_per_day = (
                    row["Planned Qty"] / num_working_days if num_working_days > 0 else 0
                )

                # Calculate distributed quantity only for working days
                qty_order_per_day = (
                    row["QTY ORDER"] / num_working_days if num_working_days > 0 else 0
                )

                # Create new rows for each valid working date
                for planned_date in working_days:
                    new_row = row.copy()
                    new_row["Planned Dates"] = planned_date.strftime(
                        "%d/%m/%y"
                    )  # Format as dd/mm/yy
                    new_row["Planned Qty"] = round(
                        planned_qty_per_day, 2
                    )  # Distribute quantity among working days
                    new_row["QTY ORDER"] = round(
                        qty_order_per_day, 2
                    )  # Distribute quantity among working days
                    expanded_rows.append(new_row)

            # Create new DataFrame from expanded rows
            df_load_plan_transformed = pd.DataFrame(expanded_rows)
            df_load_plan_transformed["Planned Dates"] = pd.to_datetime(
                df_load_plan_transformed["Planned Dates"],
                format="%d/%m/%y",
                errors="coerce",
            )

            # output_path = 'csv_files/df_load_plan_transformed.csv'
            # df_load_plan_transformed.to_csv(output_path, index=False)

            # Get unique production lines
            unique_lines = df_load_plan_transformed["Line"].unique().tolist()

            # Prepare optimization parameters from form
            # Variables passed directly
            max_styles_per_day = int(max_styles_per_day) if max_styles_per_day else 2
            custom_line_capacities = (
                custom_line_capacities  # Dictionary {line_name: capacity}
            )

            if custom_line_capacities:
                custom_line_capacities = json.loads(custom_line_capacities)

            # Identify order-related columns
            # order_identifiers = [col for col in ['ORDER NO', 'OC NO'] if col in df_load_plan_transformed.columns]
            order_identifiers = []
            if "ORDER NO" in df_load_plan_transformed.columns:
                order_identifiers.append("ORDER NO")
            if "OC NO" in df_load_plan_transformed.columns:
                order_identifiers.append("OC NO")

            if order_identifiers:
                logger.info(
                    f"Order identifier columns found: {', '.join(order_identifiers)}"
                )
                logger.info("Order references will be preserved during optimization")

            # Handle fabric article column
            if "FABRIC ARTICLE" not in df_load_plan_transformed.columns:
                # Automatically add default fabric article
                df_load_plan_transformed["FABRIC ARTICLE"] = "DEFAULT"

            # Use default capacity (1300) if custom capacities are not provided
            if not custom_line_capacities:
                custom_line_capacities = {line: 1300 for line in unique_lines}

            # Validate line capacities
            for line, capacity in custom_line_capacities.items():
                if capacity <= 0:
                    return error_response(
                        error=f"Invalid capacity for line {line}. Must be positive.",
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            keep_split_id = False
            if order_identifiers:
                keep_split_tracking = "y"  # input("\nDo you want to keep split tracking IDs in the output? (y/n): ").lower().strip()
                keep_split_id = (
                    keep_split_tracking == "y" or keep_split_tracking == "yes"
                )
                if keep_split_id:
                    logger.info("Split tracking IDs will be kept in the final output")
                else:
                    logger.info(
                        "Split tracking IDs will be removed from the final output"
                    )

            merge_with_original = "n"  # input("\nDo you want to preserve all original columns in your data? (y/n): ").lower().strip()
            preserve_columns = (
                merge_with_original == "y" or merge_with_original == "yes"
            )

            confirm = (
                "y"  # input("\nProceed with optimization? (y/n): ").lower().strip()
            )
            if confirm != "y" and confirm != "yes":
                logger.info("Optimization cancelled.")
                return

            logger.info("\nStarting production plan optimization...")
            logger.info("Considering both style and fabric article in sequencing...")
            if order_identifiers:
                logger.info(
                    "Preserving original order identifiers across allocations..."
                )

            # Run optimization
            new_plan, original_total = redistribute_production_plan(
                df_load_plan_transformed,
                line_capacities=custom_line_capacities,
                respect_date_ranges=True,
                max_styles_per_day=max_styles_per_day,
            )

            # Drop Split_ID if needed
            if "Split_ID" in new_plan.columns:
                new_plan = new_plan.drop("Split_ID", axis=1)
                logger.info("Dropped Split_ID column")

            # Define the columns to group by
            group_columns = [
                "OC NO",
                "ORDER NO",
                "CFM DATE",
                "MERCHANT",
                "STYLE",
                "BUYER",
                "L/S-S/S",
                "FABRIC ARTICLE",
                "SMV",
                "DEL DATE",
                "MONTH CODE",
                "QTY ORDER",
                "sheet_name",
                "Line",
                "Week",
                "Date_Start",
                "Date_End",
                "Planned Dates",
            ]

            # Filter to columns that actually exist in the DataFrame
            existing_columns = [col for col in group_columns if col in new_plan.columns]
            logger.info(
                f"Grouping by {len(existing_columns)} columns: {', '.join(existing_columns)}"
            )

            # Handle date columns specially - convert all date columns to string
            for col in existing_columns:
                if "DATE" in col.upper() or "Date" in col:
                    try:
                        # Only convert if it's actually a datetime column
                        if pd.api.types.is_datetime64_dtype(new_plan[col]):
                            logger.info(f"Converting datetime column to string: {col}")
                            new_plan[col] = new_plan[col].dt.strftime("%Y-%m-%d")
                    except Exception as e:
                        logger.info(
                            f"Warning: Could not convert date column {col}: {str(e)}"
                        )

            # Perform the grouping with string-converted date columns
            try:
                grouped_df = new_plan.groupby(existing_columns, as_index=False).agg(
                    {"Planned Qty": "sum"}
                )
                grouped_total = grouped_df["Planned Qty"].sum()

                logger.info(f"Total quantity after grouping: {grouped_total}")
                logger.info(f"Difference: {grouped_total - original_total}")

                if (
                    abs(grouped_total - original_total) > 0.1
                ):  # Allow for minor rounding
                    logger.info("WARNING: Quantity change detected after grouping!")

                    # Use the manual approach as a fallback
                    logger.info("Falling back to manual grouping method...")

                    # Manual grouping approach
                    grouped_data = {}

                    for row in new_plan.to_dict("records"):
                        # Create a key from the grouping columns
                        key_parts = []
                        for col in existing_columns:
                            val = row[col]
                            # Convert values to strings to avoid data type issues
                            if pd.isna(val):
                                val = "NA"
                            else:
                                val = str(val)
                            key_parts.append(val)

                        key = tuple(key_parts)

                        # Add to grouped data
                        if key in grouped_data:
                            grouped_data[key]["qty"] += row["Planned Qty"]
                            grouped_data[key]["count"] += 1
                        else:
                            grouped_data[key] = {
                                "qty": row["Planned Qty"],
                                "row": row.copy(),
                                "count": 1,
                            }

                    # Convert back to DataFrame
                    result_rows = []
                    for key, data in grouped_data.items():
                        row_copy = data["row"].copy()
                        row_copy["Planned Qty"] = data["qty"]
                        result_rows.append(row_copy)

                    grouped_df = pd.DataFrame(result_rows)
                    manual_total = grouped_df["Planned Qty"].sum()

                    logger.info(f"Manual grouping result: {len(grouped_df)} rows")
                    logger.info(f"Total quantity after manual grouping: {manual_total}")
                    logger.info(
                        f"Difference from original: {manual_total - original_total}"
                    )

                # Use the grouped DataFrame (either from pandas or manual approach)
                new_plan = grouped_df

            except Exception as e:
                logger.info(f"ERROR during grouping: {str(e)}")
                logger.info("Continuing with ungrouped data to preserve quantities")

            # Sort by Planned Dates
            if "Planned Dates" in new_plan.columns:
                # If we converted dates to strings, convert back to datetime for sorting
                if not pd.api.types.is_datetime64_dtype(new_plan["Planned Dates"]):
                    try:
                        new_plan["Planned Dates"] = pd.to_datetime(
                            new_plan["Planned Dates"]
                        )
                    except:
                        logger.info(
                            "Warning: Could not convert Planned Dates back to datetime for sorting"
                        )

                new_plan = new_plan.sort_values("Planned Dates", ascending=True)
                logger.info("Sorted data by Planned Dates in ascending order")

            logger.info(
                f"Final dataframe has {len(new_plan)} rows with total quantity {new_plan['Planned Qty'].sum()}"
            )

            ################################################################################################

            # output_file = 'csv_files/optimized_production_plan_order_preserved_2.csv' ###Change this file name to the input table filename for the manning sheet (mostly df_load_plan_transformed)
            # new_plan.to_csv(output_file, index=False)
            # print(f"\nOptimized production plan saved to '{output_file}'")

            # Delete old data before inserting new records
            truncate_table(LoadingPlan)

            # Insert data in chunks
            records = [
                LoadingPlan(
                    oc_no=row["OC NO"],
                    order_no=row["ORDER NO"],
                    cfm_date=row["CFM DATE"] if pd.notna(row["CFM DATE"]) else None,
                    merchant=row["MERCHANT"],
                    style=row["STYLE"],
                    buyer=row["BUYER"],
                    ls_ss=row["L/S-S/S"],
                    fabric_article=row["FABRIC ARTICLE"],
                    smv=row["SMV"],
                    del_date=row["DEL DATE"] if pd.notna(row["DEL DATE"]) else None,
                    month_code=row["MONTH CODE"],
                    qty_order=row["QTY ORDER"],
                    sheet_name=row["sheet_name"],
                    line=row["Line"],
                    week=row["Week"],
                    planned_qty=row["Planned Qty"],
                    date_start=row["Date_Start"]
                    if pd.notna(row["Date_Start"])
                    else None,
                    date_end=row["Date_End"] if pd.notna(row["Date_End"]) else None,
                    planned_dates=row["Planned Dates"]
                    if pd.notna(row["Planned Dates"])
                    else None,
                )
                for row in new_plan.to_dict("records")
            ]

            with transaction.atomic():
                for i in range(0, len(records), CHUNK_SIZE):
                    LoadingPlan.objects.bulk_create(records[i : i + CHUNK_SIZE])

            ####statistics
            if "FABRIC ARTICLE" in new_plan.columns:
                style_fabric_combos = new_plan[
                    ["STYLE", "FABRIC ARTICLE"]
                ].drop_duplicates()
                unique_styles = new_plan["STYLE"].nunique()
                unique_fabrics = new_plan["FABRIC ARTICLE"].nunique()

                logger.info("\nPlan statistics:")
                logger.info(f"Total unique styles: {unique_styles}")
                logger.info(f"Total unique fabric articles: {unique_fabrics}")
                logger.info(
                    f"Total unique style+fabric combinations: {len(style_fabric_combos)}"
                )

            if order_identifiers:
                id_field = order_identifiers[
                    0
                ]  # Use the first identifier for statistics
                total_orders = new_plan[id_field].nunique()
                total_rows = len(new_plan)

                logger.info("\nOrder statistics:")
                logger.info(f"Total unique orders: {total_orders}")
                logger.info(f"Total rows in optimized plan: {total_rows}")

                if "Split_ID" in new_plan.columns:
                    split_ids = [x for x in new_plan["Split_ID"] if not pd.isna(x)]
                    order_splits = {}

                    for split_id in split_ids:
                        row_id = split_id.split("_")[0]
                        if row_id not in order_splits:
                            order_splits[row_id] = 0
                        order_splits[row_id] += 1

                    split_orders = sum(
                        1 for count in order_splits.values() if count > 1
                    )
                    max_splits = max(order_splits.values()) if order_splits else 0

                    logger.info(
                        f"Orders split across multiple days: {split_orders} ({split_orders / total_orders * 100:.1f}%)"
                    )
                    logger.info(f"Maximum splits for a single order: {max_splits}")

            return success_response(
                message="File processed and data saved successfully",
                status=status.HTTP_201_CREATED,
            )
        except Exception as e:
            return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
    return error_response(error="Invalid request", status=status.HTTP_400_BAD_REQUEST)


def run_emp_fact_file_upload(file):
    if True:
        if not file:
            return error_response(
                error="File is required", status=status.HTTP_400_BAD_REQUEST
            )

        try:
            df_emp_fact = pd.read_csv(file)
            df_emp_fact.dropna(subset=["EMPLOYEE ID"], inplace=True)

            records = [
                EMPFact(
                    employee_id=int(row["EMPLOYEE ID"]),
                    employee_name=row["EMPLOYEE NAME"],
                    line=row["LINE"],
                    factory=row["FACTORY"],
                    floor=row["FLOOR"],
                    section=row["SECTION"],
                    designation=row["DESIGNATION"],
                    code=row["CODE"],
                    operation=row["OPERATION"],
                    type=row["TYPE"],
                    sam=float(row["SAM"]),
                    peak_capacity=int(row["PEAK CAPACITY"]),
                    average_capacity=int(row["AVERAGE CAPACITY"]),
                    machine=row["MACHINE"],
                    status=row["STATUS"],
                )
                for row in df_emp_fact.to_dict("records")
            ]

            EMPFact.objects.all().delete()
            EMPFact.objects.bulk_create(records, batch_size=1000)

            return success_response(
                message="File processed and data saved successfully",
                status=status.HTTP_201_CREATED,
            )
        except Exception as e:
            return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)

    return error_response(error="Invalid request", status=status.HTTP_400_BAD_REQUEST)


def run_wip_file_upload(file):
    if True:
        if not file:
            return error_response(
                error="File is required", status=status.HTTP_400_BAD_REQUEST
            )

        try:
            df_wip_data = pd.read_csv(file)

            records = [
                WIPData(
                    # row['color'].upper() if row['color'] else row['color']
                    oc_no=row["OC NO"].lower() if row["OC NO"] else row["OC NO"],
                    order_no=row["ORDER NO"],
                    buyer=row["BUYER"].lower() if row["BUYER"] else row["BUYER"],
                    style=row["STYLE"].lower() if row["STYLE"] else row["STYLE"],
                    line=row["LINE"],
                    color=row["COLOR"].lower() if row["COLOR"] else row["COLOR"],
                    section=row["SECTION"],
                    op_seq=row["OP_SEQ"],
                    operation=row["OPERATION"],
                    code=row["CODE"],
                    wip_qty=row["WIP  QTY"],
                )
                for row in df_wip_data.to_dict("records")
            ]

            WIPData.objects.all().delete()
            WIPData.objects.bulk_create(records, batch_size=1000)

            return success_response(
                message="File processed and data saved successfully",
                status=status.HTTP_201_CREATED,
            )
        except Exception as e:
            return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)

    return error_response(error="Invalid request", status=status.HTTP_400_BAD_REQUEST)


def run_fetch_emp_attendance_rockhr():
    try:
        return (
            fetch_and_transform_emp_attendance()
        )  # Call the function without needing a request
    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)


def run_fetch_emp_details_rockhr():
    try:
        return (
            fetch_and_transform_empdetails()
        )  # Call the function without needing a request
    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)


def fetch_and_transform_emp_attendance(run_type=None):
    try:
        soap_url = "https://103.31.215.22:5353/rock_HR_API.asmx"
        soap_action = "http://tempuri.org/EmpAttd"
        today = datetime.today().date()

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": soap_action,
        }

        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
            <soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
                        xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
            <soap:Body>
                <EmpAttd xmlns="http://tempuri.org/">
                <strDate>{today}</strDate>
                <lngEmpAttdCoCode>{COMPANY_CODE}</lngEmpAttdCoCode>
                </EmpAttd>
            </soap:Body>
            </soap:Envelope>
        """
        logger.info(f"Fetching API: {soap_url}")

        # Disable SSL verification due to certificate issues
        response = requests.post(
            soap_url, data=soap_body, headers=headers, verify=False
        )

        # Parse the XML response
        root = ET.fromstring(response.text)
        namespace = {
            "soap": "http://schemas.xmlsoap.org/soap/envelope/",
            "ns": "http://tempuri.org/",
        }
        result = root.find(".//ns:EmpAttdResult", namespaces=namespace)

        if result is None:
            return error_response(
                error=f"No data found for employee attendance api for {today}",
                status=status.HTTP_404_NOT_FOUND,
            )

        # Convert JSON string to Python list
        data_list = json.loads(result.text)

        # Create DataFrame from recieved data
        try:
            df_attendance = pd.DataFrame(data_list)
        except Exception as e:
            return error_response(
                error=f"Error creating DataFrame: {str(e)}",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Convert values that are not 'A', 'P', 'AP', or 'PA' to 'A'
        df_attendance["ATTD_STATUS"] = df_attendance["ATTD_STATUS"].apply(
            lambda x: "A" if x not in ["A", "P", "AP", "PA"] else x
        )

        current_time = datetime.now()

        def get_attendance_status(row):
            status = row.get("ATTD_STATUS")
            intime = row.get("INTIME")
            outtime = row.get("OUTTIME")

            if status == "PA":
                return "A" if outtime else "P"
            elif status == "AP":
                return "P" if intime else "A"
            elif status in ["P", "A"]:
                return status
            else:
                return "A"

        # Apply the function to each row to determine Attendance_Status
        df_attendance["status"] = df_attendance.apply(get_attendance_status, axis=1)

        df_attendance.rename(
            columns={
                "LOGDATE": "attendance_date",
                "EMPCODE": "employee_id",
                "EMPNAME": "employee_name",
            },
            inplace=True,
        )

        df_attendance["attendance_date"] = pd.to_datetime(
            df_attendance["attendance_date"]
        ).dt.date

        df_attendance["last_updated"] = pd.to_datetime(
            df_attendance["attendance_date"]
        ).dt.date

        # Convert INTIME and OUTTIME to datetime format
        df_attendance["INTIME"] = pd.to_datetime(
            df_attendance["INTIME"], format="%d-%b-%Y %H:%M:%S", errors="coerce"
        )
        df_attendance["OUTTIME"] = pd.to_datetime(
            df_attendance["OUTTIME"], format="%d-%b-%Y %H:%M:%S", errors="coerce"
        )

        # Function to fetch time
        def fetch_time(row):
            if pd.notnull(row["OUTTIME"]):
                return row["OUTTIME"].strftime("%H:%M:%S")
            elif pd.notnull(row["INTIME"]):
                return row["INTIME"].strftime("%H:%M:%S")
            return None

        # Apply the function to the dataframe
        df_attendance["last_updated"] = df_attendance.apply(fetch_time, axis=1)

        # df_attendance.drop(columns=["ATTD_STATUS", "INTIME", "OUTTIME"], inplace=True)

        df_attendance = df_attendance.applymap(
            lambda x: x.capitalize() if isinstance(x, str) else x
        )

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

        # Convert both columns to integer type (safe conversion)
        df_attendance["employee_id"] = (
            df_attendance["employee_id"].astype(str).str.replace(r"\D", "", regex=True)
        )
        df_attendance["employee_id"] = pd.to_numeric(
            df_attendance["employee_id"], errors="coerce"
        ).astype("Int64")
        df_active_employees["Emp No"] = pd.to_numeric(
            df_active_employees["Emp No"], errors="coerce"
        ).astype("Int64")

        # Filter df_attendance to keep only matching employee_ids
        df_attendance_filtered = df_attendance[
            df_attendance["employee_id"].isin(df_active_employees["Emp No"])
        ]

        # Now safe to merge
        merged_df = pd.merge(
            df_attendance_filtered,
            df_active_employees,
            left_on="employee_id",
            right_on="Emp No",
            how="left",
        )
        updated_df = merged_df[
            [
                "attendance_date",
                "employee_id",
                "employee_name",
                "ATTD_STATUS",
                "INTIME",
                "OUTTIME",
                "status_x",
            ]
        ]
        updated_df = updated_df.rename(columns={"status_x": "status"})

        # Use map instead of applymap to avoid warnings
        if hasattr(updated_df, "map"):
            updated_df = updated_df.map(
                lambda x: x.upper() if isinstance(x, str) else x
            )
        else:
            updated_df = updated_df.applymap(
                lambda x: x.upper() if isinstance(x, str) else x
            )

        updated_df.to_csv("csv_files/attendance.csv", index=False)

        merged_df[["factory", "floor"]] = pd.DataFrame(
            merged_df["Line"].apply(map_factory_floor).tolist(), index=merged_df.index
        )

        # Prepare all data as a list of dictionaries first (faster than processing row by row)
        data_dicts = []
        # Convert DataFrame to list of dicts (much faster than row iteration)
        for row in merged_df.to_dict("records"):
            data_dict = {
                "attendance_date": row["attendance_date"],
                "employee_id": row["employee_id"],
                "employee_name": row["employee_name"],
                "status": row[
                    "status_x"
                ],  # status_x is the status column from df_attendance
                "last_updated": row["last_updated"]
                if pd.notnull(row["last_updated"])
                else current_time.strftime("%H:%M:%S"),
                "early_departure": False,
                "line": row["Line"]
                if pd.notnull(row["Line"])
                else "N/A",  # Coming from df_active_employees
                "factory": row["factory"]
                if pd.notnull(row["factory"])
                else "N/A",  # Coming from df_active_employees
                "floor": row["floor"]
                if pd.notnull(row["floor"])
                else "N/A",  # Coming from df_active_employees
                "section": row["Section"]
                if pd.notnull(row["Section"])
                else "N/A",  # Coming from df_active_employees
                "type": "N/A",
            }
            data_dicts.append(data_dict)

        # Delete data for today's date before inserting new data
        AttendanceMaster.objects.filter(attendance_date=current_time.date()).delete()

        # Process in chunks to avoid memory issues
        for i in range(0, len(data_dicts), CHUNK_SIZE):
            chunk_dicts = data_dicts[i : i + CHUNK_SIZE]

            # Convert dictionaries to model instances
            model_instances = [AttendanceMaster(**d) for d in chunk_dicts]

            # Use a single transaction for the chunk
            with transaction.atomic():
                AttendanceMaster.objects.bulk_create(model_instances, batch_size=1000)

        if run_type is not None and run_type == "noon":
            raw_data = []
            for row in merged_df.to_dict("records"):
                if row["status_x"] == "A":
                    raw_data.append(
                        {
                            "date": row["attendance_date"],
                            "empcode": row["employee_id"],
                            "name": row["employee_name"],
                            "attendance": row[
                                "status_x"
                            ],  # status_x is the status column from df_attendance
                            "department": row["Line"].upper()
                            if pd.notnull(row["Line"])
                            else "N/A",  # Coming from df_active_employees
                            "section": row["Section"].upper()
                            if pd.notnull(row["Section"])
                            else "N/A",  # Coming from df_active_employees
                        }
                    )
            # Convert to DataFrame
            df_data = pd.DataFrame(raw_data)

            # Drop duplicates based on 'empcode' and 'date'
            df_data = df_data.drop_duplicates(
                subset=[
                    "date",
                    "empcode",
                    "name",
                    "department",
                    "section",
                    "attendance",
                ]
            )

            # Convert back to list of dicts
            absenteeism_data = df_data.to_dict(orient="records")

            # # Delete the data that is less than the date 3 years agp
            # cutoff_date = date.today().replace(year=date.today().year - 3)
            # PredictionData.objects.filter(date__lt=cutoff_date).delete()

            # Process in chunks
            for i in range(0, len(absenteeism_data), CHUNK_SIZE):
                chunk_dicts = absenteeism_data[i : i + CHUNK_SIZE]
                model_instances = [PredictionData(**d) for d in chunk_dicts]
                with transaction.atomic():
                    PredictionData.objects.bulk_create(
                        model_instances, ignore_conflicts=True
                    )

        return success_response(
            message="Data processed and uploaded to Database",
            data=data_list,
            status=status.HTTP_200_OK,
        )
    except Exception as e:
        return error_response(
            error=f"Error in RockHR API: {str(e)}", status=status.HTTP_400_BAD_REQUEST
        )


def fetch_and_transform_empdetails():
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

        soap_url = "https://103.31.215.22:5353/rock_HR_API.asmx"
        soap_action = "http://tempuri.org/EmpDetails"

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": soap_action,
        }

        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
            <soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
                        xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
            <soap:Body>
                <EmpDetails xmlns="http://tempuri.org/">
                    <lngEmpDetailsCoCode>{COMPANY_CODE}</lngEmpDetailsCoCode>
                </EmpDetails>
            </soap:Body>
            </soap:Envelope>
        """
        logger.info(f"Fetching API: {soap_url}")

        # Disable SSL verification due to certificate issues
        response = requests.post(
            soap_url, data=soap_body, headers=headers, verify=False
        )

        # Parse the XML response
        root = ET.fromstring(response.text)
        namespace = {
            "soap": "http://schemas.xmlsoap.org/soap/envelope/",
            "ns": "http://tempuri.org/",
        }
        result = root.find(".//ns:EmpDetailsResult", namespaces=namespace)

        if result is None:
            return error_response(
                error="No data found for employee details api.",
                status=status.HTTP_404_NOT_FOUND,
            )

        # Convert JSON string to Python list
        data_list = json.loads(result.text)

        df = pd.DataFrame(data_list)

        # Create DataFrame from recieved data
        try:
            df = pd.DataFrame(data_list)
        except Exception as e:
            return error_response(
                error=f"Error creating DataFrame: {str(e)}",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Make all values lowercase
        df = df.applymap(lambda x: x.lower() if isinstance(x, str) else x)

        # Allowed values
        allowed_values = ["back", "collar", "sleeve", "cuff", "front", "assembly"]

        # Keep only rows where 'operation' is in allowed_values
        df = df[df["SECTION_NAME"].isin(allowed_values)]

        # Split "Department" into "Line"
        df["line"] = df["LINE_NAME"].str.extract(r"(?i)^(line \d+)")
        df["machinist"] = df["MACHENIST"] == "direct machinist"

        # Keeping only Machinists and Floaters employees
        df = df[df["machinist"] == True]
        df = df[
            df["DESIGNATION"].astype(str).str.lower().isin(["machinist", "floaters"])
        ]

        df.drop(
            columns=["LINE_NAME", "EMAIL_ID", "OPERATIONS", "MACHENIST"], inplace=True
        )  # Drop the original column if needed
        df.rename(
            columns={
                "EMPCODE": "employee_id",
                "EMPLOYEE_NAME": "employee_name",
                "DESIGNATION": "designation",
                "SERVICE_YRS": "service_years",
                "STATUS": "status",
                "GENDER": "gender",
                "SECTION_NAME": "section",
            },
            inplace=True,
        )

        df = df.applymap(lambda x: x.capitalize() if isinstance(x, str) else x)
        df.dropna(subset=["line"], inplace=True)  # Drop rows with NaN in "line" column

        # Prepare all data as a list of dictionaries first (faster than processing row by row)
        data_dicts = []
        # Convert DataFrame to list of dicts (much faster than row iteration)
        for row in df.to_dict("records"):
            data_dict = {
                "employee_id": row["employee_id"],
                "employee_name": row["employee_name"],
                "line": row["line"],
                "section": row["section"],
                "designation": row["designation"],
                "machinist": row["machinist"],
                "service_years": row["service_years"],
                "status": row["status"],
                "gender": row["gender"],
            }
            data_dicts.append(data_dict)

        # Truncate the table before inserting new data
        truncate_table(ActiveEmployees)

        # Process in chunks to avoid memory issues
        for i in range(0, len(data_dicts), CHUNK_SIZE):
            chunk_dicts = data_dicts[i : i + CHUNK_SIZE]

            # Convert dictionaries to model instances
            model_instances = [ActiveEmployees(**d) for d in chunk_dicts]

            # Use a single transaction for the chunk
            with transaction.atomic():
                ActiveEmployees.objects.bulk_create(model_instances, batch_size=1000)

        return success_response(
            message="RockHR Data for Active Employees processed and uploaded to Database",
            status=status.HTTP_200_OK,
        )
    except Exception as e:
        return error_response(
            error=f"Error in RockHR API: {str(e)}", status=status.HTTP_400_BAD_REQUEST
        )


def run_fetch_wip_data_api():
    try:
        viaAPI = True
        return run_fetch_wip_data(viaAPI)
    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)


def run_fetch_wip_data(viaAPI):
    try:
        today = datetime.today().date()
        manning_queryset = ManningSheetData.objects.filter(planned_dates=today).values()

        if not manning_queryset.exists():
            return error_response(
                error=f"No Manning data found for {today}",
                status=status.HTTP_400_BAD_REQUEST,
            )

        manning_df = pd.DataFrame(list(manning_queryset))
        distinct_data = manning_queryset.values(
            "raw_oc_no", "raw_style", "raw_color", "line"
        ).distinct()

        columns_to_keep = [
            "raw_oc_no",
            "order_no",
            "buyer",
            "raw_style",
            "line",
            "raw_color",
            "section",
            "op_seq",
            "operation",
            "code",
        ]
        available_cols = [c for c in columns_to_keep if c in manning_df.columns]
        manning_df = manning_df[available_cols]
        manning_df.rename(
            columns={"raw_oc_no": "oc_no", "raw_style": "style", "raw_color": "color"},
            inplace=True,
        )

        allDFs = []
        for item in distinct_data:
            df = fetch_wip(
                poRef=item["raw_oc_no"],
                style=item["raw_style"],
                color=item["raw_color"],
                line=item["line"],
            )
            df["oc_no"] = item["raw_oc_no"]
            df["style"] = item["raw_style"]
            df["color"] = item["raw_color"]
            df["line"] = item["line"]
            allDFs.append(df)

        if not allDFs:
            return error_response(
                error="No WIP data fetched from OptaFloor API",
                status=status.HTTP_400_BAD_REQUEST,
            )

        allDFs = pd.concat(allDFs, ignore_index=True)

        columns_to_keep = [
            "oc_no",
            "style",
            "line",
            "color",
            "section",
            "operationName",
            "operationCode",
            "cumInputQty",
            "cumOutputQty",
            "wipQty",
        ]
        allDFs = allDFs[columns_to_keep]

        merged_df = manning_df.merge(
            allDFs[
                [
                    "oc_no",
                    "style",
                    "line",
                    "color",
                    "section",
                    "operationName",
                    "operationCode",
                    "wipQty",
                ]
            ],
            left_on=["oc_no", "style", "line", "color", "section", "operation", "code"],
            right_on=[
                "oc_no",
                "style",
                "line",
                "color",
                "section",
                "operationName",
                "operationCode",
            ],
            how="left",
        )

        if not viaAPI:
            logger.info(
                f"WIP data processed and uploaded successfully at {str(datetime.now())}"
            )

        return success_response(
            message="WIP data processed and uploaded successfully",
            status=status.HTTP_200_OK,
        )
    except Exception as e:
        logger.error(f"Error in run_fetch_wip_data: {str(e)}", exc_info=True)
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)


def run_uploading_planned_leaves(file):
    try:
        if not file:
            return error_response(
                error="File is required", status=status.HTTP_400_BAD_REQUEST
            )

        df = pd.read_excel(file)
        # Determine the correct column name for employee ID
        employee_id_col = (
            "Empployee ID" if "Empployee ID" in df.columns else "Employee ID"
        )

        # Keep only the required columns and drop rows with any NaN in these
        df_filtered = df[[employee_id_col, "From", "To"]].dropna(
            subset=[employee_id_col, "From", "To"]
        )

        # Expand leave date ranges
        def expand_date_ranges(row):
            start = pd.to_datetime(row["From"])
            end = pd.to_datetime(row["To"])
            date_range = pd.date_range(start, end)
            return [
                {employee_id_col: row[employee_id_col], "Date": date}
                for date in date_range
            ]

        # Apply the expansion
        expanded_rows = []
        for row in df_filtered.to_dict("records"):
            expanded_rows.extend(expand_date_ranges(row))

        # Create final DataFrame
        leaves_df = pd.DataFrame(expanded_rows)
        leaves_df.to_csv("csv_files/Planned_Leaves.csv", index=False)
        return success_response(
            message="File processed and data saved successfully",
            data="message",
            status=status.HTTP_200_OK,
        )
    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)


def run_upload_wip_data(file):

    if not file:
        return error_response(
            error="File is required", status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # Check the file type
        if file.name.endswith(".csv"):
            df_wip_data = pd.read_csv(file)
        elif file.name.endswith((".xls", ".xlsx")):
            df_wip_data = pd.read_excel(file)

        df_wip_data.fillna(
            {
                "op_seq": 0,
            },
            inplace=True,
        )

        df_wip_data.dropna(how="all", inplace=True)

        # Insert data in chunks
        records = [
            WIPData(
                oc_no=row["oc_no"],
                order_no=row["order_no"],
                buyer=row["buyer"],
                style=row["style"],
                line=row["line"],
                color=row["color"],
                section=row["section"],
                op_seq=row["op_seq"],
                operation=row["operation"],
                code=row["code"],
                wip_qty=row["wip_qty"],
            )
            for row in df_wip_data.to_dict("records")
        ]

        with transaction.atomic():
            # Delete old data before inserting new records
            truncate_table(WIPData)
            for i in range(0, len(records), CHUNK_SIZE):
                WIPData.objects.bulk_create(records[i : i + CHUNK_SIZE])

        return success_response(
            message="File processed and wip data saved successfully",
            status=status.HTTP_201_CREATED,
        )
    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)


def run_add_bulk_wip_data(data_list):
    """
    Adds multiple WIPData records in bulk.

    Parameters:
        data_list (list of dict): List of dictionaries where each dict represents a WIPData record.
    """
    try:
        data_list = [
            {
                "line": "Line 6",
                "section": "Back",
                "operationName": "Yoke Size Label Attach",
                "operationCode": "BA05",
                "cumInputQty": 5633,
                "cumOutputQty": 0,
                "wipQty": 5633,
            },
            {
                "line": "Line 6",
                "section": "Back",
                "operationName": "Yoke Centre Tacking",
                "operationCode": "BA51",
                "cumInputQty": 3204,
                "cumOutputQty": 2923,
                "wipQty": 281,
            },
            {
                "line": "Line 6",
                "section": "Back",
                "operationName": "Washcare Label attach",
                "operationCode": "BA40",
                "cumInputQty": 2862,
                "cumOutputQty": 2694,
                "wipQty": 168,
            },
            {
                "line": "Line 6",
                "section": "Back",
                "operationName": "Back-Endline QC",
                "operationCode": "BA64",
                "cumInputQty": 2694,
                "cumOutputQty": 2670,
                "wipQty": 24,
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "B/H Band & B/S",
                "operationCode": "CL15",
                "cumInputQty": 3599,
                "cumOutputQty": 3360,
                "wipQty": 239,
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Collar-Endline QC",
                "operationCode": "CL56",
                "cumInputQty": 3360,
                "cumOutputQty": 3013,
                "wipQty": 347,
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Collar Button Down Hole",
                "operationCode": "CL20",
                "cumInputQty": 3360,
                "cumOutputQty": 3360,
                "wipQty": 0,
            },
            {
                "line": "Line 6",
                "section": "Ticketing & Bundling",
                "operationName": "Bundling (FR, SL & BA)",
                "operationCode": "null",
                "cumInputQty": 0,
                "cumOutputQty": 0,
                "wipQty": 0,
            },
            {
                "line": "Line 6",
                "section": "Ticketing & Bundling",
                "operationName": "Bundling (CL & CU)",
                "operationCode": "null",
                "cumInputQty": 0,
                "cumOutputQty": 0,
                "wipQty": 0,
            },
            {
                "line": "Line 6",
                "section": "Sleeve",
                "operationName": "Sew Small Sleeve Placket",
                "operationCode": "SL01",
                "cumInputQty": 5633,
                "cumOutputQty": 2964,
                "wipQty": 2669,
            },
            {
                "line": "Line 6",
                "section": "Sleeve",
                "operationName": "Sleeve Tacking",
                "operationCode": "SL02",
                "cumInputQty": 2964,
                "cumOutputQty": 2754,
                "wipQty": 210,
            },
            {
                "line": "Line 6",
                "section": "Sleeve",
                "operationName": "Sleeve Box",
                "operationCode": "SL04",
                "cumInputQty": 2754,
                "cumOutputQty": 2412,
                "wipQty": 342,
            },
            {
                "line": "Line 6",
                "section": "Sleeve",
                "operationName": "Sleeve Pleet & Triming",
                "operationCode": "SL16",
                "cumInputQty": 2412,
                "cumOutputQty": 2342,
                "wipQty": 70,
            },
            {
                "line": "Line 6",
                "section": "Sleeve",
                "operationName": "Button Hole On Sleeve Placket",
                "operationCode": "SL07",
                "cumInputQty": 2342,
                "cumOutputQty": 2322,
                "wipQty": 20,
            },
            {
                "line": "Line 6",
                "section": "Sleeve",
                "operationName": "Button Stitch On Sleeve Placket",
                "operationCode": "SL08",
                "cumInputQty": 2322,
                "cumOutputQty": 2302,
                "wipQty": 20,
            },
            {
                "line": "Line 6",
                "section": "Sleeve",
                "operationName": "Sleeve-Endline QC",
                "operationCode": "SL33",
                "cumInputQty": 2302,
                "cumOutputQty": 2302,
                "wipQty": 0,
            },
            {
                "line": "Line 6",
                "section": "Matching",
                "operationName": "Matching.",
                "operationCode": "MT01",
                "cumInputQty": 2302,
                "cumOutputQty": 2302,
                "wipQty": 0,
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "Cuff Attach",
                "operationCode": "AS09",
                "cumInputQty": 1699,
                "cumOutputQty": 1629,
                "wipQty": 70,
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "Assembly-Endline QC",
                "operationCode": "AS82",
                "cumInputQty": 1508,
                "cumOutputQty": 1072,
                "wipQty": 436,
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "BUTTON DOWN",
                "operationCode": "AS20",
                "cumInputQty": 1509,
                "cumOutputQty": 1508,
                "wipQty": 1,
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "Hanger Loading",
                "operationCode": "HE",
                "cumInputQty": 2302,
                "cumOutputQty": 1980,
                "wipQty": 322,
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "Join Sholuder",
                "operationCode": "AS01",
                "cumInputQty": 1980,
                "cumOutputQty": 1850,
                "wipQty": 130,
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "Collar Attach",
                "operationCode": "AS03",
                "cumInputQty": 1850,
                "cumOutputQty": 1840,
                "wipQty": 10,
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "Collar Finish",
                "operationCode": "AS04",
                "cumInputQty": 1840,
                "cumOutputQty": 1840,
                "wipQty": 0,
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "Sleeve Attach",
                "operationCode": "AS05",
                "cumInputQty": 1840,
                "cumOutputQty": 1835,
                "wipQty": 5,
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "Sleeve Top",
                "operationCode": "AS06",
                "cumInputQty": 1835,
                "cumOutputQty": 1699,
                "wipQty": 136,
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "French Fell -1",
                "operationCode": "AS59",
                "cumInputQty": 1699,
                "cumOutputQty": 1699,
                "wipQty": 0,
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "French Fell 2",
                "operationCode": "AS17",
                "cumInputQty": 1699,
                "cumOutputQty": 1699,
                "wipQty": 0,
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "Bottom Hem",
                "operationCode": "AS14",
                "cumInputQty": 1629,
                "cumOutputQty": 1509,
                "wipQty": 120,
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "PRL EXTRA BUTTON",
                "operationCode": "AS64",
                "cumInputQty": 1508,
                "cumOutputQty": 1508,
                "wipQty": 0,
            },
            {
                "line": "Line 6",
                "section": "Finishing",
                "operationName": "Qualiy Control",
                "operationCode": "FN05",
                "cumInputQty": 0,
                "cumOutputQty": 0,
                "wipQty": 0,
            },
            {
                "line": "Line 6",
                "section": "Finishing",
                "operationName": "Packaging",
                "operationCode": "FN02",
                "cumInputQty": 0,
                "cumOutputQty": 0,
                "wipQty": 0,
            },
            {
                "line": "Line 6",
                "section": "Finishing",
                "operationName": "Carton Auditing",
                "operationCode": "FN06",
                "cumInputQty": 0,
                "cumOutputQty": 0,
                "wipQty": 0,
            },
            {
                "line": "Line 6",
                "section": "Finishing",
                "operationName": "Trim & Exam",
                "operationCode": "FN01",
                "cumInputQty": 0,
                "cumOutputQty": 0,
                "wipQty": 0,
            },
            {
                "line": "Line 6",
                "section": "Finishing",
                "operationName": "Folding",
                "operationCode": "FN04",
                "cumInputQty": 0,
                "cumOutputQty": 0,
                "wipQty": 0,
            },
            {
                "line": "Line 6",
                "section": "CSO",
                "operationName": "CSO Audit",
                "operationCode": "CSO",
                "cumInputQty": 5633,
                "cumOutputQty": 0,
                "wipQty": 5633,
            },
            {
                "line": "Line 6",
                "section": "Cuff",
                "operationName": "Cuff Lining Attach",
                "operationCode": "CU26",
                "cumInputQty": 5633,
                "cumOutputQty": 5058,
                "wipQty": 575,
            },
            {
                "line": "Line 6",
                "section": "Front",
                "operationName": "Front Button Hole",
                "operationCode": "FR14",
                "cumInputQty": 3009,
                "cumOutputQty": 2759,
                "wipQty": 250,
            },
            {
                "line": "Line 6",
                "section": "Front",
                "operationName": "Pairing",
                "operationCode": "FR24",
                "cumInputQty": 2759,
                "cumOutputQty": 2750,
                "wipQty": 9,
            },
            {
                "line": "Line 6",
                "section": "Front",
                "operationName": "Front-Endline QC",
                "operationCode": "FR75",
                "cumInputQty": 2750,
                "cumOutputQty": 2449,
                "wipQty": 301,
            },
            {
                "line": "Line 6",
                "section": "Front",
                "operationName": "Front Button Sew",
                "operationCode": "FR15",
                "cumInputQty": 3390,
                "cumOutputQty": 3165,
                "wipQty": 225,
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Neckband Fusing Attach",
                "operationCode": "CL55",
                "cumInputQty": 5633,
                "cumOutputQty": 5428,
                "wipQty": 205,
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Collar Run - Non Fusible",
                "operationCode": "CL41",
                "cumInputQty": 5633,
                "cumOutputQty": 4529,
                "wipQty": 1104,
            },
            {
                "line": "Line 6",
                "section": "Cuff",
                "operationName": "Cuff Hem",
                "operationCode": "CU13",
                "cumInputQty": 5058,
                "cumOutputQty": 4556,
                "wipQty": 502,
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Neck Band Hem",
                "operationCode": "CL08",
                "cumInputQty": 5428,
                "cumOutputQty": 4298,
                "wipQty": 1130,
            },
            {
                "line": "Line 6",
                "section": "Cuff",
                "operationName": "Run Cuff-Round Shape",
                "operationCode": "CU02",
                "cumInputQty": 4556,
                "cumOutputQty": 3982,
                "wipQty": 574,
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Top Stich Collar",
                "operationCode": "CL05",
                "cumInputQty": 4529,
                "cumOutputQty": 4285,
                "wipQty": 244,
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Collar Stay Stitch",
                "operationCode": "CL07",
                "cumInputQty": 4285,
                "cumOutputQty": 4091,
                "wipQty": 194,
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Neckband Attach",
                "operationCode": "CL37",
                "cumInputQty": 4091,
                "cumOutputQty": 3967,
                "wipQty": 124,
            },
            {
                "line": "Line 6",
                "section": "Cuff",
                "operationName": "Top Stitch Cuff",
                "operationCode": "CU07",
                "cumInputQty": 3982,
                "cumOutputQty": 3746,
                "wipQty": 236,
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Pick Attach",
                "operationCode": "CL66",
                "cumInputQty": 3967,
                "cumOutputQty": 3915,
                "wipQty": 52,
            },
            {
                "line": "Line 6",
                "section": "Front",
                "operationName": "Front placket attach (cut and sew)",
                "operationCode": "FR65",
                "cumInputQty": 5633,
                "cumOutputQty": 3009,
                "wipQty": 2624,
            },
            {
                "line": "Line 6",
                "section": "Cuff",
                "operationName": "Cuff Button Hole (2 Hole In Shirt)",
                "operationCode": "PCU03",
                "cumInputQty": 3746,
                "cumOutputQty": 3708,
                "wipQty": 38,
            },
            {
                "line": "Line 6",
                "section": "Back",
                "operationName": "CENTRE PLEAT",
                "operationCode": "BA45",
                "cumInputQty": 5633,
                "cumOutputQty": 3204,
                "wipQty": 2429,
            },
            {
                "line": "Line 6",
                "section": "Front",
                "operationName": "Button Placket Hem",
                "operationCode": "FR06",
                "cumInputQty": 5633,
                "cumOutputQty": 3390,
                "wipQty": 2243,
            },
            {
                "line": "Line 6",
                "section": "Back",
                "operationName": "SPLIT YOKE ATTACH DOUBLE",
                "operationCode": "BA50",
                "cumInputQty": 5633,
                "cumOutputQty": 3258,
                "wipQty": 2375,
            },
            {
                "line": "Line 6",
                "section": "Cuff",
                "operationName": "Cuff Button Sew( 2 In Shirt)",
                "operationCode": "CU09",
                "cumInputQty": 3708,
                "cumOutputQty": 3708,
                "wipQty": 0,
            },
            {
                "line": "Line 6",
                "section": "Cuff",
                "operationName": "Cuff-Endline QC",
                "operationCode": "CU43",
                "cumInputQty": 3708,
                "cumOutputQty": 3306,
                "wipQty": 402,
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Top Stich on NB",
                "operationCode": "CL11",
                "cumInputQty": 3915,
                "cumOutputQty": 3599,
                "wipQty": 316,
            },
            {
                "line": "Line 6",
                "section": "Back",
                "operationName": "Main Label (Four Side)",
                "operationCode": "BA17",
                "cumInputQty": 3258,
                "cumOutputQty": 3066,
                "wipQty": 192,
            },
            {
                "line": "Line 6",
                "section": "Back",
                "operationName": "Premium Label Attach",
                "operationCode": "BA04",
                "cumInputQty": 3066,
                "cumOutputQty": 3005,
                "wipQty": 61,
            },
            {
                "line": "Line 6",
                "section": "Back",
                "operationName": "YOKE ATTACH (PLEAT/ SPLIT DOUBLE)",
                "operationCode": "BA48",
                "cumInputQty": 2923,
                "cumOutputQty": 2862,
                "wipQty": 61,
            },
        ]
        wip_instances = []

        for item in data_list:
            if item["operationCode"] == "null":
                pass
            else:
                wip = WIPData(
                    oc_no="prls/24/13608",
                    order_no="tbc",
                    buyer="POLO RALPH LAUREN - BSR GD OXFORD",
                    style="710729232004 - BDPPCSPT",
                    line="Line 6",
                    color="BASTILLEBLUE",
                    section=item.get("section", ""),  # Fetch from datalist
                    op_seq=item.get("op_seq", 0),
                    operation=item.get("operationName", ""),
                    code=item.get("operationCode", ""),
                    wip_qty=item.get("wipQty", 0.0),
                )
                wip_instances.append(wip)

        with transaction.atomic():
            truncate_table(WIPData)
            WIPData.objects.bulk_create(wip_instances, batch_size=1000)

        logger.info(f"Inserted {len(wip_instances)} records into WIPData.")
        return success_response(
            message=f"Inserted {len(wip_instances)} records into WIPData.",
            data="message",
            status=status.HTTP_200_OK,
        )
    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)


def insert_consolidated_df(consolidated_df):
    consolidated_df["STYLE"] = consolidated_df["STYLE"].str.lower()

    # Fill nulls
    consolidated_df["SAM"].fillna(0, inplace=True)
    consolidated_df["ALLOCATED EMP ID"].fillna(0, inplace=True)

    consolidated_df["MACHINE_TYPE"] = (
        consolidated_df["MACHINE_TYPE"]
        .astype(str)  # convert everything to string
        .str.strip()  # remove leading/trailing whitespace
        .replace(
            ["", "nan", "NaN", "None"], np.nan
        )  # replace string empty cases with actual NaN
        .fillna("Not Applicable")  # now fill all NaN
    )

    # consolidated_df.drop_duplicates(inplace=True, ignore_index=True) # Removing the duplicate rows

    def row_to_dict(row):
        return {
            "oc_no": row["OC_NO"],
            "order_no": row["ORDER_NO"],
            "buyer": row["BUYER"],
            "style": row["STYLE"],
            "line": row["LINE"],
            "week": row["WEEK"],
            "planned_dates": row["PLANNED_DATES"],
            "planned_qty": row["PLANNED_QTY"],
            "factory": row["FACTORY"],
            "floor": row["FLOOR"],
            "workdays": row["WORKDAYS"],
            "section": row["SECTION"],
            "op_seq": row["OP_SEQ"],
            "operation": row["OPERATION"],
            "code": row["CODE"],
            "sam": row["SAM"],
            "allocated_emp_id": int(row["ALLOCATED EMP ID"]),
            "allocated_emp_name": row["ALLOCATED EMP NAME"],
            "allocated_capacity": row["ALLOCATED CAPACITY"],
            "allocated_frm_line": row["ALLOCATED_FRM_LINE"],
            "allocated_frm_factory": row["ALLOCATED_FRM_FACTORY"],
            "allocated_frm_floor": row["ALLOCATED_FRM_FLOOR"],
            "skill_type": row["SKILL_TYPE"],
            "machine": row["MACHINE_EMP_FACT"],
            "shortage_flag": row["SHORTAGE_FLAG"],
            "shortage_reason": row["SHORTAGE_REASON"],
            "designation": row["DESIGNATION"],
            "target_100": row["TARGET@100%"],
            "target_90": row["TARGET@90%"],
            "split_order_id": row["SPLIT_ORDER_ID"],
            "forecast_period": row["PERIOD"],
            "machinist": row["MACHINIST"],
            "machine_type": row["MACHINE_TYPE"],
            "color": row["COLOR"],
            "raw_oc_no": row["RAW_OC_NO"],
            "raw_style": row["RAW_STYLE"],
            "raw_color": row["RAW_FABRIC_ARTICLE"],
        }

    def insert_chunk(chunk_dicts):
        instances = [ManningSheetData(**d) for d in chunk_dicts]
        with transaction.atomic():
            ManningSheetData.objects.bulk_create(instances, batch_size=1000)

    # Step 1: Convert DataFrame rows to list of dicts (sequentially to preserve row order)
    data_dicts = [row_to_dict(row) for row in consolidated_df.to_dict("records")]

    # Step 2: Split into chunks for memory efficiency
    CHUNK_SIZE = 500  # define this globally or change as needed
    chunked_data = [
        data_dicts[i : i + CHUNK_SIZE] for i in range(0, len(data_dicts), CHUNK_SIZE)
    ]

    # Step 3: Insert each chunk sequentially to preserve order
    logger.info(
        f"Inserting {len(data_dicts)} records in {len(chunked_data)} chunks sequentially..."
    )
    for chunk in chunked_data:
        insert_chunk(chunk)


def insert_all_unallocated_employees(all_unallocated_employees, df_active_employees):
    # Ensure 'DATE' is a datetime and format to 'YYYY-MM-DD'
    all_unallocated_employees["DATE"] = pd.to_datetime(
        all_unallocated_employees["DATE"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")

    merged_df = all_unallocated_employees.merge(
        df_active_employees[["Emp No", "Designation"]],
        left_on="EMPLOYEE ID",
        right_on="Emp No",
        how="left",
    )
    merged_df.drop(columns=["Emp No"], inplace=True)

    # Convert to dicts (parallelized)
    def row_to_dict(row):
        return {
            "date": row["DATE"],
            "employee_id": row["EMPLOYEE ID"],
            "employee_name": row["EMPLOYEE NAME"],
            "line": row["LINE"],
            "section": row["SECTION"],
            "code": row["CODE"],
            "type": row["TYPE"],
            "initial_capacity": row["INITIAL CAPACITY"],
            "remaining_capacity": row["REMAINING CAPACITY"],
            "utilization_pct": row["UTILIZATION_PCT"],
            "reason": row["REASON"],
            "category": row["CATEGORY"],
            "period": row["PERIOD"],
            "designation": row["Designation"],
        }

    # Use ThreadPoolExecutor to convert rows to dicts
    with ThreadPoolExecutor(max_workers=10) as executor:
        data_dicts = list(
            executor.map(row_to_dict, [row for row in merged_df.to_dict("records")])
        )

    # Transform unallocated employees to on hold
    transform_unallocated_to_on_hold_from_dict(data_dicts)

    # Chunked insert to DB using threads
    def insert_chunk(chunk_dicts):
        instances = [UnallocatedEmployees(**d) for d in chunk_dicts]
        with transaction.atomic():
            UnallocatedEmployees.objects.bulk_create(instances, batch_size=1000)

    chunked_data = [
        data_dicts[i : i + CHUNK_SIZE] for i in range(0, len(data_dicts), CHUNK_SIZE)
    ]

    logger.info(
        f"Inserting {len(data_dicts)} unallocated records in {len(chunked_data)} chunks..."
    )
    with ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(insert_chunk, chunked_data)


def run_upload_active_employees(file):
    try:
        if not file:
            return error_response(
                error="No file uploaded", status=status.HTTP_400_BAD_REQUEST
            )

        df = pd.read_csv(file)

        # Check if it's the frontend template format
        if "employee_id" in df.columns and "employee_name" in df.columns:
            if df.empty:
                return error_response(
                    error="The uploaded template contains no employee rows.",
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if "machinist" in df.columns:
                df["machinist"] = (
                    df["machinist"]
                    .astype(str)
                    .str.lower()
                    .map({"true": True, "false": False, "1": True, "0": False})
                    .fillna(False)
                )

            # Extract only digits from employee IDs (e.g. EMP001 -> 1)
            df["employee_id"] = (
                df["employee_id"].astype(str).str.replace(r"\D", "", regex=True)
            )
            df["employee_id"] = pd.to_numeric(df["employee_id"], errors="coerce")
            df.dropna(subset=["employee_id"], inplace=True)
            if df.empty:
                return error_response(
                    error="All employee IDs were invalid or missing. Please ensure Employee IDs contain numbers.",
                    status=status.HTTP_400_BAD_REQUEST,
                )

            df.fillna("", inplace=True)

            data_dicts = []
            for row in df.to_dict("records"):
                data_dict = {
                    "employee_id": str(int(row["employee_id"])),
                    "employee_name": str(row.get("employee_name", "")),
                    "line": str(row.get("line", "")),
                    "section": str(row.get("section", "")),
                    "designation": str(row.get("designation", "")),
                    "machinist": bool(row.get("machinist", False)),
                    "service_years": row.get("service_years", 0.0),
                    "status": str(row.get("status", "active")),
                    "gender": str(row.get("gender", "Male")),
                }
                data_dicts.append(data_dict)

        # Fallback to the legacy Active_Employees.csv format
        elif "Emp No" in df.columns and "Employee name" in df.columns:
            if df.empty:
                return error_response(
                    error="The uploaded CSV contains no employee rows.",
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if "Department" in df.columns:
                df["Department"] = df["Department"].fillna("").astype(str)
                df[["Line", "Section"]] = df["Department"].str.extract(
                    r"(?i)^(line \d+)\s*(.*)$", expand=True
                )
                df["Line"] = df["Line"].str.upper()
            else:
                df["Line"] = ""
                df["Section"] = ""

            # Extract only digits from legacy Emp No
            df["Emp No"] = df["Emp No"].astype(str).str.replace(r"\D", "", regex=True)
            df["Emp No"] = pd.to_numeric(df["Emp No"], errors="coerce")
            df.dropna(subset=["Emp No"], inplace=True)
            if df.empty:
                return error_response(
                    error="All employee IDs were invalid or missing. Please ensure Employee IDs contain numbers.",
                    status=status.HTTP_400_BAD_REQUEST,
                )

            data_dicts = []
            for row in df.to_dict("records"):
                data_dict = {
                    "employee_id": str(int(row["Emp No"])),
                    "employee_name": row.get("Employee name", ""),
                    "line": row.get("Line", ""),
                    "section": row.get("Section", ""),
                    "designation": row.get("Designation", ""),
                    "machinist": str(row.get("Designation", "")).lower() == "machinist",
                    "service_years": 0.0,
                    "status": "active",
                    "gender": "Male",
                }
                data_dicts.append(data_dict)
        else:
            return error_response(
                error="Missing required columns in CSV. Make sure you use the template format.",
                status=status.HTTP_400_BAD_REQUEST,
            )

        truncate_table(ActiveEmployees)

        for i in range(0, len(data_dicts), CHUNK_SIZE):
            chunk_dicts = data_dicts[i : i + CHUNK_SIZE]
            model_instances = [ActiveEmployees(**d) for d in chunk_dicts]
            with transaction.atomic():
                ActiveEmployees.objects.bulk_create(model_instances, batch_size=1000)

        # Automatically generate the Employee Master table so the UI updates immediately
        try:
            from apps.data_engine.services.employee_service import (
                run_generate_employee_master,
            )

            result = run_generate_employee_master()
            import os

            with open(
                os.path.join(os.path.dirname(__file__), "test_debug.txt"), "w"
            ) as f:
                f.write(f"data_dicts len: {len(data_dicts)}\n")
                f.write(f"DB count: {ActiveEmployees.objects.count()}\n")
                if hasattr(result, "data"):
                    f.write(str(result.data))
                else:
                    f.write(str(result))
        except Exception as e:
            import os

            with open(
                os.path.join(os.path.dirname(__file__), "test_debug.txt"), "w"
            ) as f:
                f.write(f"Exception: {e}")
            logger.error(f"Failed to generate Employee Master after upload: {e}")

        return success_response(
            message="Active Employees data uploaded successfully",
            status=status.HTTP_200_OK,
        )

    except Exception as e:
        return error_response(
            error=f"Failed to process Active Employees upload: {str(e)}",
            status=status.HTTP_400_BAD_REQUEST,
        )
