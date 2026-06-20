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
from django.db.models import Func, FloatField, Count, Sum, Count, Case, When, Q

from io import BytesIO
from rest_framework import status
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, date, time
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes, authentication_classes

from apps.accounts.authentication import MultiSessionTokenAuthentication
from apps.accounts.utils.response_handlers import error_response, success_response

from backend_laguna.utils import truncate_table
from .loading_plan_optimization import process_df
from .loading_plan import redistribute_production_plan
from apps.absenteeism.utils import send_email, is_allowed_working_day, convert_number
from .manning_generation_multiprocessing_v5 import run_manning_allocation, filter_by_date_ranges, process_grouped_results, map_factory_floor_for_results, create_manning_dataframes, process_general_info, map_factory_floor
from .dday_generation_v3 import get_ist_time, run_intraday_allocation_enhanced, generate_reallocation_report, analyze_unallocated_patterns, print_unallocated_summary, generate_unallocated_report_safe, analyze_allocation_gaps, perform_final_allocation_pass
from .utils import fetch_skill_matrix, fetch_operations, merge_dataframe, export_to_excel, export_json_to_excel, fetch_style_ob, merge_machine_sam, process_styles, renaming_columns_style_ob, fetch_wip, custom_round, create_bulk_push_notifications, get_notification_type_by_time, fetch_dday_data, fetch_attendance_data, remove_by_employee_id, transform_unallocated_to_on_hold_from_dict, update_sections, remove_duplicate_employee_dicts, fetchMaxQtyDday

from .models import PushNotification
from apps.accounts.models import EndpointLock, User
from apps.absenteeism.models import PredictionData, AbsenteeismPrediction
from apps.dataEngine.models import AttendanceMaster, EmployeeMaster, LocalHolidayCalendar, PayableWorkingDays
from .models import StyleOB, LoadingPlan, EMPFact, ManningSheetData, DDayData, ManningGeneralInfo, WIPData, ActiveEmployees, UnallocatedEmployees, EmployeesOnHold

logger = logging.getLogger('general')

CHUNK_SIZE = 1000

# LIST_OF_EMAILS = os.getenv('LIST_OF_EMAILS')

# Create folder if it doesn't exist
os.makedirs("exports", exist_ok=True)


# Company code for Kanakpura Factory (RockHR)
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

# Custom rounding function
class Round(Func):
    function = 'ROUND'
    arity = 2
    output_field = FloatField()



@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def styleob_file_upload(request):
    if request.method == 'POST':
        file = request.FILES.get('file')
        if not file:
            return error_response(error='File is required', status=status.HTTP_400_BAD_REQUEST)
        
        try:            
            df_Style_OB = pd.read_excel(file)
            df_Style_OB.dropna(subset=['code'], inplace=True)
            df_Style_OB = df_Style_OB.drop(columns=['color'], errors='ignore') # Removed color column
            df_Style_OB['code'] = df_Style_OB['code'].str.replace(r'\s+', ' ', regex=True).str.strip()
            df_Style_OB['code'] = df_Style_OB['code'].str.replace(' ', '', regex=True)
            df_Style_OB = df_Style_OB[df_Style_OB['department'] == 'Sewing']

            ######new lines######################
            df_Style_OB['style'] = df_Style_OB['style'].str.lower().str.strip()
            df_Style_OB['style'] = df_Style_OB['style'].str.replace(r'\s+', ' ', regex=True).str.strip()
            df_Style_OB['style'] = df_Style_OB['style'].str.replace(' ', '', regex=True)
            # df_Style_OB['color'] = df_Style_OB['color'].str.lower().str.strip()
            # df_Style_OB['color'] = df_Style_OB['color'].str.replace(r'\s+', ' ', regex=True).str.strip()
            # df_Style_OB['color'] = df_Style_OB['color'].str.replace(' ', '', regex=True)

            df_Style_OB = df_Style_OB.drop(columns=['created_at', 'department', 'type', 'po_ref'])
            df_Style_OB = df_Style_OB.drop_duplicates(subset=['style', 'section', 'code'], keep='first') # Removed color and op_seq
            df_Style_OB.dropna(subset = ["style","section","op_seq","operation","code"]) # Removed color

            #arrange in ascending order by op_seq
            df_Style_OB = df_Style_OB.sort_values(by=['style', 'section','op_seq']).groupby(['style', 'section'], as_index=False).apply(lambda x: x.sort_values(by=['op_seq'], ascending=True)).reset_index(drop=True)
            
            # Delete all old entries before inserting new data
            StyleOB.objects.all().delete()
            
            records = [
                StyleOB(
                    style=row['style'],
                    section=row['section'],
                    op_seq=int(row['op_seq']),
                    operation=row['operation'],
                    code=row['code'],
                    sam=float(row['sam']),
                    color="BLACK",
                    machine_type=row['machine_type'],
                    machinist=row['machinist']
                ) for _, row in df_Style_OB.iterrows()
            ]
            
            # Delete all old entries before inserting new data
            truncate_table(StyleOB)
            
            # Insert data in chunks
            for i in range(0, len(records), CHUNK_SIZE):
                StyleOB.objects.bulk_create(records[i:i+CHUNK_SIZE])

            return success_response(message= 'File processed and data saved successfully', status=status.HTTP_201_CREATED)
        except Exception as e:
            return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)
    
    return error_response(error= 'Invalid request', status=status.HTTP_400_BAD_REQUEST)



