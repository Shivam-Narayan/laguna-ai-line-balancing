import logging
logger = logging.getLogger(__name__)

import os
import django

# Setup Django before importing models
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import numpy as np
import pandas as pd
import concurrent.futures
import multiprocessing as mp

from functools import partial
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed, ProcessPoolExecutor

from django.db import transaction

from config.utils import truncate_table
from .models import ManningSheetData, ManningGeneralInfo, UnallocatedEmployees



CHUNK_SIZE = 50000  # Larger chunk size for better efficiency


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


# Exclude today from all except df_0_day
def filter_by_date_ranges(df, today, date_thresholds, period):

    periodFilter = df[df["planned_dates"] == today]

    if period == 60:
        periodFilter = df[
            (df["planned_dates"] >= today) &
            (df["planned_dates"] <= date_thresholds["60_days"])
        ]
    if period == 30:
        periodFilter = df[
            (df["planned_dates"] > today) &
            (df["planned_dates"] <= date_thresholds["30_days"])
        ]
    if period == 7:
        periodFilter = df[
            (df["planned_dates"] > today) &
            (df["planned_dates"] <= date_thresholds["7_days"])
        ]
    if period == 1:
        periodFilter = df[
            (df["planned_dates"] > today) &
            (df["planned_dates"] <= date_thresholds["1_days"])
        ]

    filtered_dfs = {
        f"{period}_days": periodFilter
    }
    return filtered_dfs




def process_single_df(key, df):
    grouped = df.groupby(
        ["oc_no", "order_no", "buyer", "style", "fabric_article", "line", "week", "planned_dates"],
        as_index=False
    )["planned_qty"].sum()

    grouped = grouped.rename(columns={'fabric_article': 'color'})
    return key, grouped



def process_grouped_results(large_df, chunk_size=10000):
    """
    Process a large DataFrame in parallel by splitting it into chunks and combining the results.
    
    :param large_df: The large input DataFrame.
    :param chunk_size: Number of rows per chunk to process in parallel.
    :return: A single concatenated DataFrame with all results.
    """
    result_chunks = []

    # Split the large DataFrame into chunks
    num_chunks = (len(large_df) + chunk_size - 1) // chunk_size
    chunks = [large_df.iloc[i*chunk_size : (i+1)*chunk_size] for i in range(num_chunks)]

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_single_df, idx, chunk) for idx, chunk in enumerate(chunks)]

        for future in as_completed(futures):
            _, result = future.result()
            result_chunks.append(result)

    # Combine all processed chunks into a single DataFrame
    final_df = pd.concat(result_chunks, ignore_index=True)
    final_df.drop_duplicates(inplace=True)
    return final_df


# Apply mapping, ensuring empty DataFrames also have "FACTORY", "FLOOR" and "Workdays" columns
def map_factory_floor_chunk(chunk):
    if chunk.empty:
        chunk["FACTORY"] = "Unknown"
        chunk["FLOOR"] = "Unknown"
    else:
        chunk[["FACTORY", "FLOOR"]] = pd.DataFrame(
            chunk["line"].apply(map_factory_floor).tolist(),
            index=chunk.index
        )
    chunk["Workdays"] = 6
    return chunk


# Apply mapping, to chunks
def map_factory_floor_for_results(df, chunk_size=10000, max_workers=10):
    """
    Splits a large DataFrame into chunks, maps factory and floor in parallel,
    and recombines the results.
    """
    chunks = np.array_split(df, max(1, len(df) // chunk_size))
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(map_factory_floor_chunk, chunk) for chunk in chunks]
        for future in as_completed(futures):
            results.append(future.result())

    # Combine all processed chunks into a single DataFrame
    final_df = pd.concat(results, ignore_index=True)
    
    final_df.drop_duplicates(inplace=True)

    return final_df





def process_single_manning_df(df, df_Style_OB):
    # Merge with Style OB data
    manning = df.merge(df_Style_OB, left_on=["style"], right_on=["style"], how="inner") # Removed color

    # manning = manning.drop_duplicates(inplace=True)

    # Sort by specified columns
    manning = manning.sort_values(by=["style", "color", "section", "op_seq", "oc_no", "order_no", "line"])

    # Drop unnecessary columns
    manning = manning.drop(columns=["Matched Style", "UNNAMED: 0"], errors='ignore')

    # Group and sort
    manning = manning.groupby(
        ["oc_no", "order_no", "buyer", "style", "color", "line", "section"], as_index=False
    ).apply(lambda x: x.sort_values(by=["op_seq", "planned_dates"])).reset_index(drop=True)

    # Convert column names to uppercase
    manning.columns = manning.columns.str.upper()

    return manning


def create_manning_dataframes(result_dfs, df_Style_OB, chunk_size=10000):

    df_Style_OB = df_Style_OB.drop(columns=['color'], errors='ignore')

    result_chunks = []

    # Split the large DataFrame into chunks
    num_chunks = (len(result_dfs) + chunk_size - 1) // chunk_size
    chunks = [result_dfs.iloc[i*chunk_size : (i+1)*chunk_size] for i in range(num_chunks)]

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_single_manning_df, chunk, df_Style_OB) for chunk in chunks]

        for future in as_completed(futures):
            result = future.result()
            result_chunks.append(result)

    # Combine all processed chunks into a single DataFrame
    final_df = pd.concat(result_chunks, ignore_index=True)
    final_df.drop_duplicates(inplace=True)

    return final_df