# Function to fetch and process the loading plan data
@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def loading_plan_file_upload(request):
    if request.method == 'POST':
        file = request.FILES.get('file')
    
        if not file:
            return error_response(error='File is required', status=status.HTTP_400_BAD_REQUEST)
        
        try:
            df_load_plan = pd.read_excel(file, sheet_name=None)

            # Get last date of current year
            last_date_of_year = date(datetime.today().year, 12, 31)

            # Load the LocalHolidayCalendar data from the database
            queryset_local_holiday_calender = LocalHolidayCalendar.objects.all().values()
            local_holiday_calender_df = pd.DataFrame.from_records(queryset_local_holiday_calender)
            local_holiday_calender_df['date'] = pd.to_datetime(local_holiday_calender_df['date']).dt.date
            holiday_dates = set(local_holiday_calender_df['date'])


            # Get all payable working days from the database for the date range
            payable_dates = PayableWorkingDays.objects.all().values()
            payable_dates_df = pd.DataFrame.from_records(payable_dates)
            payable_dates_df['date'] = pd.to_datetime(payable_dates_df['date']).dt.date
            payable_dates = set(payable_dates_df['date'])

            sheet_names_to_extract = [sheet for sheet in df_load_plan if sheet.startswith('KPR')]
            sheets_dict = {sheet: df_load_plan[sheet] for sheet in sheet_names_to_extract}

            df_load_plan_all = []
            # final_df_all = [] # Commenting as not needed as of now

            for sheet_name, df in sheets_dict.items():
                logger.info(f"\nProcessing sheet: {sheet_name}")
                df['sheet_name'] = sheet_name
                df_load_plan, final_df_new = process_df(df, holiday_dates, last_date_of_year, payable_dates)
                # Collect for later concatenation
                df_load_plan_all.append(df_load_plan)
                # final_df_all.append(final_df_new) # Commenting as not needed as of now

            # Concatenate after loop
            df_load_plan_combined = pd.concat(df_load_plan_all, ignore_index=True)
            # final_df_combined = pd.concat(final_df_all, ignore_index=True) # Commenting as not needed as of now


            # Insert data in chunks
            records = [
                LoadingPlan(
                    oc_no=row['OC NO'], order_no=row['ORDER NO'], cfm_date=row['CFM DATE'] if pd.notna(row['CFM DATE']) else None, merchant=row['MERCHANT'],
                    style=row['STYLE'], buyer=row['BUYER'], ls_ss=row['L/S-S/S'], fabric_article=row['FABRIC ARTICLE'],
                    smv=row['SMV'], del_date=row['DEL DATE'] if pd.notna(row['DEL DATE']) else None, month_code=row['MONTH CODE'], qty_order=row['QTY ORDER'],
                    sheet_name=row['sheet_name'], line=row['Line'], week=row['Week'], planned_qty=row['Planned Qty'],
                    date_start=row['Date_Start'] if pd.notna(row['Date_Start']) else None, date_end=row['Date_End'] if pd.notna(row['Date_End']) else None,
                    planned_dates=row['Planned_Dates'] if pd.notna(row['Planned_Dates']) else None,
                    raw_oc_no=row['raw_oc_no'],
                    raw_style=row['raw_style'],
                    raw_fabric_article=row['raw_fabric_article']
                ) for _, row in df_load_plan_combined.iterrows()
            ]

            with transaction.atomic():
                # Delete old data before inserting new records
                truncate_table(LoadingPlan)

                for i in range(0, len(records), CHUNK_SIZE):
                    LoadingPlan.objects.bulk_create(records[i:i+CHUNK_SIZE])

            run_generate_style_ob(viaAPI=False)
            
            return success_response(message= 'File processed and data saved successfully', status=status.HTTP_201_CREATED)
        except Exception as e:
            return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)
    return error_response(error= 'Invalid request', status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def loading_plan_file_upload_old(request):
    if request.method == 'POST':
        file = request.FILES.get('file')

        if not file:
            return error_response(error='File is required', status=status.HTTP_400_BAD_REQUEST)
        
        try:
            df_load_plan = pd.read_excel(file, sheet_name=None)

            # Load the LocalHolidayCalendar data from the database
            queryset_local_holiday_calender = LocalHolidayCalendar.objects.all().values()
            local_holiday_calender_df = pd.DataFrame.from_records(queryset_local_holiday_calender)
            local_holiday_calender_df['date'] = pd.to_datetime(local_holiday_calender_df['date']).dt.date
            holiday_dates = set(local_holiday_calender_df['date'])

            sheet_names_to_extract = [sheet for sheet in df_load_plan if sheet.startswith('KPR')]
            sheets_dict = {sheet: df_load_plan[sheet] for sheet in sheet_names_to_extract}

            
            #Combine all selected sheets into a single DataFrame and add a sheet name column
            df_load_plan = pd.concat(
                [df.assign(sheet_name=sheet) for sheet, df in sheets_dict.items()],
                ignore_index=True
            )

            #Save the 'sheet_name' column separately before modifying headers
            sheet_name_column = df_load_plan['sheet_name'].copy()

            #Remove the first 5 rows (assuming header is on row 6)
            df_load_plan = df_load_plan.iloc[5:].reset_index(drop=True)

            # Step 9: Set the first row as the new column headers
            df_load_plan.columns = df_load_plan.iloc[0]  # Use the first row as header
            df_load_plan = df_load_plan.iloc[1:].reset_index(drop=True)  # Drop the first row after setting headers

            #Reattach the 'sheet_name' column correctly aligned
            df_load_plan['sheet_name'] = sheet_name_column.iloc[5:].reset_index(drop=True)  # Ensures proper alignment

            # Drop unnamed or unnecessary columns (like 'KPR L1' and 'NaN' columns)
            # columns_to_drop = [col for col in df_load_plan.columns if 'KPR L' in str(col) or str(col) == 'NaN']
            # df_load_plan = df_load_plan.drop(columns=columns_to_drop, errors='ignore')

            df_load_plan.dropna(how='all', inplace=True)
            df_load_plan = df_load_plan.iloc[2:].reset_index(drop=True)
            df_load_plan = df_load_plan.drop(
                columns=[col for col in df_load_plan.columns if 'KPR L' in str(col) or str(col) == 'NaN' or col in ["Unnamed", "FABRIC", "FABRIC TYPE","REMARKS","IN HOUSE","NEW INH HOUSE","APPROVAL OF FIT/PP","Release of Production file & approved sample","Revised F/R","LC received","TRIMS AVAILABILITY","BAL TO LOAD"]],
                errors='ignore'
            )
            df_load_plan = df_load_plan.drop(columns=[col for col in df_load_plan.columns if str(col).strip().lower() == 'nan'], errors='ignore')
            df_load_plan = df_load_plan.dropna(axis=1, how='all') #44444444444444
            df_load_plan = df_load_plan[df_load_plan.drop(columns=['sheet_name'], errors='ignore').notna().any(axis=1)]

            df_load_plan = df_load_plan[df_load_plan['OC NO'].notna()]
            df_load_plan['OC NO'] = df_load_plan['OC NO'].astype(str).str.strip()
            unwanted_patterns = ['KANAKPURA', 'LINE', 'DATE', 'OC']
            df_load_plan = df_load_plan[~df_load_plan['OC NO'].str.contains('|'.join(unwanted_patterns), case=False, na=False)]
            #df_load_plan['Line'] = df_load_plan['sheet_name'].str.extract(r'(\d+)$').astype(float).astype('Int64')
            df_load_plan['Line'] = df_load_plan['sheet_name'].str.strip().str.extract(r'(\d+)$').astype(float).astype('Int64')
            df_load_plan['Line'] = 'Line ' + df_load_plan['Line'].astype(str)

            #Identify columns that start with 'wk'
            wk_columns = [col for col in df_load_plan.columns if isinstance(col, str) and col.startswith('wk')]

            #Replace 'FAB', 'DEL', NaN, and empty strings in 'wk%' columns with 0
            df_load_plan[wk_columns] = df_load_plan[wk_columns].replace(['FAB', 'DEL', np.nan, ''], 0)

            ############################################################################################################

            #Convert 'wk%' columns to integers
            #df_load_plan[wk_columns] = df_load_plan[wk_columns].apply(pd.to_numeric, errors='coerce').fillna(0).astype(int)

            #Drop rows where all 'wk%' columns contain only 0
            #df_load_plan = df_load_plan[~(df_load_plan[wk_columns] == 0).all(axis=1)]

            # Melt the dataframe to transform 'wk' columns into rows
            df_load_plan = df_load_plan.melt(
                id_vars=[col for col in df_load_plan.columns if col not in wk_columns],
                value_vars=wk_columns,
                var_name='Week',
                value_name='Planned Qty'
            )

            #Extract the Week Number as an integer
            df_load_plan['Week'] = df_load_plan['Week'].str.extract(r'wk (\d+)')[0].astype(int)

            #Create a mapping of Week Number to Date Range from the column names
            week_date_mapping = {
                int(col.split()[1]): col.split(' ', 2)[-1] for col in wk_columns if col.startswith('wk')
            }

            #Map the extracted week number to its corresponding date range
            df_load_plan['Dates'] = df_load_plan['Week'].map(week_date_mapping)

            #Remove rows where 'Planned Qty' is 0 or NaN
            df_load_plan = df_load_plan[df_load_plan['Planned Qty'] > 0]

            ###########################################################################################################

            # Convert 'CFM DATE' to datetime

            df_load_plan['CFM DATE'] = pd.to_datetime(df_load_plan['CFM DATE'], errors='coerce')

            # Replace 'DEL DATE' with 'NEW DEL' where 'NEW DEL' has a valid date
            df_load_plan['DEL DATE'] = df_load_plan['NEW DEL'].combine_first(df_load_plan['DEL DATE'])

            # Drop the 'NEW DEL' column
            df_load_plan.drop(columns=['NEW DEL'], inplace=True)

            # Get the current year
            current_year = datetime.now().year

            # Split the Dates column by '-'
            df_load_plan[['Date_Start', 'Date_End']] = df_load_plan['Dates'].str.split('-', expand=True)

            # Trim whitespace
            df_load_plan['Date_Start'] = df_load_plan['Date_Start'].str.strip()
            df_load_plan['Date_End'] = df_load_plan['Date_End'].str.strip()

            # Append the current year and format as dd/mm/yy
            df_load_plan['Date_Start'] = df_load_plan['Date_Start'] + f'/{current_year}'
            df_load_plan['Date_End'] = df_load_plan['Date_End'] + f'/{current_year}'

            # Convert to datetime format and reformat as string dd/mm/yy
            df_load_plan['Date_Start'] = pd.to_datetime(df_load_plan['Date_Start'], format='%d/%m/%Y').dt.strftime('%d/%m/%y')
            df_load_plan['Date_End'] = pd.to_datetime(df_load_plan['Date_End'], format='%d/%m/%Y').dt.strftime('%d/%m/%y')

            # Drop the original Dates column
            df_load_plan.drop(columns=['Dates'], inplace=True)

            ##############################################################################################################

            sl_columns = ['OC NO', 'ORDER NO', 'STYLE','FABRIC ARTICLE']

            #####################New lines#############
            for col in sl_columns:
                if col in df_load_plan.columns:
                    df_load_plan[col] = df_load_plan[col].astype(str).str.strip()
                    df_load_plan[col] = df_load_plan[col].str.replace(r'\s+', ' ', regex=True)
                    df_load_plan[col] = df_load_plan[col].str.replace(' ', '', regex=True)
                    df_load_plan[col] = df_load_plan[col].str.lower()

            # Convert Date_Start and Date_End to datetime format
            df_load_plan['Date_Start'] = pd.to_datetime(df_load_plan['Date_Start'], format='%d/%m/%y', errors='coerce')
            df_load_plan['Date_End'] = pd.to_datetime(df_load_plan['Date_End'], format='%d/%m/%y', errors='coerce')

            # Create an empty list to store expanded data
            expanded_rows = []


            def is_included_saturday(date):
                if date.weekday() == 5:  # 5 = Saturday
                    first_saturday = (date.replace(day=1) + pd.DateOffset(days=(5 - date.replace(day=1).weekday() + 7) % 7))
                    fifth_saturday = first_saturday + pd.DateOffset(weeks=4)  # Calculate 5th Saturday (if exists)
                    return date == first_saturday or (fifth_saturday.month == date.month and date == fifth_saturday)
                return False

            # Iterate through each row to generate dates and distribute planned quantity
            for _, row in df_load_plan.iterrows():
                start_date = row['Date_Start']
                end_date = row['Date_End']

                # Generate full date range
                full_date_range = pd.date_range(start=start_date, end=end_date)
                # Remove holidays from the date range
                full_date_range = full_date_range[~full_date_range.isin(holiday_dates)]

                # Filter out Sundays and 1st & 5th Saturdays
                # working_days = [date for date in full_date_range if date.weekday() != 6 and not is_excluded_saturday(date)]

                # Keep only weekdays + 1st & 5th Saturdays (drop other Saturdays & Sundays)
                working_days = [
                    date for date in full_date_range
                    if date.weekday() != 6 and (date.weekday() != 5 or is_included_saturday(date))
                ]

                # Number of working days after filtering
                num_working_days = len(working_days)

                # Calculate distributed quantity only for working days
                planned_qty_per_day = row['Planned Qty'] / num_working_days if num_working_days > 0 else 0

                # Calculate distributed quantity only for working days
                qty_order_per_day = row['QTY ORDER'] / num_working_days if num_working_days > 0 else 0

                # Create new rows for each valid working date
                for planned_date in working_days:
                    new_row = row.copy()
                    new_row['Planned Dates'] = planned_date.strftime('%d/%m/%y')  # Format as dd/mm/yy
                    new_row['Planned Qty'] = round(planned_qty_per_day, 2)  # Distribute quantity among working days
                    new_row['QTY ORDER'] = round(qty_order_per_day, 2)  # Distribute quantity among working days
                    expanded_rows.append(new_row)


            # Create new DataFrame from expanded rows
            df_load_plan_transformed = pd.DataFrame(expanded_rows)
            df_load_plan_transformed['Planned Dates'] = pd.to_datetime(df_load_plan_transformed['Planned Dates'], format='%d/%m/%y', errors='coerce')

            # output_path = 'csv_files/df_load_plan_transformed.csv'
            # df_load_plan_transformed.to_csv(output_path, index=False)

            # Get unique production lines
            unique_lines = df_load_plan_transformed["Line"].unique().tolist()

            # Prepare optimization parameters from form
            max_styles_per_day = request.POST.get('max_styles_per_day')
            max_styles_per_day = int(max_styles_per_day) if max_styles_per_day else 2
            custom_line_capacities = request.POST.get("line_capacities")  # Dictionary {line_name: capacity}


            if custom_line_capacities:
                custom_line_capacities = json.loads(custom_line_capacities)

            # Identify order-related columns
            # order_identifiers = [col for col in ['ORDER NO', 'OC NO'] if col in df_load_plan_transformed.columns]
            order_identifiers = []
            if 'ORDER NO' in df_load_plan_transformed.columns:
                order_identifiers.append('ORDER NO')
            if 'OC NO' in df_load_plan_transformed.columns:
                order_identifiers.append('OC NO')


            if order_identifiers:
                logger.info(f"Order identifier columns found: {', '.join(order_identifiers)}")
                logger.info("Order references will be preserved during optimization")

            
            # Handle fabric article column
            if 'FABRIC ARTICLE' not in df_load_plan_transformed.columns:
                # Automatically add default fabric article
                df_load_plan_transformed['FABRIC ARTICLE'] = 'DEFAULT'
            

            # Use default capacity (1300) if custom capacities are not provided
            if not custom_line_capacities:
                custom_line_capacities = {line: 1300 for line in unique_lines}

            # Validate line capacities
            for line, capacity in custom_line_capacities.items():
                if capacity <= 0:
                    return error_response(error=f"Invalid capacity for line {line}. Must be positive.", status=status.HTTP_400_BAD_REQUEST)
                
            keep_split_id = False
            if order_identifiers:
                keep_split_tracking = 'y' #input("\nDo you want to keep split tracking IDs in the output? (y/n): ").lower().strip()
                keep_split_id = (keep_split_tracking == 'y' or keep_split_tracking == 'yes')
                if keep_split_id:
                    logger.info("Split tracking IDs will be kept in the final output")
                else:
                    logger.info("Split tracking IDs will be removed from the final output")

            merge_with_original = 'n' #input("\nDo you want to preserve all original columns in your data? (y/n): ").lower().strip()
            preserve_columns = (merge_with_original == 'y' or merge_with_original == 'yes')

            confirm = 'y' #input("\nProceed with optimization? (y/n): ").lower().strip()
            if confirm != 'y' and confirm != 'yes':
                logger.info("Optimization cancelled.")
                return

            logger.info("\nStarting production plan optimization...")
            logger.info("Considering both style and fabric article in sequencing...")
            if order_identifiers:
                logger.info("Preserving original order identifiers across allocations...")

            # Run optimization
            new_plan, original_total = redistribute_production_plan(
                df_load_plan_transformed,
                line_capacities=custom_line_capacities,
                respect_date_ranges=True,
                max_styles_per_day=max_styles_per_day
            )

            # Drop Split_ID if needed
            if 'Split_ID' in new_plan.columns:
                new_plan = new_plan.drop('Split_ID', axis=1)
                logger.info("Dropped Split_ID column")

            # Define the columns to group by
            group_columns = [
                'OC NO', 'ORDER NO', 'CFM DATE', 'MERCHANT', 'STYLE', 'BUYER', 'L/S-S/S',
                'FABRIC ARTICLE', 'SMV', 'DEL DATE', 'MONTH CODE', 'QTY ORDER', 'sheet_name',
                'Line', 'Week', 'Date_Start', 'Date_End', 'Planned Dates'
            ]

            # Filter to columns that actually exist in the DataFrame
            existing_columns = [col for col in group_columns if col in new_plan.columns]
            logger.info(f"Grouping by {len(existing_columns)} columns: {', '.join(existing_columns)}")


            # Handle date columns specially - convert all date columns to string
            for col in existing_columns:
                if 'DATE' in col.upper() or 'Date' in col:
                    try:
                        # Only convert if it's actually a datetime column
                        if pd.api.types.is_datetime64_dtype(new_plan[col]):
                            logger.info(f"Converting datetime column to string: {col}")
                            new_plan[col] = new_plan[col].dt.strftime('%Y-%m-%d')
                    except Exception as e:
                        logger.info(f"Warning: Could not convert date column {col}: {str(e)}")

            # Perform the grouping with string-converted date columns
            try:
                grouped_df = new_plan.groupby(existing_columns, as_index=False).agg({'Planned Qty': 'sum'})
                grouped_total = grouped_df['Planned Qty'].sum()

                logger.info(f"Total quantity after grouping: {grouped_total}")
                logger.info(f"Difference: {grouped_total - original_total}")

                if abs(grouped_total - original_total) > 0.1:  # Allow for minor rounding
                    logger.info("WARNING: Quantity change detected after grouping!")

                    # Use the manual approach as a fallback
                    logger.info("Falling back to manual grouping method...")

                    # Manual grouping approach
                    grouped_data = {}

                    for _, row in new_plan.iterrows():
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
                            grouped_data[key]['qty'] += row['Planned Qty']
                            grouped_data[key]['count'] += 1
                        else:
                            grouped_data[key] = {
                                'qty': row['Planned Qty'],
                                'row': row.copy(),
                                'count': 1
                            }

                    # Convert back to DataFrame
                    result_rows = []
                    for key, data in grouped_data.items():
                        row_copy = data['row'].copy()
                        row_copy['Planned Qty'] = data['qty']
                        result_rows.append(row_copy)

                    grouped_df = pd.DataFrame(result_rows)
                    manual_total = grouped_df['Planned Qty'].sum()

                    logger.info(f"Manual grouping result: {len(grouped_df)} rows")
                    logger.info(f"Total quantity after manual grouping: {manual_total}")
                    logger.info(f"Difference from original: {manual_total - original_total}")

                # Use the grouped DataFrame (either from pandas or manual approach)
                new_plan = grouped_df

            except Exception as e:
                logger.info(f"ERROR during grouping: {str(e)}")
                logger.info("Continuing with ungrouped data to preserve quantities")

            # Sort by Planned Dates
            if 'Planned Dates' in new_plan.columns:
                # If we converted dates to strings, convert back to datetime for sorting
                if not pd.api.types.is_datetime64_dtype(new_plan['Planned Dates']):
                    try:
                        new_plan['Planned Dates'] = pd.to_datetime(new_plan['Planned Dates'])
                    except:
                        logger.info("Warning: Could not convert Planned Dates back to datetime for sorting")

                new_plan = new_plan.sort_values('Planned Dates', ascending=True)
                logger.info("Sorted data by Planned Dates in ascending order")

            logger.info(f"Final dataframe has {len(new_plan)} rows with total quantity {new_plan['Planned Qty'].sum()}")

            ################################################################################################

            # output_file = 'csv_files/optimized_production_plan_order_preserved_2.csv' ###Change this file name to the input table filename for the manning sheet (mostly df_load_plan_transformed)
            # new_plan.to_csv(output_file, index=False)
            # print(f"\nOptimized production plan saved to '{output_file}'")

            # Delete old data before inserting new records
            truncate_table(LoadingPlan)

            # Insert data in chunks
            records = [
                LoadingPlan(
                    oc_no=row['OC NO'], order_no=row['ORDER NO'], cfm_date=row['CFM DATE'] if pd.notna(row['CFM DATE']) else None, merchant=row['MERCHANT'],
                    style=row['STYLE'], buyer=row['BUYER'], ls_ss=row['L/S-S/S'], fabric_article=row['FABRIC ARTICLE'],
                    smv=row['SMV'], del_date=row['DEL DATE'] if pd.notna(row['DEL DATE']) else None, month_code=row['MONTH CODE'], qty_order=row['QTY ORDER'],
                    sheet_name=row['sheet_name'], line=row['Line'], week=row['Week'], planned_qty=row['Planned Qty'],
                    date_start=row['Date_Start'] if pd.notna(row['Date_Start']) else None, date_end=row['Date_End'] if pd.notna(row['Date_End']) else None,
                    planned_dates=row['Planned Dates'] if pd.notna(row['Planned Dates']) else None
                ) for _, row in new_plan.iterrows()
            ]

            with transaction.atomic():
                for i in range(0, len(records), CHUNK_SIZE):
                    LoadingPlan.objects.bulk_create(records[i:i+CHUNK_SIZE])

            ####statistics
            if 'FABRIC ARTICLE' in new_plan.columns:
                style_fabric_combos = new_plan[['STYLE', 'FABRIC ARTICLE']].drop_duplicates()
                unique_styles = new_plan['STYLE'].nunique()
                unique_fabrics = new_plan['FABRIC ARTICLE'].nunique()

                logger.info(f"\nPlan statistics:")
                logger.info(f"Total unique styles: {unique_styles}")
                logger.info(f"Total unique fabric articles: {unique_fabrics}")
                logger.info(f"Total unique style+fabric combinations: {len(style_fabric_combos)}")


            if order_identifiers:
                id_field = order_identifiers[0]  # Use the first identifier for statistics
                total_orders = new_plan[id_field].nunique()
                total_rows = len(new_plan)

                logger.info(f"\nOrder statistics:")
                logger.info(f"Total unique orders: {total_orders}")
                logger.info(f"Total rows in optimized plan: {total_rows}")

                if 'Split_ID' in new_plan.columns:
                    split_ids = [x for x in new_plan['Split_ID'] if not pd.isna(x)]
                    order_splits = {}

                    for split_id in split_ids:
                        row_id = split_id.split('_')[0]
                        if row_id not in order_splits:
                            order_splits[row_id] = 0
                        order_splits[row_id] += 1

                    split_orders = sum(1 for count in order_splits.values() if count > 1)
                    max_splits = max(order_splits.values()) if order_splits else 0

                    logger.info(f"Orders split across multiple days: {split_orders} ({split_orders/total_orders*100:.1f}%)")
                    logger.info(f"Maximum splits for a single order: {max_splits}")

            return success_response(message= 'File processed and data saved successfully', status=status.HTTP_201_CREATED)
        except Exception as e:
            return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)
    return error_response(error= 'Invalid request', status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def emp_fact_file_upload(request):
    if request.method == 'POST':
        file = request.FILES.get('file')
        if not file:
            return error_response(error='File is required', status=status.HTTP_400_BAD_REQUEST)
        
        try:
            df_emp_fact = pd.read_csv(file)
            df_emp_fact.dropna(subset=['EMPLOYEE ID'], inplace=True)
            
            records = [
                EMPFact(
                    employee_id=int(row['EMPLOYEE ID']),
                    employee_name=row['EMPLOYEE NAME'],
                    line=row['LINE'],
                    factory=row['FACTORY'],
                    floor=row['FLOOR'],
                    section=row['SECTION'],
                    designation=row['DESIGNATION'],
                    code=row['CODE'],
                    operation=row['OPERATION'],
                    type=row['TYPE'],
                    sam=float(row['SAM']),
                    peak_capacity=int(row['PEAK CAPACITY']),
                    average_capacity=int(row['AVERAGE CAPACITY']),
                    machine=row['MACHINE'],
                    status=row['STATUS']
                ) for _, row in df_emp_fact.iterrows()
            ]
            
            EMPFact.objects.all().delete()
            EMPFact.objects.bulk_create(records)
            
            return success_response(message= 'File processed and data saved successfully', status=status.HTTP_201_CREATED)
        except Exception as e:
            return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)
    
    return error_response(error= 'Invalid request', status=status.HTTP_400_BAD_REQUEST)



@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def wip_file_upload(request):
    if request.method == 'POST':
        file = request.FILES.get('file')
        if not file:
            return error_response(error='File is required', status=status.HTTP_400_BAD_REQUEST)
        
        try:
            df_wip_data = pd.read_csv(file)
            
            records = [
                WIPData(
                    # row['color'].upper() if row['color'] else row['color']
                    oc_no=row['OC NO'].lower() if row['OC NO'] else row['OC NO'],
                    order_no=row['ORDER NO'],
                    buyer=row['BUYER'].lower() if row['BUYER'] else row['BUYER'],
                    style=row['STYLE'].lower() if row['STYLE'] else row['STYLE'],
                    line=row['LINE'],
                    color=row['COLOR'].lower() if row['COLOR'] else row['COLOR'],
                    section=row['SECTION'],
                    op_seq=row['OP_SEQ'],
                    operation=row['OPERATION'],
                    code=row['CODE'],
                    wip_qty=row['WIP  QTY'],
                ) for _, row in df_wip_data.iterrows()
            ]
            
            WIPData.objects.all().delete()
            WIPData.objects.bulk_create(records)
            
            return success_response(message= 'File processed and data saved successfully', status=status.HTTP_201_CREATED)
        except Exception as e:
            return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)
    
    return error_response(error= 'Invalid request', status=status.HTTP_400_BAD_REQUEST)



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


@api_view(['GET', 'POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated]) 
def get_manning_data(request):
    try:
        line_no = request.query_params.get('line', '').strip().capitalize()
        section_value = request.query_params.get('section', '').strip().capitalize()
        period = request.query_params.get('forecast_period', '').strip()
        style = request.query_params.get('style', '').strip()
        planned_date = request.query_params.get('planned_date', '').strip()

        # Validate required fields
        if not line_no or not section_value or not period:
            return error_response(error='"line", "section" and "forecast_period" are required.', status=status.HTTP_400_BAD_REQUEST)

        if not style:
            style = "all"

        valid_lines = [f'Line {i}' for i in range(1, 11)] + ['All']
        valid_sections = ['Collar', 'Assembly', 'Front', 'Cuff', 'Sleeve', 'Back']
        valid_periods = ['1', '7', '30', '60']
        
        if line_no not in valid_lines:
            return error_response(error='Invalid line number. Use "Line X" or "all"', status=status.HTTP_400_BAD_REQUEST)
        if section_value not in valid_sections:
            return error_response(error='Invalid section. Choose from valid options.', status=status.HTTP_400_BAD_REQUEST)
        if period not in valid_periods:
            return error_response(error='Invalid forecast period. Choose from 1, 7, 30, 60.', status=status.HTTP_400_BAD_REQUEST)
        
        period = int(period)  # Convert forecast_period to integer

        today = datetime.today().date()
        date_range = [(today + timedelta(days=i)) for i in range(1, period + 1)] # This list won't include today's date

        # Apply filters dynamically based on conditions
        manning_sheet_filters = {'section': section_value, 'planned_dates__in': date_range}
        manning_general_filters = {'section': section_value, 'planned_dates__in': date_range}
        employee_master_filters = {'section': section_value, 'designation': 'machinist'}
        employees_on_hold_filter = {'section': section_value, 'date__in': date_range}

        if line_no.lower() != 'all':
            manning_sheet_filters['line'] = line_no
            manning_general_filters['line'] = line_no
            employee_master_filters['line'] = line_no.upper()
            employees_on_hold_filter['line'] = line_no

        if style.lower() != 'all':
            manning_sheet_filters['style'] = style.lower()
            manning_general_filters['style'] = style.lower()
        
        if planned_date:
            try:
                planned_date = datetime.strptime(planned_date, '%Y-%m-%d').date()
                manning_sheet_filters['planned_dates'] = planned_date
                manning_general_filters['planned_dates'] = planned_date
                employees_on_hold_filter['date'] = planned_date
            except ValueError:
                return error_response(error='Invalid date format. Use YYYY-MM-DD.', status=status.HTTP_400_BAD_REQUEST)

        employees_on_hold_queryset = EmployeesOnHold.objects.filter(**employees_on_hold_filter)
        
        # Query filtered data
        filtered_data_table = ManningSheetData.objects.filter(**manning_sheet_filters).distinct()
        filtered_data_info = ManningGeneralInfo.objects.filter(**manning_general_filters).distinct()

        # Step 1: Group data by operation with unique (machine_type, operator_name, operator_id)
        grouped_result = defaultdict(set)

        grouped_data = filtered_data_table.only(
            'operation', 'machine_type', 'allocated_emp_name', 'allocated_emp_id'
        )

        for row in grouped_data:
            key = (row.machine_type, row.allocated_emp_name or "N/A", row.allocated_emp_id)
            grouped_result[row.operation].add(key)

        # Step 2: Flatten grouped data and count machine_type occurrences & operator counts
        machine_type_count = defaultdict(int)
        required_machinists = 0

        for entries in grouped_result.values():
            for machine_type, operator_name, operator_id in entries:
                machine_type_count[machine_type] += 1
                required_machinists += 1

        # Convert defaultdicts to normal dicts if needed
        machine_type_count_dict = dict(machine_type_count)

        machine_nonMachine_info = [
            {'machine_type': key, 'count': value}
            for key, value in machine_type_count_dict.items()
        ]
        
        if not filtered_data_table.exists() and not filtered_data_info.exists():
            return success_response(message='No data to display', data={
                'table_data': [{
                    'Operation': 'N/A', 'Machine': 'N/A', 'Operator Name': 'N/A', 'SMV': 'N/A', 'Actual Perf%': 'N/A'
                }],
                'general_info': {
                    'total_machinist_available': 0,
                    'total_non_machinist_available': 0,
                    'machinist_required': 0,
                    'non_machinist_required': 0,
                    'total_required': 0,
                    'total_available': 0
                },
                'machine_nonMachine_info': {},
                'message': 'No data to display'
            }, status=status.HTTP_200_OK)

        filtered_data_table = (
            filtered_data_table
            .order_by('planned_dates', 'op_seq')  # Order first by section, then within each section
            .values()
        )

        formatted_data = [
            {   
                'Date': row['planned_dates'].strftime('%d-%m-%Y') if row['planned_dates'] else row['planned_dates'],
                'Operation': row['operation'],
                'Style': row['raw_style'],
                'Buyer': row['buyer'],
                'Color': row['raw_color'].upper() if row['raw_color'] else row['raw_color'],
                'OC Number': row['raw_oc_no'].upper() if row['raw_oc_no'] else row['raw_oc_no'],
                'Order Number': row['order_no'],
                'Machine Type': row['machine_type'],
                'Operator Name': row['allocated_emp_name'],
                'Operator ID': row['allocated_emp_id'],
                'SAM': row['sam'],
                'Week': row['week'],
                'Planned Quantity': row['planned_qty'],
                'Allocated Capacity': row['allocated_capacity'],
                'Shortage Reason': row['shortage_reason'],
                'Manning_ID': row['id'],
                'Code': row['code']
            }
            for row in filtered_data_table
        ]

        # Create a dict mapping date strings in '%d-%m-%Y' format to preferred_employees JSON string
        date_to_preferred_employees = {}

        for obj in employees_on_hold_queryset:
            date_str = obj.date.strftime('%d-%m-%Y')
            date_to_preferred_employees[date_str] = json.loads(obj.preferred_employees) if obj.preferred_employees else []


        for row in formatted_data:
            date_key = row.get('Date')
            operator_id = row.get('Operator ID')
            operator_name = row.get('Operator Name')
            if row.get('Operator ID') == 0:
                preferred = date_to_preferred_employees.get(date_key, [])
                unique_preferred_employees = remove_duplicate_employee_dicts(preferred)
                preferred_emps = [
                    emp for emp in unique_preferred_employees
                    if not (operator_id in emp and emp[operator_id] == operator_name)
                ]
                row['Preferred Employees'] = preferred_emps
            else:
                row['Preferred Employees'] = []

        
        # ------------------------------------------------------------------------------------------- #
        # # Create a dict mapping date strings in '%d-%m-%Y' format to preferred_employees JSON string
        # date_to_preferred_employees = {}

        # for obj in employees_on_hold_queryset:
        #     date_str = obj.date.strftime('%d-%m-%Y')
        #     date_to_preferred_employees[date_str] = json.loads(obj.preferred_employees) if obj.preferred_employees else []


        # for row in formatted_data:
        #     date_key = row.get('Date')
        #     if row.get('Operator ID') == 0:
        #         preferred = date_to_preferred_employees.get(date_key, [])
        #         row['Preferred Employees'] = preferred
        #     else:
        #         row['Preferred Employees'] = []
        # ------------------------------------------------------------------------------------------- #


        actual_machinists = EmployeeMaster.objects.filter(**employee_master_filters).count()
        # # OLD LOGIC REJECTED BY CLIENT
        # required_machinists = filtered_data_table.values_list('code', flat=True).distinct().count()
        # working_days = filtered_data_table.values_list('planned_dates', flat=True).distinct().count()

        # # Group by machine and count occurrences and exclude None and Null values before aggregation
        # machine_nonMachine_info = (
        #     filtered_data_table
        #                     # .exclude(machine__isnull=True)
        #                     # .exclude(machine='null')
        #                     .values('machine_type')
        #                     .annotate(count=Count('machine_type'))
        #                     # .annotate(total_machinist_required=Sum('machinist_required'))
        # )
        # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
        machine_dict = {entry['machine_type']: entry['count'] for entry in machine_nonMachine_info}

        unique_buyers = ', '.join(set(buyer.upper() for buyer in filtered_data_table.values_list('buyer', flat=True) if buyer))
        info = {'buyers': unique_buyers}
        general_info = {'total_required': required_machinists, 'total_available': actual_machinists}

        prediction_response = get_actual_vs_planned_data(line_no=line_no, forecast_period=period, today=today, section=section_value, planned_date=planned_date)
        resp = prediction_response.data['data']
        response_data = {
            'table_data': formatted_data,
            'machinist_nonMachinist_count': general_info,
            'machinist_nonMachinist_info': machine_dict,
            'info': info,
            'message': 'Success',
            'Target data': resp['Target data']
        }

        # Add unique styles if style == 'all'
        if style.lower() == 'all':
            unique_styles = filtered_data_table.values_list('style', flat=True).distinct()
            # response_data['unique_styles'] = [s.upper() for s in unique_styles if s]
            response_data['unique_styles'] = list({s.upper() for s in unique_styles if s})
        
        if request.method == 'POST':
            # Create a new list with 'Manning_ID' and 'Code' removed
            sanitized_data = [
                {k: v for k, v in row.items() if k not in ['Manning_ID', 'Code']}
                for row in formatted_data
            ]
            # Replace in response_data
            response_data['table_data'] = sanitized_data

            excel_data = export_to_excel(response_data, style)
            response = HttpResponse(
                excel_data.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            response["Content-Disposition"] = f'attachment; filename="{line_no.title()}_ManningSheet__{section_value.title()}_{style}_{period}Days.xlsx"'
            return response

        return success_response(message='Success', data=response_data, status=status.HTTP_200_OK)
    except Exception as e:
        return success_response(message=f"Error: {str(e)}", data=None, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



# To get the actual vs planned data for selected date
def get_actual_vs_planned_data(line_no, forecast_period, today, summation=False, section=None, dday=None, planned_date=None):
    try:
        filter_date = today if dday else today + timedelta(days=forecast_period)
        filter_date = planned_date if planned_date else filter_date

        manning_sheet_filter = {'planned_dates': filter_date, 'machinist': True}
        # absenteeism_filter = {'forecast_period': forecast_period}
        loading_plan_filter = {'planned_dates': filter_date}
        # absenteeism_filter_primary={}
        employee_filter={}

        if line_no.lower() != 'all':
            employee_filter['line']=line_no.upper()
    
        if section is not None:
            sections = [section]
            employee_filter['section'] = section
            # absenteeism_filter['section']=section.upper()
            # absenteeism_filter_primary['section']=section.upper()
            manning_sheet_filter['section']=section
        else:
            sections = ['Assembly', 'Cuff', 'Front', 'Back', 'Sleeve', 'Collar']

        total_emp_count = EmployeeMaster.objects.filter(**employee_filter).count()
        if total_emp_count == 0:
            return None, None, error_response(error='No employees found.', status=status.HTTP_404_NOT_FOUND)

        if line_no.lower() != 'all':
            # absenteeism_filter['line'] = line_no.upper()
            loading_plan_filter['line'] = line_no.title()
            manning_sheet_filter['line'] = line_no.title()
            # absenteeism_filter_primary['line']=line_no.upper()

        # search_date = today
        # if forecast_period == 1:
        #     absenteeism_filter['forecast_period'] = 7
        #     absenteeism_filter_primary['forecast_period']=7

        #     while True:
        #         absenteeism_filter_primary['datetime'] = search_date
        #         prediction_qs = AbsenteeismPrediction.objects.filter(
        #             **(absenteeism_filter_primary)
        #         ).exclude(section__iexact='nan')

        #         if prediction_qs.exists():
        #             absenteeism_filter['datetime'] = search_date
        #             break
        #         search_date += timedelta(days=1)

        #     total_values = 1
        # else:
        #     absenteeism_filter['datetime__lte'] = filter_date
        #     absenteeism_filter_primary['datetime__lte'] = filter_date
        #     absenteeism_filter_primary['forecast_period']=forecast_period

        #     prediction_qs = AbsenteeismPrediction.objects.filter(
        #         **(absenteeism_filter_primary)
        #     ).exclude(section__iexact='nan')
        #     total_values = prediction_qs.values('datetime').distinct().count()

        # if not prediction_qs.exists():
        #     return None, None, error_response(error='No predictions found.', status=status.HTTP_404_NOT_FOUND)

        manning_sheet_qs = ManningSheetData.objects.filter(**manning_sheet_filter)
        manning_sheet_target = (
            manning_sheet_qs
            .values('section', 'code', 'style')
            .annotate(total_planned_qty=Sum('allocated_capacity'))
        )

        # Find the minimum value per section (including all matching records)
        min_entries = {}

        # for item in manning_sheet_target:
        #     section = item['section']
        #     qty = item['total_planned_qty']
        #     if section not in min_entries or qty < min_entries[section]['total_planned_qty']:
        #         min_entries[section] = item  # Keep only one item with min qty

        for item in manning_sheet_target:
            key = (item['section'], item['style'])  # tuple as key
            qty = item['total_planned_qty']
            
            if key not in min_entries or qty < min_entries[key]['total_planned_qty']:
                min_entries[key] = item  # Keep only one item with min qty

        # Convert result to list
        min_entries_list = list(min_entries.values())

        # Aggregate total_planned_qty per section
        section_summary = defaultdict(float)

        for item in min_entries_list:
            section_summary[item['section']] += item['total_planned_qty']

        # Convert to list of dicts if needed
        result = [{'section': sec, 'total_planned_qty': qty} for sec, qty in section_summary.items()]

        # section_data = (
        #     EmployeeMaster.objects
        #     .filter(**employee_filter)
        #     .values('section')
        #     .annotate(count=Count('emp_code'))
        # )

        total_planned_qty = (
            LoadingPlan.objects
            .filter(**loading_plan_filter)
            .aggregate(total_planned_qty=Sum('planned_qty'))
        )['total_planned_qty'] or 0

        production_target = [
            {'section': section, 'total_planned_qty': round(total_planned_qty, 2)}
            for section in sections
        ]

        # total_gap_summary = (
        #     AbsenteeismPrediction.objects
        #     .filter(**absenteeism_filter)
        #     .exclude(section='nan')
        #     .values('section')
        #     .annotate(count=Sum('predicted_absent_count'))
        # )

        # gap_summary_normalized = [
        #     {
        #         'section': entry['section'].strip().capitalize(),
        #         'count': convert_number(entry['count'] / total_values)
        #     }
        #     for entry in total_gap_summary
        # ]

        # section_emp_count = {
        #     item['section']: item['count']
        #     for item in section_data
        # }

        # # Calculate absenteeism percentage by section
        # absenteeism_percentage_by_section = {
        #     item['section']: round((item['count'] / section_emp_count[item['section']] * 100), 1) if total_emp_count else 0
        #     for item in gap_summary_normalized
        # }

        # # Calculate predicted production based on absenteeism percentage
        # predicted_production = [
        #     {
        #         'section': item['section'],
        #         'total_planned_qty': custom_round(item['total_planned_qty'] - (item['total_planned_qty'] * absenteeism_percentage_by_section.get(item['section'], 0) / 100))
        #     }
        #     for item in result
        # ]
        predicted_production = update_sections(result, sections)

        # Special handling for "all" lines case
        if line_no.lower() == "all":
            # First calculate individual line predictions
            all_line_predictions = {}
            for line_index in range(1, 11):
                individual_line = f"line {line_index}"
                # Call recursively but don't return, just store results
                response_data = get_actual_vs_planned_data(line_no=individual_line, forecast_period=forecast_period, today=today, summation=True, section=section, dday=dday)
                response_data = response_data.data
                
                # If the response is valid, extract the prediction data
                if isinstance(response_data, tuple):
                    continue  # Skip invalid responses
                
                if 'data' in response_data and 'Target data' in response_data['data']:
                    prediction_data = response_data['data']['Target data'][0]['predicted_production']
                    # Store by line number for aggregation
                    all_line_predictions[individual_line] = prediction_data

            # 1. Accumulate totals per section
            section_totals = defaultdict(float)

            for sections in all_line_predictions.values():
                for item in sections:
                    section_totals[item["section"]] += item["total_planned_qty"]

            # 2. Convert to desired list-of-dict format
            predicted_production = [{"section": section, "total_planned_qty": qty} for section, qty in section_totals.items()]

        if summation==False:
            # First, find if any non-Assembly section has zero quantity
            non_assembly_zero = any(
                item['section'] != 'Assembly' and item['total_planned_qty'] == 0.0
                for item in predicted_production
            )
            # If condition met, directly update Assembly section in same loop
            if non_assembly_zero:
                for item in predicted_production:
                    if item['section'] == 'Assembly':
                        item['total_planned_qty'] = 0.0
                        break

        production_data = [{
            "production_target": production_target,
            "predicted_production": predicted_production,
            # "absenteeism_percentage_by_section": absenteeism_percentage_by_section
        }]

        prediction_response = {
            'Target data': production_data
        }

        return success_response(message='Data fetched successfully', data=prediction_response, status=status.HTTP_200_OK)

    except Exception as e:
        logger.info(f"Error in prepare_prediction_data: {str(e)}")
        return error_response(error=f"Unknown error: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Function to use in scheduler to send email of dday data at 8:50 AM, 12:45 PM and 05:30 PM
def get_dday_data():
    try:
        logger.info(f"*******************************************************************")
        logger.info(f"Running DDAY Mailing at {str(datetime.now())} hours!")

        # Calculate dates
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)

        dday_data = fetch_dday_data('All')
        attendance_data = fetch_attendance_data('All', today, yesterday)

        df = pd.DataFrame(dday_data["data"]["records"])
        df.drop(columns=['Dday_ID', 'WIP Qty'], inplace=True)

        planned_attendance = attendance_data['data']['attendance_data']['Planned Attendance']
        present = attendance_data['data']['attendance_data']['Present']
        absent = attendance_data['data']['attendance_data']['Absent']

        # Generate Excel file in memory
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name="Sheet1", startrow=5, index=False)

            # Get the worksheet AFTER writing the DataFrame
            worksheet = writer.sheets["Sheet1"]
            workbook = writer.book
            bold_format = workbook.add_format({'bold': True})  # Bold format for headers

            # Write attendance data at the top with proper alignment
            worksheet.write(0, 0, "Line number", bold_format)
            worksheet.write(0, 1, "All")

            worksheet.write(1, 0, "Planned Attendance", bold_format)
            worksheet.write(1, 1, planned_attendance)

            worksheet.write(2, 0, "Present", bold_format)
            worksheet.write(2, 1, present)

            worksheet.write(3, 0, "Absent", bold_format)
            worksheet.write(3, 1, absent)

            # Adjust column width for A and B (0 and 1)
            worksheet.set_column(0, 0, 25)  # Column A (Labels)
            worksheet.set_column(1, 1, 15)  # Column B (Values)

            # Adjust column widths dynamically based on data
            for i, col in enumerate(df.columns):
                if col != 'Factory':
                    max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2  # Adjust width
                    worksheet.set_column(i, i, max_len, workbook.add_format({'text_wrap': False}))  # Disable text wrapping

            # Handle "Preferred Employees" column formatting
            preferred_col_index = list(df.columns).index("Preferred Employees")
            worksheet.set_column(preferred_col_index, preferred_col_index, 30)  # Fixed width

            # Create a custom format to prevent text overflow in "Preferred Employees"
            truncate_format = workbook.add_format({
                'text_wrap': False,
                'num_format': '@'  # Text format
            })

            # Apply format to all rows in "Preferred Employees" column
            for row_num in range(6, 6 + len(df)):  # Data starts from row 6
                worksheet.write(row_num, preferred_col_index, df["Preferred Employees"].iloc[row_num - 6], truncate_format)

        output.seek(0)

        userEmails = list(User.objects.filter(send_mail=True, status=True).values_list('email', flat=True))

        subject = "Download D-Day Manning Data File"
        file_name = "Dday_Manning_data_ALL.xlsx"
        file_data = output  # Pass the BytesIO object directly
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        # Call the send_email function
        send_email(userEmails, file_data, subject, content_type, file_name=file_name, test=True)
        # Send push notifications to all users regardless of status
        notification_type = get_notification_type_by_time()
        time_display = NOTIFICATION_DISPLAY_TIME.get(notification_type, "Unknown")
        notification_title = NOTIFICATION_DISPLAY_TITLE.get(notification_type, "Unknown")

        with open(f"exports/Dday_Manning_data_ALL_{today}_{time_display.replace(' ', '_').replace(':', '_')}.xlsx", "wb") as f:
            f.write(output.getvalue())

        create_bulk_push_notifications(
            notification_type=notification_type,
            title=notification_title,
            message=f"Kindly review the D-Day prediction data provided for {time_display}",
            users=User.objects.filter(status=True),  # only active users
            data={"fileName": f"Dday_Manning_data_ALL_{today}_{time_display.replace(' ', '_').replace(':', '_')}.xlsx"}
        )
        logger.info(f"Email successfully sent at {str(datetime.now())} hours!")
        logger.info(f"***************************************************\n")

    except Exception as e:
        logger.error(f"Error in get_dday_8_45_12_45_5_30 function: {e}")
        return success_response(message="An unexpected error occurred in get_dday_8_45_12_45_5_30", status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return success_response(message="Success", status=status.HTTP_200_OK)



@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def download_manning_data_by_section(request):
    line_no = request.query_params.get('line', ' ').strip()
    period = request.query_params.get('forecast_period', ' ').strip()
    
    line_no = line_no.capitalize()
    
    try:
        # Validate required fields
        if not line_no or not period:
            return error_response(error='"line" and "forecast_period" are required.', status=status.HTTP_400_BAD_REQUEST)

        valid_lines = [f'Line {i}' for i in range(1, 11)] + ['All']
        valid_periods = ['1', '7', '30', '60']

        if line_no not in valid_lines:
            return error_response(error='Invalid line number. Use "Line X" or "all"', status=status.HTTP_400_BAD_REQUEST)
        if period not in valid_periods:
            return error_response(error='Invalid forecast period. Choose from 1, 7, 30, 60.', status=status.HTTP_400_BAD_REQUEST)

        period = int(period)  # Convert forecast_period to integer

        # nextDay = today + timedelta(days=1)
        today = datetime.today().date()
        date_range = [(today + timedelta(days=i)) for i in range(1, period + 1)] # This list won't include today's date

        # Apply filters dynamically based on conditions
        filters = {'planned_dates__in': date_range}
        employee_master_filters = {'designation': 'machinist'}

        if line_no.lower() != 'all':
            filters['line'] = line_no
            employee_master_filters['line'] = line_no.upper()

        # Query filtered data
        filtered_data_table = ManningSheetData.objects.filter(**filters).distinct()
        filtered_data_info = ManningGeneralInfo.objects.filter(**filters).distinct()

        if not filtered_data_table.exists() and not filtered_data_info.exists():
            return success_response(message='No data to display', data={
                'table_data': [{
                    'Operation': 'N/A', 'Machine': 'N/A', 'Operator Name': 'N/A', 'SMV': 'N/A', 'Actual Perf%': 'N/A'
                }],
                'general_info': {
                    'total_machinist_available': 0,
                    'total_non_machinist_available': 0,
                    'machinist_required': 0,
                    'non_machinist_required': 0,
                    'total_required': 0,
                    'total_available': 0
                },
                'machine_nonMachine_info': {},
                'message': 'No data to display'
            }, status=status.HTTP_200_OK)

        table_data_query = (
            filtered_data_table
            .order_by('planned_dates', 'op_seq')  # Order first by section, then within each section
            .values()
        )

        # Group data by section if section is not passed
        grouped_table_data = {}
        for row in table_data_query:
            section = row['section']
            if section not in grouped_table_data:
                grouped_table_data[section] = []
            
            grouped_table_data[section].append({
                'Date': row['planned_dates'].strftime('%d-%m-%Y') if row['planned_dates'] else row['planned_dates'],
                'Operation': row['operation'],
                'Style': row['style'],
                'Buyer': row['buyer'],
                'Color': row['color'].upper() if row['color'] else row['color'],
                'OC Number': row['oc_no'].upper() if row['oc_no'] else row['oc_no'],
                'Order Number': row['order_no'],
                'Machine Type': row['machine_type'],
                'Operator Name': row['allocated_emp_name'],
                'Operator ID': row['allocated_emp_id'],
                'SAM': row['sam'],
                'Week': row['week'],
                'Planned Quantity': row['planned_qty'],
                'Allocated Capacity': row['allocated_capacity'],
                'Shortage Reason': row['shortage_reason'],
            })

        actual_machinists = list(EmployeeMaster.objects.filter(**employee_master_filters).values('section').annotate(actual_machinists=Count('emp_code')))  # or another unique field like 'emp_code'

        # Step 1: Group data by section and operation with unique (machine_type, operator_name, operator_id)
        grouped_result = defaultdict(lambda: defaultdict(set))

        grouped_data = filtered_data_table.only(
            'section', 'operation', 'machine_type', 'allocated_emp_name', 'allocated_emp_id'
        )

        for row in grouped_data:
            section = row.section or "Unknown"
            operation = row.operation or "Unknown"
            key = (row.machine_type, row.allocated_emp_name or "N/A", row.allocated_emp_id)
            grouped_result[section][operation].add(key)

        # Step 2: Flatten grouped data into required output structure
        grouped_machine_nonMachine_info = {}
        required_machinists = []

        for section, operations in grouped_result.items():
            machine_type_count = defaultdict(int)
            machinist_count = 0

            for entries in operations.values():
                for machine_type, operator_name, operator_id in entries:
                    machine_type_count[machine_type] += 1
                    machinist_count += 1

            # Store machine type counts
            grouped_machine_nonMachine_info[section] = dict(machine_type_count)

            # Store machinist count if needed
            required_machinists.append({
                'section': section,
                'required_machinists': machinist_count
            })

        # Convert lists to dictionaries keyed by 'section'
        actual_dict = {item['section']: item['actual_machinists'] for item in actual_machinists}
        required_dict = {item['section']: item['required_machinists'] for item in required_machinists}

        # Merge into desired format
        grouped_general_info = {}
        for section in set(actual_dict) | set(required_dict):  # union of both keys
            grouped_general_info[section] = {
                'total_required': required_dict.get(section, 0),
                'total_available': actual_dict.get(section, 0)
            }

        # Aggregate info data from filtered_data_table (grouped by section)
        info_query = filtered_data_table.values('section').annotate(
            buyers=Count('buyer', distinct=True)
        )

        # Group buyers info by section
        grouped_info = {}
        for entry in info_query:
            section = entry['section']
            buyers_list = list(filtered_data_table.filter(section=section).values_list('buyer', flat=True).distinct())
            grouped_info[section] = {'buyers': [buyer.upper() for buyer in buyers_list if buyer]}  # Capitalize

        # Aggregate unique styles by section
        unique_styles_query = filtered_data_table.values('section').annotate(
            styles=Count('style', distinct=True)  # Count distinct styles
        )

        # Group unique styles by section
        grouped_unique_styles = {}
        for entry in unique_styles_query:
            section = entry['section']
            styles_list = list(filtered_data_table.filter(section=section).values_list('style', flat=True).distinct())
            grouped_unique_styles[section] = {'unique_styles': [style.upper() for style in styles_list if style]}  # Capitalize

        grouped_prediction_report={}
        for sec in ['Assembly', 'Cuff', 'Front', 'Back', 'Sleeve', 'Collar']:
            prediction_response = get_actual_vs_planned_data(line_no=line_no, forecast_period=period, today=today, section=sec)
            grouped_prediction_report[sec] = prediction_response.data['data']

        # Prepare response data
        response_data = {
            'table_data': grouped_table_data,
            'machinist_nonMachinist_count': grouped_general_info,
            'machinist_nonMachinist_info': grouped_machine_nonMachine_info,
            'info': grouped_info,
            'unique_styles': grouped_unique_styles,
            'prediction_report': grouped_prediction_report,
            'message': 'Success'
        }

        excel_data = export_json_to_excel(response_data)

        response = HttpResponse(
            excel_data.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = f'attachment; filename="{line_no.title()}_ManningSheet__{period}Days.xlsx"'
        return response

    except Exception as e:
        return success_response(message=f"Error: {str(e)}", data=None, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# To fetch only DDay Data
@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def get_dday_manning_data(request):
    try:
        # Get line parameter from either GET or POST
        line_no = request.query_params.get('line', '').strip().capitalize()

        if not line_no:
            return error_response(error='"line" is required.', status=status.HTTP_400_BAD_REQUEST)
        
        # Define valid line options
        valid_lines = [f'Line {i}' for i in range(1, 11)] + ['All']

        if line_no not in valid_lines:
            return error_response(error='Enter a valid line number (Valid Formats: "Line 1" or "line 3" or "LINE 5" or "all")', 
                                  status=status.HTTP_400_BAD_REQUEST)

        dday_data = fetch_dday_data(line_no)
        today = datetime.today().date()
        prediction_response = get_dday_actual_vs_planned_data(line_no=line_no, today=today)
        dday_data["data"]["prediction_data"] = prediction_response.data['data']
        unallocated_emp_data = get_unallocated_employees_count(line_no=line_no)
        dday_data["data"]["unallocated_emp_data"] = unallocated_emp_data

        return success_response(
            data=dday_data["data"], 
            message=dday_data["message"], 
            status=dday_data["status"]
        )
    except Exception as e:
        return error_response(error=f"An unexpected error occurred: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)



def get_unallocated_employees_count(line_no):
    file_path = 'exports/unallocated_report_dday.csv'

    if not os.path.exists(file_path):
        return 0
    try:
        df = pd.read_csv(file_path, usecols=['line', 'reason', 'type'])
        
        # Apply the same filtering as in the export function
        df = df[(df['reason'] != 'Employee Absent') & (df['type'] == 'Primary')]

        if line_no.lower() != 'all':
            return (df['line'] == line_no.title()).sum()
        else:
            return len(df)
    except Exception as e:
        logger.info(f"Error reading unallocated report: {e}")
        return 0  # In case of read/parsing error

# To get the actual vs planned data for selected date
# <--------------------Vatsals code 29-Aug-2025------------------>    
# To get the actual vs planned data for selected date 

# def get_dday_actual_vs_planned_data(line_no, today, summation=False):
#     try:
#         sections = ['Assembly', 'Cuff', 'Front', 'Back', 'Sleeve', 'Collar']
#         manning_sheet_filter = {'planned_dates': today, 'machinist': True}
#         loading_plan_filter = {'planned_dates': today}
#         # attendance_filter={'attendance_date': today}

#         if line_no.lower() != 'all':
#             loading_plan_filter['line'] = line_no.title()
#             manning_sheet_filter['line'] = line_no.title()
#             # attendance_filter['line'] = line_no.title()

#         total_planned_qty = (
#             LoadingPlan.objects
#             .filter(**loading_plan_filter)
#             .aggregate(total_planned_qty=Sum('planned_qty'))
#         )['total_planned_qty'] or 0

#         production_target = [{"section": "Assembly", "total_planned_qty": total_planned_qty}]

        # # Modify to display only Assembly
        # production_target = [
        #     {'section': section, 'total_planned_qty': round(total_planned_qty, 2)}
        #     for section in sections if section == "Assembly"
        # ]

        # manning_sheet_qs = ManningSheetData.objects.filter(**manning_sheet_filter)
        # manning_sheet_target = (
        #     manning_sheet_qs
        #     .values('section', 'code', 'style')
        #     .annotate(total_planned_qty=Sum('allocated_capacity'))
        # )

        # # Find the minimum value per section (including all matching records)
        # min_entries = {}

        # for item in manning_sheet_target:
        #     key = (item['section'], item['style'])  # tuple as key
        #     qty = item['total_planned_qty']
            
        #     if key not in min_entries or qty < min_entries[key]['total_planned_qty']:
        #         min_entries[key] = item  # Keep only one item with min qty

        # # Convert result to list
        # min_entries_list = list(min_entries.values())

        # # Aggregate total_planned_qty per section
        # section_summary = defaultdict(float)

        # for item in min_entries_list:
        #     section_summary[item['section']] += item['total_planned_qty']

        # # Convert to list of dicts if needed
        # result = [{'section': sec, 'total_planned_qty': qty} for sec, qty in section_summary.items()]

        # predicted_production = update_sections(result, sections)

        # # First, find if any non-Assembly section has zero quantity
        # non_assembly_zero = any(
        #     item['section'] != 'Assembly' and item['total_planned_qty'] == 0.0
        #     for item in predicted_production
        # )
        # # If condition met, directly update Assembly section in same loop
        # if non_assembly_zero:
        #     for item in predicted_production:
        #         if item['section'] == 'Assembly':
        #             item['total_planned_qty'] = 0.0
        #             break

        # Added below snippet to fetch lowest predicted qty from 6 sections when selected single line
        # ----------------------------------------------------------------------------------------- #
        # min_quantities = [item['total_planned_qty'] for item in predicted_production]
        # if all(q == min_quantities[0] for q in min_quantities):
        #     # All values are the same → return only Assembly
        #     predicted_production_updated = [item for item in predicted_production if item['section'] == 'Assembly']
        # else:
        #     # Return the item with the lowest total_planned_qty
        #     min_item = min(predicted_production, key=lambda x: x['total_planned_qty'])
        #     predicted_production_updated = [min_item]
        
        # predicted_production = predicted_production_updated
        # ----------------------------------------------------------------------------------------- #


        # # Special handling for "all" lines case
        # if line_no.lower() == "all":
        #     # First calculate individual line predictions
        #     all_line_predictions = {}
        #     for line_index in range(1, 11):
        #         individual_line = f"line {line_index}"
        #         # Call recursively but don't return, just store results
        #         response_data = get_dday_actual_vs_planned_data(line_no=individual_line, today=today)
        #         response_data = response_data.data
                
        #         # If the response is valid, extract the prediction data
        #         if isinstance(response_data, tuple):
        #             continue  # Skip invalid responses
                
        #         if 'data' in response_data and 'Target data' in response_data['data']:
        #             prediction_data = response_data['data']['Target data'][0]['predicted_production']
        #             # Store by line number for aggregation
        #             all_line_predictions[individual_line] = prediction_data

        #     # 1. Accumulate totals per section
        #     section_totals = defaultdict(float)

        #     for sections in all_line_predictions.values():
        #         for item in sections:
        #             section_totals[item["section"]] += item["total_planned_qty"]

        #     # 2. Convert to desired list-of-dict format
        #     predicted_production = [{"section": section, "total_planned_qty": qty} for section, qty in section_totals.items()]

    #     dday_filter = Q()
    #     if line_no.lower() != 'all':
    #         dday_filter = Q(line=line_no.title())
    #     dday_df = pd.DataFrame(list(DDayData.objects.filter(dday_filter).values()))
    #     if dday_df.empty:
    #         predicted_data = 0
    #     else:
    #         predicted_value = fetchMaxQtyDday(dday_df)
    #         predicted_data = predicted_value['sum_allocated_capacity'].sum()
    #     predicted_production = [{"section": "Assembly", "total_planned_qty": predicted_data}]

    #     production_data = [{
    #         "production_target": production_target,
    #         "predicted_production": predicted_production,
    #         # "absenteeism_percentage_by_section": absenteeism_percentage_by_section
    #     }]

    #     prediction_response = {
    #         'Target data': production_data
    #     }
    #     return success_response(message='Data fetched successfully', data=prediction_response, status=status.HTTP_200_OK)

    # except Exception as e:
    #     print(f"Error in prepare_prediction_data: {str(e)}")
    #     return error_response(error=f"Unknown error: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                            # <--------------------Kavya code 29-Aug-2025------------------>  
  

# def get_dday_actual_vs_planned_data(line_no, today, section=None, operation=None, operation_code=None):
#     """
#     Daily target vs predicted production.

#     - target_planned_qty = SUM(planned_qty) for the line & date
#     - predicted_production = MIN over (SUM(allocated_capacity) per code)
#     """
#     try:
#         def get_data_for_line(line: str) -> dict:
#             """Fetch target and predicted data for a single line."""

#             # --- 1. Target planned qty ---
#             lp_filter = {'planned_dates': today, 'line': line}
#             total_planned_qty = (
#                 LoadingPlan.objects
#                 .filter(**lp_filter)
#                 .aggregate(total_planned_qty=Sum('planned_qty'))
#             )['total_planned_qty'] or 0

#             # --- 2. Predicted production ---
#             msd_filter = {'line': line}
#             manning_records = DDayData.objects.filter(**msd_filter)
#             manning_sheet_data = manning_records.filter(allocated_capacity__gt=0)

#             predicted_production = 0
#             if manning_sheet_data.exists():
#                 code_sums = (
#                     manning_sheet_data
#                     .values('code')
#                     .annotate(total_allocated=Sum('allocated_capacity'))
#                     .order_by('total_allocated')
#                 )
#                 if code_sums:
#                     predicted_production = code_sums.first()['total_allocated']

#             return {
#                 'line': line,
#                 'target_planned_qty': float(total_planned_qty),
#                 'predicted_production': float(predicted_production)
#             }

#         is_all_lines = str(line_no).lower() == 'all'

#         if is_all_lines:
#             # --- Collect all lines ---
#             unique_lines = (
#                 ManningSheetData.objects
#                 .filter(planned_dates=today)
#                 .values_list('line', flat=True)
#                 .distinct()
#             )

#             # Calculate totals across all lines
#             total_target = 0
#             total_predicted = 0

#             for line in unique_lines:
#                 data = get_data_for_line(line)
#                 total_target += data['target_planned_qty']
#                 total_predicted += data['predicted_production']

#             response_data = {
#                "Target data": {
#                     "production_target": total_target,
#                     "predicted_production": total_predicted
#                 }
#             }

#         else:
#             # --- Just this line ---
#             response_data = {
#                 "Target data": [get_data_for_line(line_no)]
#             }

#         return success_response(
#             message="Data fetched successfully",
#             data=response_data,
#             status=status.HTTP_200_OK
#         )

#     except Exception as e:
#         print(f"[ERROR] get_dday_actual_vs_planned_data: {str(e)}")
#         return error_response(
#             error=f"Unknown error: {str(e)}",
#             status=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )

####################kavya style update 24-09-2025##########################

def get_dday_actual_vs_planned_data(line_no, today, section=None, operation=None, operation_code=None):
    """
    Daily target vs predicted production.
 
    - target_planned_qty = SUM(planned_qty) for the line & date
    - predicted_production = SUM of minimum allocated capacity per style
    """
    try:
        def get_data_for_line(line: str) -> dict:
            """Fetch target and predicted data for a single line."""
 
            # --- 1. Target planned qty ---
            lp_filter = {'planned_dates': today, 'line': line}
            total_planned_qty = (
                LoadingPlan.objects
                .filter(**lp_filter)
                .aggregate(total_planned_qty=Sum('planned_qty'))
            )['total_planned_qty'] or 0
 
            # --- 2. Predicted production - NEW LOGIC ---
            # Get minimum allocated capacity per style along with operation code
            style_minimums = (
                DDayData.objects
                .filter(line=line, allocated_capacity__gt=0)
                .values('style', 'code')  # Group by style and code
                .annotate(total_allocated=Sum('allocated_capacity'))
                .order_by('style', 'total_allocated')
            )
           
            # For each style, get the minimum allocated capacity (first record after ordering)
            style_min_dict = {}
            for item in style_minimums:
                style = item['style']
                # Only keep the minimum for each style (first occurrence due to ordering)
                if style not in style_min_dict:
                    style_min_dict[style] = {
                        'code': item['code'],
                        'min_allocated': item['total_allocated']
                    }
           
            # Sum all the style minimums to get total predicted production
            predicted_production = sum(item['min_allocated'] for item in style_min_dict.values())
           
            # Prepare style-wise breakdown for debugging/information
            style_breakdown = [
                {
                    'style': style,
                    'code': data['code'],
                    'style_minimum': data['min_allocated']
                }
                for style, data in style_min_dict.items()
            ]
 
            return {
                'line': line,
                'target_planned_qty': float(total_planned_qty),
                'predicted_production': float(predicted_production),
                'style_breakdown': style_breakdown  # Optional: include breakdown in response
            }
 
        is_all_lines = str(line_no).lower() == 'all'
 
        if is_all_lines:
            # --- Collect all lines ---
            unique_lines = (
                ManningSheetData.objects
                .filter(planned_dates=today)
                .values_list('line', flat=True)
                .distinct()
            )
 
            # Calculate totals across all lines
            total_target = 0
            total_predicted = 0
            all_lines_data = []
 
            for line in unique_lines:
                data = get_data_for_line(line)
                total_target += data['target_planned_qty']
                total_predicted += data['predicted_production']
                all_lines_data.append(data)
 
            response_data = {
               "Target data": {
                    "production_target": total_target,
                    "predicted_production": total_predicted,
                    "line_wise_breakdown": all_lines_data  # Optional: include detailed breakdown
                }
            }
 
        else:
            # --- Just this line ---
            line_data = get_data_for_line(line_no)
            response_data = {
                "Target data": {
                    "line": line_data['line'],
                    "production_target": line_data['target_planned_qty'],
                    "predicted_production": line_data['predicted_production'],
                    "style_breakdown": line_data['style_breakdown']  # Include style breakdown
                }
            }
 
        return success_response(
            message="Data fetched successfully",
            data=response_data,
            status=status.HTTP_200_OK
        )
 
    except Exception as e:
        logger.info(f"[ERROR] get_dday_actual_vs_planned_data: {str(e)}")
        return error_response(
            error=f"Unknown error: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# To fetch only Attendance Data
@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def get_attendance_data(request):
    """
    Retrieve attendance statistics with a single highly optimized database query
    using Django's conditional expressions.
    """
    try:
        # Get and validate line parameter
        line_no = request.query_params.get('line', '').strip().title()
        
        if not line_no:
            return error_response(error='"line" is required.', status=status.HTTP_400_BAD_REQUEST)
        
        # Fast validation with set lookup
        if line_no not in {f'Line {i}' for i in range(1, 11)} | {'All'}:
            return error_response(
                error='Enter a valid line number (Valid Formats: "Line 1" or "line 3" or "LINE 5" or "all")',
                status=status.HTTP_400_BAD_REQUEST
            )

        # Calculate dates
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)

        attendance_data = fetch_attendance_data(line_no, today, yesterday)

        return success_response(
            data=attendance_data["data"], 
            message=attendance_data["message"], 
            status=attendance_data["status"]
        )

    except Exception as e:
        return error_response(
            error="An unexpected error occurred. Please try again later.",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


#<--------------Vatsals code 05-Sep-2025------------------>

# To download excel file or via email
# @api_view(['POST'])
# @authentication_classes([MultiSessionTokenAuthentication])
# @permission_classes([IsAuthenticated])
# def download_manning_attendance_data(request):
#     """
#     Retrieve attendance statistics with a single highly optimized database query
#     using Django's conditional expressions and fetch dday data and export it as excel or via email
#     """
#     try:
#         # Get and validate line parameter
#         line_no = request.query_params.get('line', '').strip().title()
        
#         if not line_no:
#             return error_response(error='"line" is required.', status=status.HTTP_400_BAD_REQUEST)
        
#         # Fast validation with set lookup
#         if line_no not in {f'Line {i}' for i in range(1, 11)} | {'All'}:
#             return error_response(
#                 error='Enter a valid line number (Valid Formats: "Line 1" or "line 3" or "LINE 5" or "all")',
#                 status=status.HTTP_400_BAD_REQUEST
#             )
        
#         # Calculate dates
#         today = datetime.now().date()
#         yesterday = today - timedelta(days=1)

#         dday_data = fetch_dday_data(line_no)
#         attendance_data = fetch_attendance_data(line_no, today, yesterday)

#         prediction_response = get_dday_actual_vs_planned_data(line_no=line_no, today=today)
#         preditction_data = prediction_response.data['data']['Target data']
#         production_target = 0.0
#         predicted_production = 0.0
#         for item in preditction_data:
#             production_target = item.get('production_target', [{}])[0].get('total_planned_qty', 0.0)
#             predicted_production = item.get('predicted_production', [{}])[0].get('total_planned_qty', 0.0)
#         unallocated_emp_data = get_unallocated_employees_count(line_no=line_no)

#         type_of_export = request.query_params.get('type', '').strip().lower()
#         email = request.query_params.get('email', '').strip()

#         df = pd.DataFrame(dday_data["data"]["records"])
#         df.drop(columns=['Dday_ID', 'WIP Qty'], inplace=True)

#         # Generate Excel file in memory
#         output = BytesIO()
#         with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
#             df.to_excel(writer, sheet_name="Sheet1", startrow=9, index=False)

#             # Get the worksheet AFTER writing the DataFrame
#             worksheet = writer.sheets["Sheet1"]
#             workbook = writer.book
#             bold_format = workbook.add_format({'bold': True})  # Bold format for headers

#             # Write attendance data at the top with proper alignment
#             worksheet.write(0, 0, "Line number", bold_format)
#             worksheet.write(0, 1, line_no)

#             worksheet.write(1, 0, "Planned Attendance", bold_format)
#             worksheet.write(1, 1, attendance_data['data']['attendance_data']['Planned Attendance'])

#             worksheet.write(2, 0, "Present", bold_format)
#             worksheet.write(2, 1, attendance_data['data']['attendance_data']['Present'])

#             worksheet.write(3, 0, "Absent", bold_format)
#             worksheet.write(3, 1, attendance_data['data']['attendance_data']['Absent'])

#             worksheet.write(4, 0, "Unallocated Operators", bold_format)
#             worksheet.write(4, 1, unallocated_emp_data)

#             worksheet.write(5, 0, "Production Target", bold_format)
#             worksheet.write(5, 1, production_target)

#             worksheet.write(6, 0, "Planned Qty", bold_format)
#             worksheet.write(6, 1, predicted_production)

#             # Adjust column width for A and B (0 and 1)
#             worksheet.set_column(0, 0, 25)  # Column A (Labels)
#             worksheet.set_column(1, 1, 15)  # Column B (Values)

#             # Adjust column widths dynamically based on data
#             for i, col in enumerate(df.columns):
#                 if col != 'Factory':
#                     max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2  # Adjust width
#                     worksheet.set_column(i, i, max_len, workbook.add_format({'text_wrap': False}))  # Disable text wrapping

#             # Handle "Preferred Employees" column formatting
#             preferred_col_index = list(df.columns).index("Preferred Employees")
#             worksheet.set_column(preferred_col_index, preferred_col_index, 30)  # Fixed width

#             # Create a custom format to prevent text overflow in "Preferred Employees"
#             truncate_format = workbook.add_format({
#                 'text_wrap': False,
#                 'num_format': '@'  # Text format
#             })

#             # Apply format to all rows in "Preferred Employees" column
#             for row_num in range(10, 10 + len(df)):  # Since headers are at row 9, data starts at 10
#                 worksheet.write(row_num, preferred_col_index, df["Preferred Employees"].iloc[row_num - 10], truncate_format)

#         output.seek(0)

#         if type_of_export == 'email':
#             if not email:
#                 return error_response(error="Email address is required.", status=status.HTTP_400_BAD_REQUEST)

#             subject = "Downlaod D-Day Manning Data File"
#             file_name = f"Dday_Manning_data_{line_no}.xlsx"
#             file_data = output  # Pass the BytesIO object directly
#             content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

#             # Call the send_email function
#             email_body = send_email(email, file_data, subject, content_type, file_name=file_name)

#             if not email_body:
#                 return error_response(
#                     error="Error sending email, Invalid email address.",
#                     status=status.HTTP_404_NOT_FOUND
#                 )

#             return success_response(
#                 message=f"Email sent successfully to {email}.",
#                 data={"message": "File attached to the email."},
#                 status=status.HTTP_200_OK
#             )

#         elif type_of_export == 'excel':
#             # Return the file as a downloadable response
#             response = HttpResponse(
#                 output.getvalue(),
#                 content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
#             )
#             response["Content-Disposition"] = f'attachment; filename="Dday_Manning_data_{line_no}.xlsx"'
#             return response
#         else:
#             return error_response(error='Type should be "email" or "excel".', status=status.HTTP_400_BAD_REQUEST)

#     except Exception as e:
#         return error_response(
#             error="An unexpected error occurred. Please try again later.",
#             status=status.HTTP_500_INTERNAL_SERVER_ERROR
#         )

#<--------------Kavya code 05-sep-2025------------------>
# To download excel file or via email
@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def download_manning_attendance_data(request):
    """
    Retrieve attendance statistics with a single highly optimized database query
    using Django's conditional expressions and fetch dday data and export it as excel or via email
    """
    try:
        # Get and validate line parameter
        line_no = request.query_params.get('line', '').strip().title()
        if not line_no:
            return error_response(error='"line" is required.', status=status.HTTP_400_BAD_REQUEST)
        # Fast validation with set lookup
        if line_no not in {f'Line {i}' for i in range(1, 11)} | {'All'}:
            return error_response(
                error='Enter a valid line number (Valid Formats: "Line 1" or "line 3" or "LINE 5" or "all")',
                status=status.HTTP_400_BAD_REQUEST
            )
        # Calculate dates
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        dday_data = fetch_dday_data(line_no)
        attendance_data = fetch_attendance_data(line_no, today, yesterday)
        prediction_response = get_dday_actual_vs_planned_data(line_no=line_no, today=today)
        prediction_data = prediction_response.data['data']['Target data']
        # FIXED: Correct structure based on get_dday_actual_vs_planned_data function
        if line_no == 'All':
            # For "All" lines: {"Target data": {"production_target": x, "predicted_production": y, "line_wise_breakdown": [...]}}
            production_target = prediction_data.get('production_target', 0.0)
            predicted_production = prediction_data.get('predicted_production', 0.0)
        else:
            # For single line: {"Target data": {"line": "Line X", "production_target": x, "predicted_production": y, "style_breakdown": [...]}}
            production_target = prediction_data.get('production_target', 0.0)
            predicted_production = prediction_data.get('predicted_production', 0.0)
        unallocated_emp_data = get_unallocated_employees_count(line_no=line_no)
        type_of_export = request.query_params.get('type', '').strip().lower()
        email = request.query_params.get('email', '').strip()
        df = pd.DataFrame(dday_data["data"]["records"])
        df.drop(columns=['Dday_ID', 'WIP Qty'], inplace=True)
        # Generate Excel file in memory
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name="Sheet1", startrow=9, index=False)
            # Get the worksheet AFTER writing the DataFrame
            worksheet = writer.sheets["Sheet1"]
            workbook = writer.book
            bold_format = workbook.add_format({'bold': True})  # Bold format for headers
            # Write attendance data at the top with proper alignment
            worksheet.write(0, 0, "Line number", bold_format)
            worksheet.write(0, 1, line_no)
            worksheet.write(1, 0, "Planned Attendance", bold_format)
            worksheet.write(1, 1, attendance_data['data']['attendance_data']['Planned Attendance'])
            worksheet.write(2, 0, "Present", bold_format)
            worksheet.write(2, 1, attendance_data['data']['attendance_data']['Present'])
            worksheet.write(3, 0, "Absent", bold_format)
            worksheet.write(3, 1, attendance_data['data']['attendance_data']['Absent'])
            worksheet.write(4, 0, "Unallocated Operators", bold_format)
            worksheet.write(4, 1, unallocated_emp_data)
            worksheet.write(5, 0, "Production Target", bold_format)
            worksheet.write(5, 1, production_target)
            worksheet.write(6, 0, "Predicted Production", bold_format)  # Changed label for clarity
            worksheet.write(6, 1, predicted_production)
            # Adjust column width for A and B (0 and 1)
            worksheet.set_column(0, 0, 25)  # Column A (Labels)
            worksheet.set_column(1, 1, 15)  # Column B (Values)
            # Adjust column widths dynamically based on data
            for i, col in enumerate(df.columns):
                if col != 'Factory':
                    max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2  # Adjust width
                    worksheet.set_column(i, i, max_len, workbook.add_format({'text_wrap': False}))  # Disable text wrapping
            # Handle "Preferred Employees" column formatting
            preferred_col_index = list(df.columns).index("Preferred Employees")
            worksheet.set_column(preferred_col_index, preferred_col_index, 30)  # Fixed width
            # Create a custom format to prevent text overflow in "Preferred Employees"
            truncate_format = workbook.add_format({
                'text_wrap': False,
                'num_format': '@'  # Text format
            })
            # Apply format to all rows in "Preferred Employees" column
            for row_num in range(10, 10 + len(df)):  # Since headers are at row 9, data starts at 10
                worksheet.write(row_num, preferred_col_index, df["Preferred Employees"].iloc[row_num - 10], truncate_format)
        output.seek(0)
        if type_of_export == 'email':
            if not email:
                return error_response(error="Email address is required.", status=status.HTTP_400_BAD_REQUEST)
            subject = "Download D-Day Manning Data File"
            file_name = f"Dday_Manning_data_{line_no}.xlsx"
            file_data = output  # Pass the BytesIO object directly
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            # Call the send_email function
            email_body = send_email(email, file_data, subject, content_type, file_name=file_name)
            if not email_body:
                return error_response(
                    error="Error sending email, Invalid email address.",
                    status=status.HTTP_404_NOT_FOUND
                )
            return success_response(
                message=f"Email sent successfully to {email}.",
                data={"message": "File attached to the email."},
                status=status.HTTP_200_OK
            )
        elif type_of_export == 'excel':
            # Return the file as a downloadable response
            response = HttpResponse(
                output.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            response["Content-Disposition"] = f'attachment; filename="Dday_Manning_data_{line_no}.xlsx"'
            return response
        else:
            return error_response(error='Type should be "email" or "excel".', status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return error_response(
            error="An unexpected error occurred. Please try again later.",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def generate_emp_fact(request):
    try:
        return run_generate_emp_fact()  # Call the function without needing a request
    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)


# Function to generate the EMP_FACT and can be used in a view as well as in a scheduler
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
    

# Function to use in api as well as scheduler to generate manning sheets data at 8:00 AM
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


# Function to use in api as well as scheduler to generate dday data at 08:50 AM, 12:45 PM and 5:30 PM
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
def get_user_notifications(request):
    """
    Get all notifications for the authenticated user from the last 7 days.
    Notifications are ordered by creation time (newest first).
    Optional query parameter 'unread_only=true' to get only unread notifications.
    """
    try:        
        # Calculate date 7 days ago
        seven_days_ago = datetime.now() - timedelta(days=7)
        
        # Check if we should only return unread notifications
        unread_only = request.query_params.get('unread_only', '').lower() == 'true'
        
        # Create base filter dictionary
        base_filter = {
            'user': request.user,
            'created_at__gte': seven_days_ago
        }
        
        # Add unread filter if requested
        if unread_only:
            base_filter['is_read'] = False
        
        # Get notifications using the filter dictionary
        notifications = PushNotification.objects.filter(**base_filter).order_by('-created_at')
        
        # Convert to list of dictionaries
        notification_list = []
        for notification in notifications:
            # Convert created_at to IST
            created_at_ist = timezone.localtime(notification.created_at, pytz.timezone('Asia/Kolkata'))
            created_at_ist = created_at_ist.strftime('%B %d, %Y %I:%M %p')
            
            notification_list.append({
                'id': notification.id,
                'type': notification.get_notification_type_display(),
                'title': notification.title,
                'message': notification.message,
                'created_at': created_at_ist,
                'is_read': notification.is_read,
                'data': notification.data
            })
        
        return success_response(
            message="Notifications retrieved successfully",
            data={'notifications': notification_list},
            status=status.HTTP_200_OK
        )
    
    except Exception as e:
        return error_response(
            error=f"Failed to retrieve notifications: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# Function to download a file attached to a specific notification for the authenticated user
@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def download_notification_file(request):
    """
    Download a file attached to a specific notification for the authenticated user.

    Request Parameters (query):
        - notification_id (int): ID of the notification containing the file.

    Behavior:
        - Verifies the presence of notification_id.
        - Retrieves the corresponding PushNotification for the logged-in user.
        - Checks if the notification contains a 'fileName' in its data field.
        - Checks if the corresponding file exists in the 'exports' directory.
        - Returns the file as a downloadable response if found.

    Returns:
        - 200 OK with the file if everything is valid.
        - 400 if notification_id is missing.
        - 404 if the notification, data, or fileName is not found.
        - 500 on unexpected server error.
    """
    try:
        notification_id = request.query_params.get('notification_id', None)

        if not notification_id:
            return error_response(
                error="Notification ID is required",
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create base filter dictionary
        base_filter = {
            'user': request.user,
            'id': int(notification_id)
        }
        
        # Get notification object using the filter dictionary
        notification = PushNotification.objects.get(**base_filter)

        if not notification:
            return error_response(
                error="Notification not found",
                status=status.HTTP_404_NOT_FOUND
            )

        if not notification.data:
            return error_response(
                error="No data available for this notification",
                status=status.HTTP_404_NOT_FOUND
            )
        
        if "fileName" not in notification.data:
            return error_response(
                error="File name not found in notification data",
                status=status.HTTP_404_NOT_FOUND
            )
        file_name = notification.data["fileName"]
        file_path = os.path.join("exports", file_name)

        # Check if the file exists
        if not os.path.exists(file_path):
            return error_response(
                error="File not found",
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Open the file and return it as a response for download
        response = FileResponse(open(file_path, 'rb'), as_attachment=True, filename=file_name)
        return response

    except Exception as e:
        return error_response(
            error=f"Failed to retrieve notification's data: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )



@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def mark_notification_read(request):
    """
    Mark a notification as read.
    Requires 'notification_id' in the request body to mark a specific notification as read.
    Optional 'mark_all=true' to mark all user's notifications as read.

    provide any one of the above in the request body.
    """
    try:
        # Check if we should mark all notifications as read
        mark_all = request.data.get('mark_all', False)
        
        if mark_all:
            # Create filter for marking all unread notifications
            unread_filter = {
                'user': request.user,
                'is_read': False
            }
            
            # Mark all notifications for this user as read
            with transaction.atomic():
                PushNotification.objects.filter(**unread_filter).update(is_read=True)
            
            return success_response(
                message="All notifications marked as read",
                status=status.HTTP_200_OK
            )
        
        # Get notification ID from request
        notification_id = request.data.get('notification_id')
        
        if not notification_id:
            return error_response(
                error="notification_id is required",
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create filter for specific notification
        notification_filter = {
            'id': notification_id,
            'user': request.user
        }
        
        # Update notification in a single database call
        updated_count = PushNotification.objects.filter(**notification_filter).update(is_read=True)
        
        if updated_count == 0:
            return error_response(
                error="Notification not found",
                status=status.HTTP_404_NOT_FOUND
            )
        
        return success_response(
            message="Notification marked as read",
            status=status.HTTP_200_OK
        )
    
    except Exception as e:
        return error_response(
            error=f"Failed to mark notification as read: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def create_test_notification(request):
    """
    Create test notifications with different dates to test the 7-day filter.
    Creates 3 notifications:
    1. Today's notification
    2. 5 days old notification
    3. 10 days old notification (should not appear in 7-day filter)
    """
    try:
        
        # Create today's notification
        today_notification = PushNotification.objects.create(
            user=request.user,
            title="Test Notification - Today",
            message="This is a test notification created today",
            created_at=datetime.now()
        )
        
        # Create 5 days old notification
        five_days_ago = datetime.now() - timedelta(days=5)
        five_days_notification = PushNotification.objects.create(
            user=request.user,
            title="Test Notification - 5 Days Ago",
            message="This is a test notification created 5 days ago",
            created_at=five_days_ago
        )
        
        # Create 10 days old notification (should not appear in 7-day filter)
        ten_days_ago = datetime.now() - timedelta(days=10)
        ten_days_notification = PushNotification.objects.create(
            user=request.user,
            title="Test Notification - 10 Days Ago",
            message="This is a test notification created 10 days ago",
            created_at=ten_days_ago
        )
        
        return success_response(
            message="Test notifications created successfully",
            data={
                "notifications": [
                    {
                        "id": today_notification.id,
                        "title": today_notification.title,
                        "created_at": today_notification.created_at
                    },
                    {
                        "id": five_days_notification.id,
                        "title": five_days_notification.title,
                        "created_at": five_days_notification.created_at
                    },
                    {
                        "id": ten_days_notification.id,
                        "title": ten_days_notification.title,
                        "created_at": ten_days_notification.created_at
                    }
                ]
            },
            status=status.HTTP_201_CREATED
        )
        
    except Exception as e:
        return error_response(
            error=f"Failed to create test notifications: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )



@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def generate_style_ob(request):
    try:
        viaAPI=True
        return run_generate_style_ob(viaAPI)  # Call the function without needing a request
    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)
    


# Function to generate the EMP_FACT and can be used in a view as well as in a scheduler
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


# Function to fetch employee attendance from RockHR API
@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def fetch_emp_attendance_rockhr(request):
    try:
        return fetch_and_transform_emp_attendance()  # Call the function without needing a request
    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)



# Function to fetch active employee details from RockHR API
@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def fetch_emp_details_rockhr(request):
    try:
        return fetch_and_transform_empdetails()  # Call the function without needing a request
    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)





# Function to fetch employee attendance from RockHR API
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
        response = requests.post(soap_url, data=soap_body, headers=headers, verify=False)

        # Parse the XML response
        root = ET.fromstring(response.text)
        namespace = {'soap': 'http://schemas.xmlsoap.org/soap/envelope/', 'ns': 'http://tempuri.org/'}
        result = root.find('.//ns:EmpAttdResult', namespaces=namespace)

        if result is None:
            return error_response(error=f"No data found for employee attendance api for {today}", status=status.HTTP_404_NOT_FOUND)  

        # Convert JSON string to Python list
        data_list = json.loads(result.text)

        # Create DataFrame from recieved data
        try:
            df_attendance = pd.DataFrame(data_list)
        except Exception as e:
            return error_response(
                error=f"Error creating DataFrame: {str(e)}",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Convert values that are not 'A', 'P', 'AP', or 'PA' to 'A'
        df_attendance['ATTD_STATUS'] = df_attendance['ATTD_STATUS'].apply(lambda x: 'A' if x not in ['A', 'P', 'AP', 'PA'] else x)

        current_time = datetime.now()

        def get_attendance_status(row):
            status = row.get('ATTD_STATUS')
            intime = row.get('INTIME')
            outtime = row.get('OUTTIME')

            if status == 'PA':
                return 'A' if outtime else 'P'
            elif status == 'AP':
                return 'P' if intime else 'A'
            elif status in ['P', 'A']:
                return status
            else:
                return 'A'

        # Apply the function to each row to determine Attendance_Status
        df_attendance['status'] = df_attendance.apply(get_attendance_status, axis=1)

        df_attendance.rename(columns={'LOGDATE': 'attendance_date', 'EMPCODE': 'employee_id', 'EMPNAME': 'employee_name'}, inplace=True)

        df_attendance['attendance_date'] = pd.to_datetime(df_attendance['attendance_date']).dt.date

        df_attendance['last_updated'] = pd.to_datetime(df_attendance['attendance_date']).dt.date

        # Convert INTIME and OUTTIME to datetime format
        df_attendance['INTIME'] = pd.to_datetime(df_attendance['INTIME'], format="%d-%b-%Y %H:%M:%S", errors='coerce')
        df_attendance['OUTTIME'] = pd.to_datetime(df_attendance['OUTTIME'], format="%d-%b-%Y %H:%M:%S", errors='coerce')


        # Function to fetch time
        def fetch_time(row):
            if pd.notnull(row['OUTTIME']):
                return row['OUTTIME'].strftime("%H:%M:%S")
            elif pd.notnull(row['INTIME']):
                return row['INTIME'].strftime("%H:%M:%S")
            return None

        # Apply the function to the dataframe
        df_attendance['last_updated'] = df_attendance.apply(fetch_time, axis=1)

        # df_attendance.drop(columns=["ATTD_STATUS", "INTIME", "OUTTIME"], inplace=True)

        df_attendance = df_attendance.applymap(lambda x: x.capitalize() if isinstance(x, str) else x)


        active_employees_queryset = ActiveEmployees.objects.all().values()
        df_active_employees = pd.DataFrame(list(active_employees_queryset))
        df_active_employees.rename(columns={'employee_id': 'Emp No', 'employee_name': 'Employee name', 'line': 'Line', 'section': 'Section', 'designation': 'Designation'}, inplace=True)
        
        # Convert both columns to integer type (safe conversion)
        df_attendance['employee_id'] = pd.to_numeric(df_attendance['employee_id'], errors='coerce').astype('Int64')
        df_active_employees['Emp No'] = pd.to_numeric(df_active_employees['Emp No'], errors='coerce').astype('Int64')

        # Filter df_attendance to keep only matching employee_ids
        df_attendance_filtered = df_attendance[df_attendance['employee_id'].isin(df_active_employees['Emp No'])]

        # Now safe to merge
        merged_df = pd.merge(df_attendance_filtered, df_active_employees, left_on='employee_id', right_on='Emp No', how='left')
        updated_df = merged_df[['attendance_date', 'employee_id', 'employee_name', 'ATTD_STATUS', 'INTIME', 'OUTTIME', 'status_x']]
        updated_df.rename(columns={'status_x': 'status'}, inplace=True)
        updated_df = updated_df.applymap(lambda x: x.upper() if isinstance(x, str) else x)
        updated_df.to_csv("csv_files/attendance.csv", index=False)


        merged_df[["factory", "floor"]] = pd.DataFrame(merged_df["Line"].apply(map_factory_floor).tolist(), index=merged_df.index)

        # Prepare all data as a list of dictionaries first (faster than processing row by row)
        data_dicts = []
        # Convert DataFrame to list of dicts (much faster than row iteration)
        for _, row in merged_df.iterrows():
            data_dict = {
                'attendance_date': row['attendance_date'],
                'employee_id': row['employee_id'],
                'employee_name': row['employee_name'],
                'status': row['status_x'], # status_x is the status column from df_attendance
                'last_updated': row['last_updated'] if pd.notnull(row['last_updated']) else current_time.strftime("%H:%M:%S"),
                'early_departure': False,
                'line': row['Line'] if pd.notnull(row['Line']) else "N/A", # Coming from df_active_employees
                'factory': row['factory'] if pd.notnull(row['factory']) else "N/A", # Coming from df_active_employees
                'floor': row['floor'] if pd.notnull(row['floor']) else "N/A", # Coming from df_active_employees
                'section': row['Section'] if pd.notnull(row['Section']) else "N/A", # Coming from df_active_employees
                'type': "N/A",
            }
            data_dicts.append(data_dict)

        # Delete data for today's date before inserting new data
        AttendanceMaster.objects.filter(attendance_date=current_time.date()).delete()

        # Process in chunks to avoid memory issues
        for i in range(0, len(data_dicts), CHUNK_SIZE):
            chunk_dicts = data_dicts[i:i + CHUNK_SIZE]
            
            # Convert dictionaries to model instances
            model_instances = [AttendanceMaster(**d) for d in chunk_dicts]
            
            # Use a single transaction for the chunk
            with transaction.atomic():
                AttendanceMaster.objects.bulk_create(model_instances)

        if run_type is not None and run_type == "noon":
            raw_data = []
            for _, row in merged_df.iterrows():
                if row['status_x'] == 'A':
                    raw_data.append({
                        'date': row['attendance_date'],
                        'empcode': row['employee_id'],
                        'name': row['employee_name'],
                        'attendance': row['status_x'], # status_x is the status column from df_attendance
                        'department': row['Line'].upper() if pd.notnull(row['Line']) else "N/A", # Coming from df_active_employees
                        'section': row['Section'].upper() if pd.notnull(row['Section']) else "N/A", # Coming from df_active_employees
                    })
            # Convert to DataFrame
            df_data = pd.DataFrame(raw_data)

            # Drop duplicates based on 'empcode' and 'date'
            df_data = df_data.drop_duplicates(subset=['date', 'empcode', 'name', 'department', 'section', 'attendance'])

            # Convert back to list of dicts
            absenteeism_data = df_data.to_dict(orient='records')

            # # Delete the data that is less than the date 3 years agp
            # cutoff_date = date.today().replace(year=date.today().year - 3)
            # PredictionData.objects.filter(date__lt=cutoff_date).delete()

            # Process in chunks
            for i in range(0, len(absenteeism_data), CHUNK_SIZE):
                chunk_dicts = absenteeism_data[i:i + CHUNK_SIZE]
                model_instances = [PredictionData(**d) for d in chunk_dicts]
                with transaction.atomic():
                    PredictionData.objects.bulk_create(model_instances, ignore_conflicts=True)

        return success_response(message="Data processed and uploaded to Database", data=data_list, status=status.HTTP_200_OK)
    except Exception as e:
        return error_response(error=f"Error in RockHR API: {str(e)}", status=status.HTTP_400_BAD_REQUEST)




# Function to fetch active employee details from RockHR API
def fetch_and_transform_empdetails():
    try:
        # Get today's date
        current_date = datetime.now().date()
        # Check if the filter date is a working day and not a holiday
        isWorkingDay, reason = is_allowed_working_day(current_date)
        if not isWorkingDay:
            return error_response(error=f'Skipping for {current_date} as it is {reason}', status=status.HTTP_400_BAD_REQUEST)

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
        response = requests.post(soap_url, data=soap_body, headers=headers, verify=False)

        # Parse the XML response
        root = ET.fromstring(response.text)
        namespace = {'soap': 'http://schemas.xmlsoap.org/soap/envelope/', 'ns': 'http://tempuri.org/'}
        result = root.find('.//ns:EmpDetailsResult', namespaces=namespace)

        if result is None:
            return error_response(error="No data found for employee details api.", status=status.HTTP_404_NOT_FOUND)  

        # Convert JSON string to Python list
        data_list = json.loads(result.text)

        df = pd.DataFrame(data_list)

        # Create DataFrame from recieved data
        try:
            df = pd.DataFrame(data_list)
        except Exception as e:
            return error_response(
                error=f"Error creating DataFrame: {str(e)}",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Make all values lowercase
        df = df.applymap(lambda x: x.lower() if isinstance(x, str) else x)

        # Allowed values
        allowed_values = ['back', 'collar', 'sleeve', 'cuff', 'front', 'assembly']

        # Keep only rows where 'operation' is in allowed_values
        df = df[df['SECTION_NAME'].isin(allowed_values)]

        # Split "Department" into "Line"
        df["line"] = df["LINE_NAME"].str.extract(r"(?i)^(line \d+)")
        df['machinist'] = df['MACHENIST'] == 'direct machinist'

        # Keeping only Machinists and Floaters employees
        df = df[df['machinist'] == True]
        df = df[df['DESIGNATION'].astype(str).str.lower().isin(['machinist', 'floaters'])]

        df.drop(columns=["LINE_NAME", "EMAIL_ID", "OPERATIONS", "MACHENIST"], inplace=True)  # Drop the original column if needed
        df.rename(columns={"EMPCODE": "employee_id", "EMPLOYEE_NAME": "employee_name", "DESIGNATION": "designation", "SERVICE_YRS": "service_years", "STATUS": "status", "GENDER": "gender", "SECTION_NAME": "section"}, inplace=True)

        df = df.applymap(lambda x: x.capitalize() if isinstance(x, str) else x)
        df.dropna(subset=["line"], inplace=True)  # Drop rows with NaN in "line" column

        # Prepare all data as a list of dictionaries first (faster than processing row by row)
        data_dicts = []
        # Convert DataFrame to list of dicts (much faster than row iteration)
        for _, row in df.iterrows():
            data_dict = {
                'employee_id': row['employee_id'],
                'employee_name': row['employee_name'],
                'line': row['line'],
                'section': row['section'],
                'designation': row['designation'],
                'machinist': row['machinist'],
                'service_years': row['service_years'],
                'status': row['status'],
                'gender': row['gender']
            }
            data_dicts.append(data_dict)

        # Truncate the table before inserting new data
        truncate_table(ActiveEmployees)

        # Process in chunks to avoid memory issues
        for i in range(0, len(data_dicts), CHUNK_SIZE):
            chunk_dicts = data_dicts[i:i + CHUNK_SIZE]
            
            # Convert dictionaries to model instances
            model_instances = [ActiveEmployees(**d) for d in chunk_dicts]
            
            # Use a single transaction for the chunk
            with transaction.atomic():
                ActiveEmployees.objects.bulk_create(model_instances)

        return success_response(message="RockHR Data for Active Employees processed and uploaded to Database", status=status.HTTP_200_OK)
    except Exception as e:
        return error_response(error=f"Error in RockHR API: {str(e)}", status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def get_unallocated_employees(request):
    try:
        line_no = request.query_params.get('line', '').strip()
        forecast_period = request.query_params.get('forecast_period', '').strip()

        if not line_no or not forecast_period:
            return error_response(error='"line" and "forecast_period" are required.', status=status.HTTP_400_BAD_REQUEST)

        try:
            forecast_period = int(forecast_period)
        except ValueError:
            return error_response(error='"forecast_period" must be an integer.', status=status.HTTP_400_BAD_REQUEST)

        today = datetime.today().date()
        date_range = [(today + timedelta(days=i)) for i in range(1, forecast_period + 1)] # This list won't include today's date

        query_filter = {
            'line': line_no.capitalize(),
            'date__in': date_range  
        }
        queryset = UnallocatedEmployees.objects.filter(**query_filter)

        if request.method == 'POST':
            df_unallocated_employees = pd.DataFrame(list(queryset.values()))
            df_unallocated_employees['period'] = forecast_period
            df_unallocated_employees.drop(columns={'id'}, inplace=True)
            df_unallocated_employees.columns = df_unallocated_employees.columns.str.replace('_', ' ').str.upper()
            # Convert timezone-aware datetimes to timezone-naive
            for col in df_unallocated_employees.select_dtypes(include=['datetimetz']).columns:
                df_unallocated_employees[col] = df_unallocated_employees[col].dt.tz_localize(None)
            # Generate Excel file in memory
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_unallocated_employees.to_excel(writer, index=False, sheet_name='Unallocated Employees')

                # Get the workbook and worksheet objects
                # workbook  = writer.book
                worksheet = writer.sheets['Unallocated Employees']

                # Auto-adjust column widths
                for i, col in enumerate(df_unallocated_employees.columns):
                    # Get max length of values in column (including column name)
                    max_len = max(
                        df_unallocated_employees[col].astype(str).map(len).max(),
                        len(col)
                    ) + 2  # Add padding
                    worksheet.set_column(i, i, max_len)

            output.seek(0)
            response = HttpResponse(output.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = 'attachment; filename=unallocated_employees.xlsx'
            return response
    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)



# Function to fetch active employee details from RockHR API
# @api_view(['GET'])
# @authentication_classes([MultiSessionTokenAuthentication])
# @permission_classes([IsAuthenticated])
# def fetch_wip_data(request):
#     try:
#         # lagunaData = {
#         #     "raw_oc_no": "LC/HB/24/13152.7",
#         #     "raw_style": "50469345-H-HANK-kent -C1-214-2",
#         #     "raw_color": "WHITE(10219212-100)",
#         #     "line": "Line 1"
#         # }
#         allDFs = []
#         today = datetime.today().date()
#         manning_queryset = ManningSheetData.objects.filter(planned_dates=today).values()
#         manning_df = pd.DataFrame(list(manning_queryset))
#         distinct_data = manning_queryset.values(
#             'raw_oc_no', 'raw_style', 'raw_color', 'line'
#         ).distinct()
#         columns_to_keep = ['raw_oc_no', 'order_no', 'buyer', 'raw_style', 'line', 'raw_color', 'section', 'op_seq', 'operation', 'code']
#         manning_df = manning_df[columns_to_keep]
#         manning_df.rename(columns={'raw_oc_no': 'oc_no', 'raw_style': 'style', 'raw_color': 'color'}, inplace=True)
#         for item in distinct_data:
#             df = fetch_wip(poRef=item['raw_oc_no'], style=item['raw_style'], color=item['raw_color'], line=item['line'])
#             df['oc_no'] = item['raw_oc_no']
#             df['style'] = item['raw_style']
#             df['color'] = item['raw_color']
#             df['line'] = item['line']
#             allDFs.append(df)

#         allDFs = pd.concat(allDFs, ignore_index=True)

#         if allDFs.empty:
#             message = "Unable to fetch WIP data from OptaFloor API"
#         else:
#             columns_to_keep = ['oc_no', 'style', 'line', 'color', 'section', 'operationName', 'operationCode', 'cumInputQty', 'cumOutputQty', 'wipQty']
#             allDFs = allDFs[columns_to_keep]
#             merged_df = manning_df.merge(
#                 allDFs[['oc_no', 'style', 'line', 'color', 'section', 'operationName', 'operationCode', 'wipQty']],
#                 left_on=['oc_no', 'style', 'line', 'color', 'section', 'operation', 'code'],
#                 right_on=['oc_no', 'style', 'line', 'color', 'section', 'operationName', 'operationCode'],
#                 how='left'
#             )
#             message = "WIP data uploaded to database sucessfully."

#         return success_response(message='Success', data=message, status=status.HTTP_200_OK)
#     except Exception as e:
#         return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def fetch_wip_data_api(request):
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
            return error_response(error=f"No Manning data found for {today}", status=status.HTTP_400_BAD_REQUEST)

        manning_df = pd.DataFrame(list(manning_queryset))
        distinct_data = manning_queryset.values(
            'raw_oc_no', 'raw_style', 'raw_color', 'line'
        ).distinct()

        columns_to_keep = ['raw_oc_no', 'order_no', 'buyer', 'raw_style', 'line', 'raw_color', 'section', 'op_seq', 'operation', 'code']
        available_cols = [c for c in columns_to_keep if c in manning_df.columns]
        manning_df = manning_df[available_cols]
        manning_df.rename(columns={'raw_oc_no': 'oc_no', 'raw_style': 'style', 'raw_color': 'color'}, inplace=True)

        allDFs = []
        for item in distinct_data:
            df = fetch_wip(
                poRef=item['raw_oc_no'],
                style=item['raw_style'],
                color=item['raw_color'],
                line=item['line']
            )
            df['oc_no'] = item['raw_oc_no']
            df['style'] = item['raw_style']
            df['color'] = item['raw_color']
            df['line'] = item['line']
            allDFs.append(df)

        if not allDFs:
            return error_response(error="No WIP data fetched from OptaFloor API", status=status.HTTP_400_BAD_REQUEST)

        allDFs = pd.concat(allDFs, ignore_index=True)

        columns_to_keep = ['oc_no', 'style', 'line', 'color', 'section', 'operationName', 'operationCode', 'cumInputQty', 'cumOutputQty', 'wipQty']
        allDFs = allDFs[columns_to_keep]

        merged_df = manning_df.merge(
            allDFs[['oc_no', 'style', 'line', 'color', 'section', 'operationName', 'operationCode', 'wipQty']],
            left_on=['oc_no', 'style', 'line', 'color', 'section', 'operation', 'code'],
            right_on=['oc_no', 'style', 'line', 'color', 'section', 'operationName', 'operationCode'],
            how='left'
        )

        if not viaAPI:
            logger.info(f"WIP data processed and uploaded successfully at {str(datetime.now())}")

        return success_response(message="WIP data processed and uploaded successfully", status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error in run_fetch_wip_data: {str(e)}", exc_info=True)
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)




def insert_all_unallocated_employees(all_unallocated_employees, df_active_employees):
    # Ensure 'DATE' is a datetime and format to 'YYYY-MM-DD'
    all_unallocated_employees['DATE'] = pd.to_datetime(all_unallocated_employees['DATE'], errors='coerce').dt.strftime('%Y-%m-%d')

    merged_df = all_unallocated_employees.merge(
        df_active_employees[['Emp No', 'Designation']],
        left_on='EMPLOYEE ID',
        right_on='Emp No',
        how='left'
    )
    merged_df.drop(columns=['Emp No'], inplace=True)

    # Convert to dicts (parallelized)
    def row_to_dict(row):
        return {
            'date': row['DATE'],
            'employee_id': row['EMPLOYEE ID'],
            'employee_name': row['EMPLOYEE NAME'],
            'line': row['LINE'],
            'section': row['SECTION'],
            'code': row['CODE'],
            'type': row['TYPE'],
            'initial_capacity': row['INITIAL CAPACITY'],
            'remaining_capacity': row['REMAINING CAPACITY'],
            'utilization_pct': row['UTILIZATION_PCT'],
            'reason': row['REASON'],
            'category': row['CATEGORY'],
            'period': row['PERIOD'],
            'designation': row['Designation']
        }

    # Use ThreadPoolExecutor to convert rows to dicts
    with ThreadPoolExecutor(max_workers=10) as executor:
        data_dicts = list(executor.map(row_to_dict, [row for _, row in merged_df.iterrows()]))

    # Transform unallocated employees to on hold
    transform_unallocated_to_on_hold_from_dict(data_dicts)

    # Chunked insert to DB using threads
    def insert_chunk(chunk_dicts):
        instances = [UnallocatedEmployees(**d) for d in chunk_dicts]
        with transaction.atomic():
            UnallocatedEmployees.objects.bulk_create(instances)

    chunked_data = [data_dicts[i:i + CHUNK_SIZE] for i in range(0, len(data_dicts), CHUNK_SIZE)]

    logger.info(f"Inserting {len(data_dicts)} unallocated records in {len(chunked_data)} chunks...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(insert_chunk, chunked_data)



def insert_consolidated_df(consolidated_df):
    consolidated_df['STYLE'] = consolidated_df['STYLE'].str.lower()

    # Fill nulls
    consolidated_df['SAM'].fillna(0, inplace=True)
    consolidated_df['ALLOCATED EMP ID'].fillna(0, inplace=True)

    consolidated_df['MACHINE_TYPE'] = (
        consolidated_df['MACHINE_TYPE']
        .astype(str)                            # convert everything to string
        .str.strip()                            # remove leading/trailing whitespace
        .replace(['', 'nan', 'NaN', 'None'], np.nan)  # replace string empty cases with actual NaN
        .fillna('Not Applicable')               # now fill all NaN
    )

    # consolidated_df.drop_duplicates(inplace=True, ignore_index=True) # Removing the duplicate rows


    def row_to_dict(row):
        return {
            'oc_no': row['OC_NO'],
            'order_no': row['ORDER_NO'],
            'buyer': row['BUYER'],
            'style': row['STYLE'],
            'line': row['LINE'],
            'week': row['WEEK'],
            'planned_dates': row['PLANNED_DATES'],
            'planned_qty': row['PLANNED_QTY'],
            'factory': row['FACTORY'],
            'floor': row['FLOOR'],
            'workdays': row['WORKDAYS'],
            'section': row['SECTION'],
            'op_seq': row['OP_SEQ'],
            'operation': row['OPERATION'],
            'code': row['CODE'],
            'sam': row['SAM'],
            'allocated_emp_id': int(row['ALLOCATED EMP ID']),
            'allocated_emp_name': row['ALLOCATED EMP NAME'],
            'allocated_capacity': row['ALLOCATED CAPACITY'],
            'allocated_frm_line': row['ALLOCATED_FRM_LINE'],
            'allocated_frm_factory': row['ALLOCATED_FRM_FACTORY'],
            'allocated_frm_floor': row['ALLOCATED_FRM_FLOOR'],
            'skill_type': row['SKILL_TYPE'],
            'machine': row['MACHINE_EMP_FACT'],
            'shortage_flag': row['SHORTAGE_FLAG'],
            'shortage_reason': row['SHORTAGE_REASON'],
            'designation': row['DESIGNATION'],
            'target_100': row['TARGET@100%'],
            'target_90': row['TARGET@90%'],
            'split_order_id': row['SPLIT_ORDER_ID'],
            'forecast_period': row['PERIOD'],
            'machinist': row['MACHINIST'],
            'machine_type': row['MACHINE_TYPE'],
            'color': row['COLOR'],
            'raw_oc_no': row['RAW_OC_NO'],
            'raw_style': row['RAW_STYLE'],
            'raw_color': row['RAW_FABRIC_ARTICLE']
        }

    def insert_chunk(chunk_dicts):
        instances = [ManningSheetData(**d) for d in chunk_dicts]
        with transaction.atomic():
            ManningSheetData.objects.bulk_create(instances)

    # Step 1: Convert DataFrame rows to list of dicts (sequentially to preserve row order)
    data_dicts = [row_to_dict(row) for _, row in consolidated_df.iterrows()]

    # Step 2: Split into chunks for memory efficiency
    CHUNK_SIZE = 500  # define this globally or change as needed
    chunked_data = [data_dicts[i:i + CHUNK_SIZE] for i in range(0, len(data_dicts), CHUNK_SIZE)]

    # Step 3: Insert each chunk sequentially to preserve order
    logger.info(f"Inserting {len(data_dicts)} records in {len(chunked_data)} chunks sequentially...")
    for chunk in chunked_data:
        insert_chunk(chunk)


@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def update_allocated_employees(request):
    try:
        final_allocation = request.data.get('final_allocation')
        dday_id = request.data.get('dday_id')

        dday_instance = get_object_or_404(DDayData, pk=dday_id)
        dday_instance.final_allocation = final_allocation
        dday_instance.save()
        return success_response(message='Successully updated the allocation employee.', status=status.HTTP_200_OK)
    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)



# Function to allocated employee in ManningSheet from EmployeeOnHOld
@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def update_employee_on_hold_individual(request):
    try:
        preferred_employee = request.data.get('preferred_employee')
        employee_name = None
        employee_id = 0
        allocated_capacity = request.data.get('allocated_capacity')
        for emp_id, emp_name in preferred_employee.items():
            employee_id = emp_id
            employee_name = emp_name
        manning_id = request.data.get('manning_id')

        manning_instance = get_object_or_404(ManningSheetData, pk=manning_id)

        try:
            employees_on_hold_instance = EmployeesOnHold.objects.get(
                line=manning_instance.line,
                section=manning_instance.section,
                date=manning_instance.planned_dates
            )

            manning_instance.allocated_emp_id = employee_id
            manning_instance.allocated_emp_name = employee_name
            if allocated_capacity:
                manning_instance.allocated_capacity = allocated_capacity

            preferred_employees = json.loads(employees_on_hold_instance.preferred_employees)
            if preferred_employee in preferred_employees:
                preferred_employees = remove_by_employee_id(preferred_employees, employee_id)
                employees_on_hold_instance.preferred_employees = json.dumps(preferred_employees)
                employees_on_hold_instance.count = len(preferred_employees) if preferred_employees else 0
                manning_instance.save()
                employees_on_hold_instance.save()
                return success_response(message='Successully updated the allocation of an employee.', status=status.HTTP_200_OK)
            else:
                return error_response(error='Employee not found in the preferred employees list.', status=status.HTTP_400_BAD_REQUEST)
        except EmployeesOnHold.DoesNotExist:
            return error_response(error='No EmployeesOnHold instance found for the given line, section, and date.', status=status.HTTP_404_NOT_FOUND)

    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)




@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def update_employee_on_hold(request):
    try:
        multiple_ids = request.data.get('multiple_IDs', [])
        if not multiple_ids:
            return error_response(error='No data found in multiple_IDs.', status=status.HTTP_400_BAD_REQUEST)

        for entry in multiple_ids:
            preferred_employee = entry.get('preferred_employee')
            allocated_capacity = entry.get('allocated_capacity')
            manning_id = entry.get('manning_id')

            if not (preferred_employee and manning_id):
                continue  # Skip this entry if essential data is missing

            employee_name = None
            employee_id = 0

            for emp_id, emp_name in preferred_employee.items():
                employee_id = emp_id
                employee_name = emp_name

            manning_instance = get_object_or_404(ManningSheetData, pk=manning_id)

            try:
                employees_on_hold_instance = EmployeesOnHold.objects.get(
                    line=manning_instance.line,
                    section=manning_instance.section,
                    date=manning_instance.planned_dates
                )

                manning_instance.allocated_emp_id = employee_id
                manning_instance.allocated_emp_name = employee_name
                if allocated_capacity:
                    manning_instance.allocated_capacity = allocated_capacity

                preferred_employees = json.loads(employees_on_hold_instance.preferred_employees)

                if any(str(employee_id) == str(eid) for eid in map(str, [list(emp.keys())[0] for emp in preferred_employees])):
                    # preferred_employees = remove_by_employee_id(preferred_employees, employee_id)
                    # employees_on_hold_instance.preferred_employees = json.dumps(preferred_employees)
                    # employees_on_hold_instance.count = len(preferred_employees) if preferred_employees else 0
                    manning_instance.save()
                    # employees_on_hold_instance.save()
                else:
                    return error_response(error=f'Employee {employee_id} not found in preferred employees list for manning_id {manning_id}.',
                                          status=status.HTTP_400_BAD_REQUEST)
            except EmployeesOnHold.DoesNotExist:
                return error_response(error=f'No EmployeesOnHold instance found for manning_id {manning_id}.',
                                      status=status.HTTP_404_NOT_FOUND)

        return success_response(message='Successfully updated the allocation of all employees.', status=status.HTTP_200_OK)

    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)





# Function to manually update 'allocated_capaity' of an allocated employee
@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def update_allocated_capacity(request):
    try:
        allocated_capacity = request.data.get('allocated_capacity')
        manning_id = request.data.get('manning_id')

        # Validate required fields
        if not allocated_capacity or not manning_id:
            return error_response(error='"allocated_capacity" and "manning_id" are required.', status=status.HTTP_400_BAD_REQUEST)

        manning_instance = get_object_or_404(ManningSheetData, pk=manning_id)

        try:
            manning_instance.allocated_capacity = allocated_capacity
            manning_instance.save()
            return success_response(message='Successully updated the allocated capacity of an employee.', status=status.HTTP_200_OK)
        except EmployeesOnHold.DoesNotExist:
            return error_response(error='Error in allocating capacity to an employee.', status=status.HTTP_404_NOT_FOUND)

    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)



@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def uploading_planned_leaves(request):
    try:
        file = request.FILES.get('file')
        if not file:
            return error_response(error='File is required', status=status.HTTP_400_BAD_REQUEST)
        
        df = pd.read_excel(file)
        # Determine the correct column name for employee ID
        employee_id_col = 'Empployee ID' if 'Empployee ID' in df.columns else 'Employee ID'

        # Keep only the required columns and drop rows with any NaN in these
        df_filtered = df[[employee_id_col, 'From', 'To']].dropna(subset=[employee_id_col, 'From', 'To'])

        # Expand leave date ranges
        def expand_date_ranges(row):
            start = pd.to_datetime(row['From'])
            end = pd.to_datetime(row['To'])
            date_range = pd.date_range(start, end)
            return [{employee_id_col: row[employee_id_col], 'Date': date} for date in date_range]

        # Apply the expansion
        expanded_rows = []
        for _, row in df_filtered.iterrows():
            expanded_rows.extend(expand_date_ranges(row))

        # Create final DataFrame
        leaves_df = pd.DataFrame(expanded_rows)
        leaves_df.to_csv('csv_files/Planned_Leaves.csv', index=False)
        return success_response(message='File processed and data saved successfully', data="message", status=status.HTTP_200_OK)
    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)



@api_view(['GET', 'POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def get_unallocated_employees_dday(request):
    try:
        line_no = request.query_params.get('line', 'all').strip()
        df_unallocated_employees = pd.read_csv('exports/unallocated_report_dday.csv')
        df_unallocated_employees = df_unallocated_employees[(df_unallocated_employees['reason'] != 'Employee Absent') & (df_unallocated_employees['type'] == 'Primary')]

        file_name = f"Unallocated_Employees_DDay"

        if line_no.lower() != 'all':
            df_unallocated_employees = df_unallocated_employees[df_unallocated_employees['line'] == line_no.title()]
            file_name =  f"Unallocated_Employees_DDay_{line_no.replace(' ', '_').title()}"

        if request.method == 'POST':
            df_unallocated_employees.columns = df_unallocated_employees.columns.str.replace('_', ' ').str.upper()
            # Convert timezone-aware datetimes to timezone-naive
            for col in df_unallocated_employees.select_dtypes(include=['datetimetz']).columns:
                df_unallocated_employees[col] = df_unallocated_employees[col].dt.tz_localize(None)
            # Generate Excel file in memory
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_unallocated_employees.to_excel(writer, index=False, sheet_name='Unallocated Employees')

                # Get the workbook and worksheet objects
                # workbook  = writer.book
                worksheet = writer.sheets['Unallocated Employees']

                # Auto-adjust column widths
                for i, col in enumerate(df_unallocated_employees.columns):
                    # Get max length of values in column (including column name)
                    max_len = max(
                        df_unallocated_employees[col].astype(str).map(len).max(),
                        len(col)
                    ) + 2  # Add padding
                    worksheet.set_column(i, i, max_len)

            output.seek(0)
            response = HttpResponse(output.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = f"attachment; filename={file_name}.xlsx"
            return response
    except Exception as e:
        return error_response(error=str(e), status=status.HTTP_400_BAD_REQUEST)
    


# Function to manually upload WIP data from a file
@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def upload_wip_data(request):
    file = request.FILES.get('file')

    if not file:
        return error_response(error='File is required', status=status.HTTP_400_BAD_REQUEST)
    
    try:
        # Check the file type
        if file.name.endswith('.csv'):
            df_wip_data = pd.read_csv(file)
        elif file.name.endswith(('.xls', '.xlsx')):
            df_wip_data = pd.read_excel(file)

        df_wip_data.fillna({
            'op_seq': 0,
        }, inplace=True)

        df_wip_data.dropna(how='all', inplace=True)

        # Insert data in chunks
        records = [
            WIPData(
                oc_no=row['oc_no'], 
                order_no=row['order_no'], 
                buyer=row['buyer'],
                style=row['style'], 
                line=row['line'],
                color=row['color'], 
                section=row['section'], 
                op_seq=row['op_seq'], 
                operation=row['operation'],
                code=row['code'], 
                wip_qty=row['wip_qty']
            ) for _, row in df_wip_data.iterrows()
        ]

        with transaction.atomic():
            # Delete old data before inserting new records
            truncate_table(WIPData)
            for i in range(0, len(records), CHUNK_SIZE):
                WIPData.objects.bulk_create(records[i:i+CHUNK_SIZE])
        
        return success_response(message= 'File processed and wip data saved successfully', status=status.HTTP_201_CREATED)
    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)
    


@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def add_bulk_wip_data(request):
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
                "wipQty": 5633
            },
            {
                "line": "Line 6",
                "section": "Back",
                "operationName": "Yoke Centre Tacking",
                "operationCode": "BA51",
                "cumInputQty": 3204,
                "cumOutputQty": 2923,
                "wipQty": 281
            },
            {
                "line": "Line 6",
                "section": "Back",
                "operationName": "Washcare Label attach",
                "operationCode": "BA40",
                "cumInputQty": 2862,
                "cumOutputQty": 2694,
                "wipQty": 168
            },
            {
                "line": "Line 6",
                "section": "Back",
                "operationName": "Back-Endline QC",
                "operationCode": "BA64",
                "cumInputQty": 2694,
                "cumOutputQty": 2670,
                "wipQty": 24
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "B/H Band & B/S",
                "operationCode": "CL15",
                "cumInputQty": 3599,
                "cumOutputQty": 3360,
                "wipQty": 239
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Collar-Endline QC",
                "operationCode": "CL56",
                "cumInputQty": 3360,
                "cumOutputQty": 3013,
                "wipQty": 347
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Collar Button Down Hole",
                "operationCode": "CL20",
                "cumInputQty": 3360,
                "cumOutputQty": 3360,
                "wipQty": 0
            },
            {
                "line": "Line 6",
                "section": "Ticketing & Bundling",
                "operationName": "Bundling (FR, SL & BA)",
                "operationCode": "null",
                "cumInputQty": 0,
                "cumOutputQty": 0,
                "wipQty": 0
            },
            {
                "line": "Line 6",
                "section": "Ticketing & Bundling",
                "operationName": "Bundling (CL & CU)",
                "operationCode": "null",
                "cumInputQty": 0,
                "cumOutputQty": 0,
                "wipQty": 0
            },
            {
                "line": "Line 6",
                "section": "Sleeve",
                "operationName": "Sew Small Sleeve Placket",
                "operationCode": "SL01",
                "cumInputQty": 5633,
                "cumOutputQty": 2964,
                "wipQty": 2669
            },
            {
                "line": "Line 6",
                "section": "Sleeve",
                "operationName": "Sleeve Tacking",
                "operationCode": "SL02",
                "cumInputQty": 2964,
                "cumOutputQty": 2754,
                "wipQty": 210
            },
            {
                "line": "Line 6",
                "section": "Sleeve",
                "operationName": "Sleeve Box",
                "operationCode": "SL04",
                "cumInputQty": 2754,
                "cumOutputQty": 2412,
                "wipQty": 342
            },
            {
                "line": "Line 6",
                "section": "Sleeve",
                "operationName": "Sleeve Pleet & Triming",
                "operationCode": "SL16",
                "cumInputQty": 2412,
                "cumOutputQty": 2342,
                "wipQty": 70
            },
            {
                "line": "Line 6",
                "section": "Sleeve",
                "operationName": "Button Hole On Sleeve Placket",
                "operationCode": "SL07",
                "cumInputQty": 2342,
                "cumOutputQty": 2322,
                "wipQty": 20
            },
            {
                "line": "Line 6",
                "section": "Sleeve",
                "operationName": "Button Stitch On Sleeve Placket",
                "operationCode": "SL08",
                "cumInputQty": 2322,
                "cumOutputQty": 2302,
                "wipQty": 20
            },
            {
                "line": "Line 6",
                "section": "Sleeve",
                "operationName": "Sleeve-Endline QC",
                "operationCode": "SL33",
                "cumInputQty": 2302,
                "cumOutputQty": 2302,
                "wipQty": 0
            },
            {
                "line": "Line 6",
                "section": "Matching",
                "operationName": "Matching.",
                "operationCode": "MT01",
                "cumInputQty": 2302,
                "cumOutputQty": 2302,
                "wipQty": 0
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "Cuff Attach",
                "operationCode": "AS09",
                "cumInputQty": 1699,
                "cumOutputQty": 1629,
                "wipQty": 70
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "Assembly-Endline QC",
                "operationCode": "AS82",
                "cumInputQty": 1508,
                "cumOutputQty": 1072,
                "wipQty": 436
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "BUTTON DOWN",
                "operationCode": "AS20",
                "cumInputQty": 1509,
                "cumOutputQty": 1508,
                "wipQty": 1
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "Hanger Loading",
                "operationCode": "HE",
                "cumInputQty": 2302,
                "cumOutputQty": 1980,
                "wipQty": 322
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "Join Sholuder",
                "operationCode": "AS01",
                "cumInputQty": 1980,
                "cumOutputQty": 1850,
                "wipQty": 130
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "Collar Attach",
                "operationCode": "AS03",
                "cumInputQty": 1850,
                "cumOutputQty": 1840,
                "wipQty": 10
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "Collar Finish",
                "operationCode": "AS04",
                "cumInputQty": 1840,
                "cumOutputQty": 1840,
                "wipQty": 0
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "Sleeve Attach",
                "operationCode": "AS05",
                "cumInputQty": 1840,
                "cumOutputQty": 1835,
                "wipQty": 5
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "Sleeve Top",
                "operationCode": "AS06",
                "cumInputQty": 1835,
                "cumOutputQty": 1699,
                "wipQty": 136
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "French Fell -1",
                "operationCode": "AS59",
                "cumInputQty": 1699,
                "cumOutputQty": 1699,
                "wipQty": 0
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "French Fell 2",
                "operationCode": "AS17",
                "cumInputQty": 1699,
                "cumOutputQty": 1699,
                "wipQty": 0
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "Bottom Hem",
                "operationCode": "AS14",
                "cumInputQty": 1629,
                "cumOutputQty": 1509,
                "wipQty": 120
            },
            {
                "line": "Line 6",
                "section": "Assembly",
                "operationName": "PRL EXTRA BUTTON",
                "operationCode": "AS64",
                "cumInputQty": 1508,
                "cumOutputQty": 1508,
                "wipQty": 0
            },
            {
                "line": "Line 6",
                "section": "Finishing",
                "operationName": "Qualiy Control",
                "operationCode": "FN05",
                "cumInputQty": 0,
                "cumOutputQty": 0,
                "wipQty": 0
            },
            {
                "line": "Line 6",
                "section": "Finishing",
                "operationName": "Packaging",
                "operationCode": "FN02",
                "cumInputQty": 0,
                "cumOutputQty": 0,
                "wipQty": 0
            },
            {
                "line": "Line 6",
                "section": "Finishing",
                "operationName": "Carton Auditing",
                "operationCode": "FN06",
                "cumInputQty": 0,
                "cumOutputQty": 0,
                "wipQty": 0
            },
            {
                "line": "Line 6",
                "section": "Finishing",
                "operationName": "Trim & Exam",
                "operationCode": "FN01",
                "cumInputQty": 0,
                "cumOutputQty": 0,
                "wipQty": 0
            },
            {
                "line": "Line 6",
                "section": "Finishing",
                "operationName": "Folding",
                "operationCode": "FN04",
                "cumInputQty": 0,
                "cumOutputQty": 0,
                "wipQty": 0
            },
            {
                "line": "Line 6",
                "section": "CSO",
                "operationName": "CSO Audit",
                "operationCode": "CSO",
                "cumInputQty": 5633,
                "cumOutputQty": 0,
                "wipQty": 5633
            },
            {
                "line": "Line 6",
                "section": "Cuff",
                "operationName": "Cuff Lining Attach",
                "operationCode": "CU26",
                "cumInputQty": 5633,
                "cumOutputQty": 5058,
                "wipQty": 575
            },
            {
                "line": "Line 6",
                "section": "Front",
                "operationName": "Front Button Hole",
                "operationCode": "FR14",
                "cumInputQty": 3009,
                "cumOutputQty": 2759,
                "wipQty": 250
            },
            {
                "line": "Line 6",
                "section": "Front",
                "operationName": "Pairing",
                "operationCode": "FR24",
                "cumInputQty": 2759,
                "cumOutputQty": 2750,
                "wipQty": 9
            },
            {
                "line": "Line 6",
                "section": "Front",
                "operationName": "Front-Endline QC",
                "operationCode": "FR75",
                "cumInputQty": 2750,
                "cumOutputQty": 2449,
                "wipQty": 301
            },
            {
                "line": "Line 6",
                "section": "Front",
                "operationName": "Front Button Sew",
                "operationCode": "FR15",
                "cumInputQty": 3390,
                "cumOutputQty": 3165,
                "wipQty": 225
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Neckband Fusing Attach",
                "operationCode": "CL55",
                "cumInputQty": 5633,
                "cumOutputQty": 5428,
                "wipQty": 205
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Collar Run - Non Fusible",
                "operationCode": "CL41",
                "cumInputQty": 5633,
                "cumOutputQty": 4529,
                "wipQty": 1104
            },
            {
                "line": "Line 6",
                "section": "Cuff",
                "operationName": "Cuff Hem",
                "operationCode": "CU13",
                "cumInputQty": 5058,
                "cumOutputQty": 4556,
                "wipQty": 502
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Neck Band Hem",
                "operationCode": "CL08",
                "cumInputQty": 5428,
                "cumOutputQty": 4298,
                "wipQty": 1130
            },
            {
                "line": "Line 6",
                "section": "Cuff",
                "operationName": "Run Cuff-Round Shape",
                "operationCode": "CU02",
                "cumInputQty": 4556,
                "cumOutputQty": 3982,
                "wipQty": 574
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Top Stich Collar",
                "operationCode": "CL05",
                "cumInputQty": 4529,
                "cumOutputQty": 4285,
                "wipQty": 244
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Collar Stay Stitch",
                "operationCode": "CL07",
                "cumInputQty": 4285,
                "cumOutputQty": 4091,
                "wipQty": 194
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Neckband Attach",
                "operationCode": "CL37",
                "cumInputQty": 4091,
                "cumOutputQty": 3967,
                "wipQty": 124
            },
            {
                "line": "Line 6",
                "section": "Cuff",
                "operationName": "Top Stitch Cuff",
                "operationCode": "CU07",
                "cumInputQty": 3982,
                "cumOutputQty": 3746,
                "wipQty": 236
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Pick Attach",
                "operationCode": "CL66",
                "cumInputQty": 3967,
                "cumOutputQty": 3915,
                "wipQty": 52
            },
            {
                "line": "Line 6",
                "section": "Front",
                "operationName": "Front placket attach (cut and sew)",
                "operationCode": "FR65",
                "cumInputQty": 5633,
                "cumOutputQty": 3009,
                "wipQty": 2624
            },
            {
                "line": "Line 6",
                "section": "Cuff",
                "operationName": "Cuff Button Hole (2 Hole In Shirt)",
                "operationCode": "PCU03",
                "cumInputQty": 3746,
                "cumOutputQty": 3708,
                "wipQty": 38
            },
            {
                "line": "Line 6",
                "section": "Back",
                "operationName": "CENTRE PLEAT",
                "operationCode": "BA45",
                "cumInputQty": 5633,
                "cumOutputQty": 3204,
                "wipQty": 2429
            },
            {
                "line": "Line 6",
                "section": "Front",
                "operationName": "Button Placket Hem",
                "operationCode": "FR06",
                "cumInputQty": 5633,
                "cumOutputQty": 3390,
                "wipQty": 2243
            },
            {
                "line": "Line 6",
                "section": "Back",
                "operationName": "SPLIT YOKE ATTACH DOUBLE",
                "operationCode": "BA50",
                "cumInputQty": 5633,
                "cumOutputQty": 3258,
                "wipQty": 2375
            },
            {
                "line": "Line 6",
                "section": "Cuff",
                "operationName": "Cuff Button Sew( 2 In Shirt)",
                "operationCode": "CU09",
                "cumInputQty": 3708,
                "cumOutputQty": 3708,
                "wipQty": 0
            },
            {
                "line": "Line 6",
                "section": "Cuff",
                "operationName": "Cuff-Endline QC",
                "operationCode": "CU43",
                "cumInputQty": 3708,
                "cumOutputQty": 3306,
                "wipQty": 402
            },
            {
                "line": "Line 6",
                "section": "Collar",
                "operationName": "Top Stich on NB",
                "operationCode": "CL11",
                "cumInputQty": 3915,
                "cumOutputQty": 3599,
                "wipQty": 316
            },
            {
                "line": "Line 6",
                "section": "Back",
                "operationName": "Main Label (Four Side)",
                "operationCode": "BA17",
                "cumInputQty": 3258,
                "cumOutputQty": 3066,
                "wipQty": 192
            },
            {
                "line": "Line 6",
                "section": "Back",
                "operationName": "Premium Label Attach",
                "operationCode": "BA04",
                "cumInputQty": 3066,
                "cumOutputQty": 3005,
                "wipQty": 61
            },
            {
                "line": "Line 6",
                "section": "Back",
                "operationName": "YOKE ATTACH (PLEAT/ SPLIT DOUBLE)",
                "operationCode": "BA48",
                "cumInputQty": 2923,
                "cumOutputQty": 2862,
                "wipQty": 61
            }
        ]
        wip_instances = []

        for item in data_list:
            if item['operationCode'] == 'null':
                pass
            else:
                wip = WIPData(
                    oc_no="prls/24/13608",
                    order_no="tbc",
                    buyer="POLO RALPH LAUREN - BSR GD OXFORD",
                    style="710729232004 - BDPPCSPT",
                    line="Line 6",
                    color="BASTILLEBLUE",
                    section=item.get('section', ''), # Fetch from datalist
                    op_seq=item.get('op_seq', 0),
                    operation=item.get('operationName', ''),
                    code=item.get('operationCode', ''),
                    wip_qty=item.get('wipQty', 0.0)
                )
                wip_instances.append(wip)

        with transaction.atomic():
            truncate_table(WIPData)
            WIPData.objects.bulk_create(wip_instances, batch_size=1000)

        logger.info(f"Inserted {len(wip_instances)} records into WIPData.")
        return success_response(message=f'Inserted {len(wip_instances)} records into WIPData.', data="message", status=status.HTTP_200_OK)
    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)