# Ensure filter_by_date_ranges, process_grouped_results, and map_factory_floor_for_results are properly defined
def filter_by_date_ranges_wrapper(*args):
    return filter_by_date_ranges(*args)

def process_grouped_results_wrapper(*args):
    return process_grouped_results(*args)

def map_factory_floor_for_results_wrapper(*args):
    return map_factory_floor_for_results(*args)


# Function to fetch prioritized employees based on constraints
def get_prioritized_employees(emp_df, employee_used_capacity, line=None, code=None, section=None, emp_type=None):
    """
    Fetch prioritized employees based on constraints

    Parameters:
    -----------
    emp_df : pandas.DataFrame
        Employee dataframe
    line : str, optional
        Line constraint
    code : str, optional
        Code constraint
    section : str, optional
        Section constraint
    emp_type : str, optional
        Employee type constraint

    Returns:
    --------
    pandas.DataFrame
        Filtered and sorted employees
    """

    for idx, row in emp_df.iterrows():
        emp_id = row["employee_id"]
        skill_capacity = row["average_capacity"]
        already_used = employee_used_capacity.get(emp_id, 0)
        remaining = max(0, skill_capacity - already_used)
        emp_df.at[idx, "effective_remaining_capacity"] = remaining

    query = (emp_df["effective_remaining_capacity"] > 0)

    if line:
        query &= (emp_df["line"] == line)
    if code: # Ensure employee only works on assigned CODE
        query &= (emp_df["code"] == code)
    if section:
        query &= (emp_df["section"] == section)
    if emp_type:
        query &= (emp_df["type"] == emp_type)

    # Filter and sort
    filtered_df = emp_df[query].copy()

    # Sort by TYPE (Primary first) and effective remaining capacity
    filtered_df = filtered_df.sort_values(
        by=["type", "effective_remaining_capacity"],
        ascending=[True, False]
    )
    return filtered_df


# Add allocation columns in manning
allocation_columns = [
    "ALLOCATED EMP ID", "ALLOCATED EMP NAME", "ALLOCATED CAPACITY",
    "ALLOCATED_FRM_LINE", "ALLOCATED_FRM_FACTORY", "ALLOCATED_FRM_FLOOR",
    "SKILL_TYPE", "MACHINE_EMP_FACT", "SHORTAGE_FLAG", "SHORTAGE_REASON", "DESIGNATION",
    "TARGET@100%", "TARGET@90%", "SPLIT_ORDER_ID", "PERIOD"
]



def run_manning_allocation(PERIOD, manning_df, emp_fact_df_original, df_unique_smv=None):
    """
    Main function to run the manning allocation process with multithreading support
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"[{timestamp}] Starting manning allocation process...")

    truncate_table(UnallocatedEmployees)

    results = {}
    all_processed_dfs = []
    unallocated_collection = {}

    # Filter emp_fact_df
    # emp_fact_df_original = emp_fact_df_original[emp_fact_df_original["type"].isin(["Primary", "Secondary"])]

    suffix = str(PERIOD)
    manning_df = manning_df.copy()
    df_name = f"manning_{suffix}_df"

    try:
        if manning_df is not None:
            logger.info(f"Processing manning data for period {PERIOD}...")

            updated_manning_df, unallocated_employees = process_manning_dataframe(
                manning_df,
                emp_fact_df_original,
                PERIOD,
                df_unique_smv
            )

            # Store results
            results[f"updated_manning_{suffix}_df"] = updated_manning_df

            # Store unallocated employees in collection using the original df_name format
            unallocated_collection[df_name] = unallocated_employees

            # Add to our collection for consolidation
            all_processed_dfs.append(updated_manning_df)

            logger.info(f"Successfully processed period {PERIOD}:")
            logger.info(f"  - Created manning sheet with {len(updated_manning_df)} rows")
    except Exception as e:
        logger.info(f"Error processing period {PERIOD}: {e}")

    # Process unallocated employee data
    unallocated_results = process_unallocated_data(unallocated_collection, {"suffix": str(PERIOD), "period": PERIOD, "df": manning_df, "df_name": df_name})
    results.update(unallocated_results)

    try:
        if all_processed_dfs:
            consolidated_df = pd.concat(all_processed_dfs, ignore_index=True)

            for col in ['OC NO', 'BUYER', 'STYLE', 'COLOR']:
                if col in consolidated_df.columns:
                    consolidated_df[col] = consolidated_df[col].str.upper()

            consolidated_df['STYLE'] = consolidated_df['STYLE'].str.lower()

            # Fill nulls
            consolidated_df['SAM'].fillna(0, inplace=True)
            consolidated_df['smv'].fillna(0, inplace=True)
            consolidated_df['ALLOCATED EMP ID'].fillna(0, inplace=True)

            consolidated_df['MACHINE_TYPE'] = consolidated_df['MACHINE_TYPE'].replace('nan', 'Not Applicable')

            consolidated_df.drop_duplicates(inplace=True) # Removing the duplicate rows
            
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
                    'smv': row['smv'],
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
                    'color': row['COLOR']
                }

            # Use ThreadPoolExecutor to convert rows to dicts
            with ThreadPoolExecutor(max_workers=10) as executor:
                data_dicts = list(executor.map(row_to_dict, [row for _, row in consolidated_df.iterrows()]))
    
            # Chunked insert to DB using threads
            def insert_chunk(chunk_dicts):
                instances = [ManningSheetData(**d) for d in chunk_dicts]
                with transaction.atomic():
                    ManningSheetData.objects.bulk_create(instances)

            chunked_data = [data_dicts[i:i + CHUNK_SIZE] for i in range(0, len(data_dicts), CHUNK_SIZE)]

            logger.info(f"Inserting {len(data_dicts)} unallocated records in {len(chunked_data)} chunks...")
            with ThreadPoolExecutor(max_workers=10) as executor:
                executor.map(insert_chunk, chunked_data)

                
            results["consolidated_manning_df"] = consolidated_df

            if "all_unallocated_employees" in results:
                skill_gap_results = analyze_skill_gaps(consolidated_df, results["all_unallocated_employees"])
                results.update(skill_gap_results)

            logger.info(f"Successfully created consolidated manning dataframe with {len(consolidated_df)} total rows")
        else:
            logger.info("No dataframes were processed successfully for consolidation")
    except Exception as e:
        raise ValueError(f"Error creating consolidated dataframe: {e}")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"[{timestamp}] Manning allocation process completed.")

    return results



def process_single_date_standalone(daily_orders, emp_fact_df, period):
    """
    Process a single date's worth of manning data without requiring shared state.
    Designed to be compatible with ProcessPoolExecutor.
    
    Args:
        daily_orders: DataFrame containing orders for a specific date
        emp_fact_df: The employee DataFrame for this process
        period: Time period identifier
        
    Returns:
        tuple: (processed date DataFrame, list of unallocated employees)
    """
    # Track capacity used per employee
    employee_used_capacity = {}
    
    # Reset remaining capacity for all employees
    for idx, emp_row in emp_fact_df.iterrows():
        emp_id = emp_row["employee_id"]
        skill_capacity = emp_row["average_capacity"]
        
        # Initialize capacity tracking
        employee_used_capacity[emp_id] = 0
        
        # Set remaining capacity
        emp_fact_df.at[idx, "remaining_capacity"] = skill_capacity
    
    # Pre-compute grouping to avoid redundant operations
    grouped_orders = daily_orders.groupby(['LINE', 'SECTION', 'CODE'])
    
    new_rows = []
    date = None
    if len(daily_orders) > 0:
        date = daily_orders["PLANNED_DATES"].iloc[0]
    
    # Process each group
    for (line, section, code), group_orders in grouped_orders:
        group_rows = process_order_group(
            line, section, code, group_orders, 
            emp_fact_df, employee_used_capacity, date, period
        )
        new_rows.extend(group_rows)
    
    # Get unallocated employees
    unallocated_employees = get_unallocated_employees(
        emp_fact_df, daily_orders, date, period
    )
    
    # Convert to DataFrame if we have rows
    if new_rows:
        date_df = pd.DataFrame(new_rows)
    else:
        date_df = pd.DataFrame(columns=daily_orders.columns)
        
    return date_df, unallocated_employees


# Create a function that will receive serializable arguments
def process_date_for_pool(args):
    date, filtered_df, emp_fact_df, period = args
    logger.info(f"Processing date: {date}")
    
    # Process this date's data
    date_df, unallocated = process_single_date_standalone(
        filtered_df, 
        emp_fact_df.copy(), 
        period
    )
    
    return date_df, unallocated



def process_manning_dataframe(manning_df, emp_fact_df, period, df_unique_smv=None, max_workers=None):
    """
    Threaded version of processing a manning DataFrame.
    """
    manning_df["PLANNED_DATES"] = pd.to_datetime(manning_df["PLANNED_DATES"])

    updated_manning_df = pd.DataFrame(columns=manning_df.columns)
    unallocated_employees_list = []

    # Ensure all allocation columns are present
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
                manning_df[col] = period
            else:
                manning_df[col] = None

    unique_dates = sorted(manning_df["PLANNED_DATES"].unique())

    # Determine optimal process count if not specified
    if max_workers is None:
        # Use fewer processes than CPUs to avoid overwhelming the system
        max_workers = max(1, os.cpu_count() - 1)

    results = []
    unallocated_employees_list = []

    data_by_date = []
    for date in unique_dates:
        # date_str = date.strftime('%Y-%m-%d')
        filtered_df = manning_df[manning_df["PLANNED_DATES"] == date].copy()
        data_by_date.append((date, filtered_df, emp_fact_df, period))

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        for date_idx, (date_df, unallocated) in enumerate(executor.map(process_date_for_pool, data_by_date)):
            results.append(date_df)
            if unallocated and len(unallocated) > 0:
                unallocated_employees_list.append(pd.DataFrame(unallocated))
    
    
    # Combine results
    if results:
        updated_manning_df = pd.concat(results, ignore_index=True)
    else:
        updated_manning_df = pd.DataFrame(columns=manning_df.columns)

    # Merge SMV if available
    try:
        if df_unique_smv is not None:
            updated_manning_df = updated_manning_df.merge(
                df_unique_smv[['style', 'smv']], left_on='STYLE', right_on='style', how='left'
            )
    except Exception as e:
        raise ValueError(f"SMV data error. Message: {e}")

    return updated_manning_df, unallocated_employees_list



def process_order_group(line, section, code, group_orders, emp_fact_df, employee_used_capacity, date, period):  # added employee_used_capacity on 03-05-2025
    total_planned_qty = group_orders['PLANNED_QTY'].sum()
    new_rows = []

    # Get available employees for this skill combination
    available_employees = get_prioritized_employees(
        emp_df=emp_fact_df,
        employee_used_capacity=employee_used_capacity,
        line=line,
        code=code,
        section=section
    )

    if available_employees.empty:
        # No matching employees - mark all as shortages
        for _, row in group_orders.iterrows():
            shortage_row = row.copy()
            shortage_row["SHORTAGE_FLAG"] = "Shortage Unresolved"

            # Add shortage reason based on availability checks
            any_matching_code = emp_fact_df[emp_fact_df["code"] == code].shape[0] > 0

            if not any_matching_code:
                shortage_row["SHORTAGE_REASON"] = f"No employees with CODE={code} found in any line"
            else:
                # Check for employees with matching code in different lines
                other_lines = set(emp_fact_df[
                    (emp_fact_df["code"] == code) &
                    (emp_fact_df["line"] != line)
                ]["line"].unique())

                if other_lines:
                    shortage_row["SHORTAGE_REASON"] = f"CODE={code} found only in lines: {', '.join(other_lines)}"
                else:
                    # Check if there are employees in this line but with zero capacity
                    zero_capacity = emp_fact_df[
                        (emp_fact_df["code"] == code) &
                        (emp_fact_df["line"] == line) &
                        (emp_fact_df["remaining_capacity"] == 0)
                    ].shape[0] > 0

                    if zero_capacity:
                        shortage_row["SHORTAGE_REASON"] = f"Employees with CODE={code} in LINE={line} have no remaining capacity"
                    else:
                        shortage_row["SHORTAGE_REASON"] = f"No matching employees for LINE={line} and CODE={code}"

            shortage_row["SPLIT_ORDER_ID"] = ""
            new_rows.append(shortage_row)

    # PHASE 1: Allocate employees
    employee_allocations = []
    remaining_total_qty = total_planned_qty

    for _, emp in available_employees.iterrows():
        emp_id = emp["employee_id"]
        skill_capacity = emp["average_capacity"]  # Skill-specific capacity (e.g., 100 for Primary, 80 for Secondary)
        already_used = employee_used_capacity.get(emp_id, 0)
        available_capacity = skill_capacity - already_used

        if available_capacity > 0 and remaining_total_qty > 0:
            allocation = min(remaining_total_qty, available_capacity)
            allocation = round(allocation, 2)

            #The if statement causing error was improperly nested, and is now fixed
            if allocation > 0:
                # Save this allocation plan
                employee_allocations.append({
                    "EMPLOYEE ID": emp["employee_id"],
                    "EMPLOYEE NAME": emp["employee_name"],
                    "ALLOCATION": allocation,
                    "LINE": emp["line"],
                    "FACTORY": emp["factory"],
                    "FLOOR": emp["floor"],
                    "TYPE": emp["type"],
                    "MACHINE": emp["machine"],
                    "DESIGNATION": emp["designation"],
                    "SKILL_CAPACITY": skill_capacity  # Store for reference
                })

                # Update remaining quantity
                remaining_total_qty -= allocation
                remaining_total_qty = round(remaining_total_qty, 2)
                employee_used_capacity[emp_id] = already_used + allocation

                emp_fact_df.loc[
                    (emp_fact_df["employee_id"] == emp["employee_id"]) &
                    (emp_fact_df["code"] == emp["code"]) &
                    (emp_fact_df["type"] == emp["type"]),
                    "remaining_capacity"
                ] = available_capacity - allocation

                # Update remaining capacity for all skill types of this employee
                # Their remaining capacity = their skill capacity - total used
                emp_fact_df.loc[
                    emp_fact_df["employee_id"] == emp_id,
                    "remaining_capacity"
                ] = emp_fact_df.apply(
                    lambda row: max(0, row["average_capacity"] - employee_used_capacity[emp_id])
                    if row["employee_id"] == emp_id else row["remaining_capacity"],
                    axis=1
                )


    # Check if we have a shortage after allocation planning
    # if remaining_total_qty > 0:
    #     shortage_qty = remaining_total_qty
    #     print(f"WARNING: Group shortage of {shortage_qty} units for {line}/{section}/{code}")

    # PHASE 2: Distribute the allocations to individual orders
    # Sort orders by quantity (descending) to prioritize larger orders
    sorted_orders = group_orders.sort_values(by="PLANNED_QTY", ascending=False)
   
    # Process each order using our pre-determined employee allocations
    current_emp_index = 0  # Start with the first pre-allocated employee


    for _, row in sorted_orders.iterrows():
        original_row = row.copy()
        planned_qty = row["PLANNED_QTY"]
        remaining_qty = planned_qty

        # Skip if no employees were allocated
        if not employee_allocations:
            shortage_row = original_row.copy()
            shortage_row["SHORTAGE_FLAG"] = "Shortage"
            shortage_row["SHORTAGE_REASON"] = f"No employees available for {line}/{section}/{code}"
            new_rows.append(shortage_row)
            continue

        #first_allocation = True
        split_count = 0
        split_order_id = f"{row['ORDER_NO']}_{row['STYLE']}_{line}_{code}_{date.strftime('%Y%m%d')}"

        # Allocate this order using pre-determined employees
        while remaining_qty > 0 and current_emp_index < len(employee_allocations):
            current_emp = employee_allocations[current_emp_index]

            # How much can this employee take from the current order?
            order_allocation = min(remaining_qty, current_emp["ALLOCATION"])

            if order_allocation > 0:
                split_count += 1
                current_row = original_row.copy()
                current_row["SPLIT_ORDER_ID"] = f"{split_order_id}_part{split_count}"

                # Set allocation details
                current_row["ALLOCATED EMP ID"] = current_emp["EMPLOYEE ID"]
                current_row["ALLOCATED EMP NAME"] = current_emp["EMPLOYEE NAME"]
                current_row["ALLOCATED CAPACITY"] = float(order_allocation)
                current_row["ALLOCATED_FRM_LINE"] = current_emp["LINE"]
                current_row["ALLOCATED_FRM_FACTORY"] = current_emp["FACTORY"]
                current_row["ALLOCATED_FRM_FLOOR"] = current_emp["FLOOR"]
                current_row["SKILL_TYPE"] = current_emp["TYPE"]
                current_row["MACHINE_EMP_FACT"] = current_emp["MACHINE"]
                current_row["DESIGNATION"] = current_emp["DESIGNATION"]
                current_row["TARGET@100%"] = float(order_allocation)
                current_row["TARGET@90%"] = float(order_allocation) * 0.9
                current_row["PLANNED_QTY"] = float(order_allocation)
                current_row["PERIOD"] = period
                current_row["SHORTAGE_FLAG"] = "Fulfilled"
                current_row["SHORTAGE_REASON"] = ""

                # Update remaining quantities
                remaining_qty -= order_allocation
                remaining_qty = round(remaining_qty, 2)

                # Update employee's allocation in our plan
                current_emp["ALLOCATION"] -= order_allocation
                current_emp["ALLOCATION"] = round(current_emp["ALLOCATION"], 2)

                # Add to our results
                new_rows.append(current_row)

            # If this employee is fully allocated, move to next employee
            if current_emp["ALLOCATION"] <= 0.001:
                current_emp_index += 1

        # If order still has unallocated quantity (shortage)
        if remaining_qty > 0:
            shortage_row = original_row.copy()
            shortage_row["SHORTAGE_FLAG"] = "Partial Shortage"
            shortage_row["PLANNED_QTY"] = float(remaining_qty)
            shortage_row["ALLOCATED CAPACITY"] = 0
            shortage_row["TARGET@100%"] = 0
            shortage_row["TARGET@90%"] = 0
            shortage_row["SPLIT_ORDER_ID"] = f"{split_order_id}_shortage"
            shortage_row["PERIOD"] = period
            shortage_row["SHORTAGE_REASON"] = f"Insufficient capacity: Needed {remaining_qty} more units"
            shortage_row["ALLOCATED EMP ID"] = None
            shortage_row["ALLOCATED EMP NAME"] = None
            shortage_row["ALLOCATED_FRM_LINE"] = None
            shortage_row["ALLOCATED_FRM_FACTORY"] = None
            shortage_row["ALLOCATED_FRM_FLOOR"] = None
            shortage_row["SKILL_TYPE"] = None
            shortage_row["MACHINE_EMP_FACT"] = None
            shortage_row["DESIGNATION"] = None
            new_rows.append(shortage_row)

    return new_rows




def get_unallocated_employees(emp_fact_df, daily_orders, date, period):
    """
    Track unallocated employees for a specific date using threading for performance.
    """

    unallocated_employees = []

    # Loop through all employees to find unallocated ones
    for _, emp in emp_fact_df.iterrows():
        # Calculate what percentage of capacity was utilized
        initial_capacity = emp["average_capacity"]
        remaining_capacity = emp["remaining_capacity"]

        # Skip employees with zero initial capacity (they can't be allocated)
        if initial_capacity <= 0:
            continue

        # Calculate utilization percentage
        utilized_capacity = initial_capacity - remaining_capacity
        utilization_pct = (utilized_capacity / initial_capacity) * 100

        # Round values for cleaner output
        remaining_capacity = round(remaining_capacity, 2)
        utilization_pct = round(utilization_pct, 2)

        # Check if employee was underutilized (less than 100% capacity used)
        if remaining_capacity > 0:
            # Get all orders for this employee's line on this date
            line_orders = daily_orders[daily_orders["LINE"] == emp["line"]]

            # Check if there were any orders matching this employee's code
            matching_code_orders = line_orders[line_orders["CODE"] == emp["code"]]

            # Determine reason for underutilization
            if matching_code_orders.empty:
                reason = "No matching orders for employee's skillset on this date"
                category = "Skillset not required"
            else:
                # There were matching orders but employee still has capacity
                reason = "Partial allocation - capacity exceeds requirements"
                category = "Excess capacity"

            # Create record for this unallocated employee
            unallocated_record = {
                "DATE": date,
                "EMPLOYEE ID": emp["employee_id"],
                "EMPLOYEE NAME": emp["employee_name"],
                "LINE": emp["line"],
                "SECTION": emp["section"],
                "CODE": emp["code"],
                "TYPE": emp["type"],
                "INITIAL CAPACITY": initial_capacity,
                "REMAINING CAPACITY": remaining_capacity,
                "UTILIZATION_PCT": utilization_pct,
                "REASON": reason,
                "CATEGORY": category,
                "PERIOD": period  # Include the period information
            }

            unallocated_employees.append(unallocated_record)

    return unallocated_employees




def process_unallocated_data(unallocated_collection, manning_dataframes):
    """
    Process unallocated employee data across all manning periods using threading
    """
    logger.info("\nProcessing unallocated employee data...")

    results = {}
    unallocated_all_periods = []
    df_name = manning_dataframes["df_name"]

    unallocated_dfs = unallocated_collection[manning_dataframes["df_name"]]

    logger.info(f"Processing unallocated data for {df_name}...")

    period = manning_dataframes["period"]

    combined_unallocated = pd.concat(unallocated_dfs, ignore_index=True)
    if "PERIOD" not in combined_unallocated.columns:
        combined_unallocated["PERIOD"] = period

    results[f"unallocated_{df_name}"] = combined_unallocated
    unallocated_all_periods.append(combined_unallocated)

    # Consolidated view of all unallocated employees
    if unallocated_all_periods:
        all_unallocated = pd.concat(unallocated_all_periods, ignore_index=True)
        results["all_unallocated_employees"] = all_unallocated

        logger.info(f"\nCreated consolidated unallocated employees dataframe with {len(all_unallocated)} total entries")

        # Ensure 'DATE' is a datetime and format to 'YYYY-MM-DD'
        all_unallocated['DATE'] = pd.to_datetime(all_unallocated['DATE'], errors='coerce').dt.strftime('%Y-%m-%d')

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
            }

        # Use ThreadPoolExecutor to convert rows to dicts
        with ThreadPoolExecutor(max_workers=10) as executor:
            data_dicts = list(executor.map(row_to_dict, [row for _, row in all_unallocated.iterrows()]))

        # Chunked insert to DB using threads
        def insert_chunk(chunk_dicts):
            instances = [UnallocatedEmployees(**d) for d in chunk_dicts]
            with transaction.atomic():
                UnallocatedEmployees.objects.bulk_create(instances)

        chunked_data = [data_dicts[i:i + CHUNK_SIZE] for i in range(0, len(data_dicts), CHUNK_SIZE)]

        logger.info(f"Inserting {len(data_dicts)} unallocated records in {len(chunked_data)} chunks...")
        with ThreadPoolExecutor(max_workers=10) as executor:
            executor.map(insert_chunk, chunked_data)

        # Training opportunity report
        training_opportunities = all_unallocated.copy()
        skillset_not_required = training_opportunities[training_opportunities["CATEGORY"] == "Skillset not required"]

        employee_cross_training = skillset_not_required.groupby(
            ["EMPLOYEE ID", "EMPLOYEE NAME", "LINE", "CODE"]
        )["DATE"].count().reset_index()

        employee_cross_training.rename(columns={"DATE": "DAYS_UNALLOCATED"}, inplace=True)
        employee_cross_training = employee_cross_training.sort_values(
            by=["DAYS_UNALLOCATED", "LINE"], ascending=[False, True])

        results["training_opportunities"] = employee_cross_training

        logger.info(f"Created training opportunities report with {len(employee_cross_training)} entries")

    return results




# Global functions for multiprocessing (must not be nested)
def _filter_shortages(df):
    return df[df["SHORTAGE_FLAG"].str.contains("Shortage", na=False)]

def _group_and_aggregate(shortages):
    # Group shortages by code to see which skills have the highest need
    grouped = shortages.groupby(["LINE", "CODE"])["PLANNED_QTY"].sum().reset_index()
    # Sort by quantity (descending)
    grouped = grouped.sort_values(
        by="PLANNED_QTY", ascending=False)
    grouped.rename(columns={"PLANNED_QTY": "SHORTAGE_QTY"}, inplace=True)
    return grouped.sort_values(by="SHORTAGE_QTY", ascending=False)

def analyze_skill_gaps(consolidated_manning_df, all_unallocated_employees):
    """
    Analyze skill gaps by comparing shortages with unallocated employees
    using multiprocessing for large DataFrames.
    """
    logger.info("\nAnalyzing skill gaps...")

    results = {}

    # Determine max workers - limit to avoid memory overhead
    max_workers = min(os.cpu_count() or 4, 4)

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Step 1: Submit task to filter shortages
        future_shortages = executor.submit(_filter_shortages, consolidated_manning_df)

        # Get shortages result
        shortages = future_shortages.result()
        
        if not shortages.empty:
            logger.info(f"Found {len(shortages)} shortage rows. Aggregating...")
            
            # Step 2: Submit task to aggregate shortage data
            future_aggregation = executor.submit(_group_and_aggregate, shortages)
            shortage_by_code = future_aggregation.result()
            
            # Store results
            results["skill_shortages"] = shortage_by_code
            logger.info(f"Created skill shortages report with {len(shortage_by_code)} entries")
        
    return results


# Define the worker function that each process will execute
def process_period(df_manning, period, reference_data):
    
    if 'ALLOCATED CAPACITY' not in df_manning.columns:
        return None
        
    df_manning = df_manning.copy()
    df_manning['PLANNED_QTY'] = df_manning['PLANNED_QTY'].fillna(0).astype(int)
    df_manning['ALLOCATED CAPACITY'] = df_manning['ALLOCATED CAPACITY'].fillna(0).astype(int)

    df_manning = df_manning.groupby(['PLANNED_DATES', 'STYLE', 'LINE', 'SECTION', 'CODE', 'MACHINE_TYPE'], as_index=False)[['PLANNED_QTY', 'ALLOCATED CAPACITY']].sum()
    df_manning['SHORTAGE CAPACITY'] = df_manning['PLANNED_QTY'] - df_manning['ALLOCATED CAPACITY']
    df_manning["Manning_Sheet_Period"] = period

    df_merged = df_manning \
        .merge(reference_data['df_median_capacity'], left_on=["CODE", "LINE", "SECTION"], right_on=["code", "line", "section"], how="left") \
        .merge(reference_data['df_section_avg_capacity'], on=["section", "line"], how="left") \
        .merge(reference_data['df_total_active_operators'], on=["code", "line", "section"], how="left") \
        .merge(reference_data['df_machinist_count'], on=["code", "line", "section"], how="left") \
        .merge(reference_data['df_non_machinist_count'], on=["code", "line", "section"], how="left") \
        .merge(reference_data['machine_data'], on="code", how="left")
    
    # Fix pandas chain assignment warnings by avoiding inplace operations on slices
    df_merged["Median_Average_Capacity"] = df_merged["Median_Average_Capacity"].fillna(df_merged["Section_Average_Capacity"])
    df_merged["Median_Average_Capacity"] = df_merged["Median_Average_Capacity"].replace(0, 1)

    df_merged[["Total_Active_Operators", "Total_Machinist_Available", "Total_Non_Machinist_Available"]] = \
        df_merged[["Total_Active_Operators", "Total_Machinist_Available", "Total_Non_Machinist_Available"]].fillna(0)

    df_merged["Total_Operators_Required"] = (df_merged["PLANNED_QTY"] / df_merged["Median_Average_Capacity"]).round(1)

    df_merged["Machinist_Required"] = df_merged.apply(
        lambda row: row["Total_Operators_Required"] if row["code"] in reference_data['machinist_codes'] else 0, axis=1)
    df_merged["Non_Machinist_Required"] = df_merged.apply(
        lambda row: row["Total_Operators_Required"] if row["code"] not in reference_data['machinist_codes'] else 0, axis=1)

    df_merged.drop_duplicates(inplace=True)
    return df_merged



def chunk_dataframe(df, chunk_size=10000):
    chunks = np.array_split(df, max(1, len(df) // chunk_size))
    return chunks

def process_general_info(df_manning, df_emp_fact, period):

    # Global filter of Employee Fact Data (Primary and Secondary only)
    df_emp_fact = df_emp_fact[df_emp_fact["type"].isin(["Primary", "Secondary"])]

    # Precomputed shared data for merging - these will be passed to each process
    df_median_capacity = df_emp_fact.groupby(["code", "line", "section"], as_index=False)["average_capacity"].median()
    df_median_capacity.rename(columns={"average_capacity": "Median_Average_Capacity"}, inplace=True)

    df_section_avg_capacity = df_emp_fact.groupby(["section", "line"], as_index=False)["average_capacity"].median()
    df_section_avg_capacity.rename(columns={"average_capacity": "Section_Average_Capacity"}, inplace=True)

    df_total_active_operators = df_emp_fact.groupby(["code", "line", "section"], as_index=False)["employee_id"].count()
    df_total_active_operators.rename(columns={"employee_id": "Total_Active_Operators"}, inplace=True)

    df_machinist_count = df_emp_fact[df_emp_fact["designation"] == "Machinist"].groupby(["code", "line", "section"], as_index=False)["employee_id"].count()
    df_machinist_count.rename(columns={"employee_id": "Total_Machinist_Available"}, inplace=True)

    df_non_machinist_count = df_emp_fact[df_emp_fact["designation"] != "Machinist"].groupby(["code", "line", "section"], as_index=False)["employee_id"].count()
    df_non_machinist_count.rename(columns={"employee_id": "Total_Non_Machinist_Available"}, inplace=True)

    machine_data = df_emp_fact.groupby("code")["machine"].unique().reset_index()
    machine_data["machine"] = machine_data["machine"].apply(lambda x: ', '.join([m for m in x if m not in ["Unknown", "-"]]))

    machinist_codes = set(df_emp_fact[df_emp_fact["designation"] == "Machinist"]["code"].values)
    
    # Package all reference data into a dictionary to pass to worker processes
    reference_data = {
        'df_median_capacity': df_median_capacity,
        'df_section_avg_capacity': df_section_avg_capacity,
        'df_total_active_operators': df_total_active_operators,
        'df_machinist_count': df_machinist_count,
        'df_non_machinist_count': df_non_machinist_count,
        'machine_data': machine_data,
        'machinist_codes': machinist_codes
    }

    # Use ProcessPoolExecutor for parallel processing
    # Limit max_workers to CPU count minus 1 for system stability
    max_workers = max(1, mp.cpu_count() - 1)
    
    results = []

    # Split df_manning into chunks
    chunks = chunk_dataframe(df_manning, max_workers)

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        process_func = partial(process_period, period=period, reference_data=reference_data)
        
        futures = [executor.submit(process_func, chunk) for chunk in chunks]

        for future in futures:
            result = future.result()
            if result is not None:
                results.append(result)
    
    # No need for locks since we're collecting results after all processes complete
    truncate_table(ManningGeneralInfo)
    
    if not results:
        return []
        
    df_final_Information = pd.concat(results, ignore_index=True)

    drop_c = ["OC NO", "ORDER NO", "BUYER", "COLOR", "WEEK", "PLANNED DATES", "FACTORY", "FLOOR",
              "UNNAMED: 0", "OP_SEQ", "OPERATION", "SAM", "MACHINIST", "SMV"]
    df_final_Information.drop(columns=[col for col in drop_c if col in df_final_Information.columns], inplace=True)

    def safe_get(value, default=0):
        if pd.isna(value):
            return default
        return value
    
    df_final_Information.drop_duplicates(inplace=True)

    # Prepare bulk data dicts
    data_dicts = df_final_Information.apply(lambda row: {
        'style': row['STYLE'],
        'line': row['LINE'],
        'section': row['SECTION'],
        'code': row['CODE'],
        'planned_qty': row['PLANNED_QTY'],
        'allocated_capacity': row['ALLOCATED CAPACITY'],
        'shortage_capacity': row['SHORTAGE CAPACITY'],
        'forecast_period': row['Manning_Sheet_Period'],
        'median_average_capacity': safe_get(row['Median_Average_Capacity'] if row['Median_Average_Capacity'] else 0),
        'section_average_capacity': safe_get(row['Section_Average_Capacity'] if row['Section_Average_Capacity'] else 0),
        'total_active_operators': safe_get(int(row['Total_Active_Operators']) if row['Total_Active_Operators'] else 0),
        'machinist_available': safe_get(float(row['Total_Machinist_Available']) if row['Total_Machinist_Available'] else 0),
        'non_machinist_available': safe_get(float(row['Total_Non_Machinist_Available']) if row['Total_Non_Machinist_Available'] else 0),
        'total_operators_required': safe_get(float(row['Total_Operators_Required']) if row['Total_Operators_Required'] else 0),
        'machinist_required': safe_get(float(row['Machinist_Required']) if row['Machinist_Required'] else 0),
        'non_machinist_required': safe_get(float(row['Non_Machinist_Required']) if row['Non_Machinist_Required'] else 0),
        'machine': row['MACHINE_TYPE'],
        'planned_dates': row['PLANNED_DATES']
    }, axis=1).tolist()

    # Use CHUNK_SIZE for bulk insertion to avoid memory issues
    for i in range(0, len(data_dicts), CHUNK_SIZE):
        chunk_dicts = data_dicts[i:i + CHUNK_SIZE]
        model_instances = [ManningGeneralInfo(**d) for d in chunk_dicts]
        with transaction.atomic():
            ManningGeneralInfo.objects.bulk_create(model_instances)

    return results