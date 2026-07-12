import logging
logger = logging.getLogger(__name__)

import os
import django

# Setup Django before importing models
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import time
import numpy as np
import pandas as pd
import multiprocessing as mp

from datetime import datetime
from functools import partial
from concurrent.futures import ProcessPoolExecutor, as_completed, ThreadPoolExecutor

from django.db import transaction

from .models import ManningGeneralInfo
from config.utils import truncate_table

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
            (df["planned_dates"] >= today) &
            (df["planned_dates"] <= date_thresholds["30_days"])
        ]
    if period == 7:
        periodFilter = df[
            (df["planned_dates"] >= today) &
            (df["planned_dates"] <= date_thresholds["7_days"])
        ]
    if period == 1:
        periodFilter = df[
            (df["planned_dates"] >= today) &
            (df["planned_dates"] <= date_thresholds["1_days"])
        ]

    filtered_dfs = {
        f"{period}_days": periodFilter
    }
    return filtered_dfs


def process_single_df(key, df):
    grouped = df.groupby(
        ["oc_no", "order_no", "buyer", "style", "fabric_article", "line", "week", "planned_dates",],
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
    final_df.drop_duplicates(inplace=True, ignore_index=True)
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
    
    final_df.drop_duplicates(inplace=True, ignore_index=True)

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
    final_df.drop_duplicates(inplace=True, ignore_index=True)

    return final_df


def run_manning_allocation(PERIOD, manning_df, emp_fact_df, df_load_plan_transformed, max_workers=None):
    """
    Main function to process manning allocation with multiprocessing
    """
    start_time = time.time()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"[{timestamp}] Starting optimized manning allocation process...")
    

    # Determine optimal number of workers if not specified
    if not max_workers:
        max_workers = max(1, min(mp.cpu_count() - 1, 4))  # Use N-1 cores, max 4
    
    logger.info(f"Using {max_workers} worker processes on system with {mp.cpu_count()} logical CPUs")
    
    results = {}

    suffix = str(PERIOD)
    manning_df = manning_df.copy()
    df_name = f"manning_{suffix}_df"

    
    # Pre-filter and optimize employee dataframe
    emp_fact_df_original = emp_fact_df.copy()
    emp_fact_df_original = emp_fact_df_original[emp_fact_df_original["type"].isin(["Primary", "Secondary"])]
    
    # Convert string columns to category for memory efficiency
    # for col in emp_fact_df.select_dtypes(include=['object']).columns:
    #     emp_fact_df[col] = emp_fact_df[col].astype('category')
    
    all_processed_dfs = []
    unallocated_collection = {}
        
    try:
        if manning_df is not None:
            logger.info(f"Processing manning data for period {PERIOD}...")
            df_name = f"manning_{suffix}_df"
            
            # Pre-process the dataframe
            manning_df["PLANNED_DATES"] = pd.to_datetime(manning_df["PLANNED_DATES"])
            
            # Prepare allocation columns
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
                        manning_df[col] = PERIOD
                    else:
                        manning_df[col] = None
            
            # Process the dataframe with multiprocessing
            updated_manning_df, unallocated_employees = process_manning_dataframe_parallel(
                manning_df,
                emp_fact_df_original.copy(),
                PERIOD,
                max_workers
            )
            df_load_plan_transformed.columns = df_load_plan_transformed.columns.str.upper()
            df_load_plan_transformed = df_load_plan_transformed.rename(columns={'FABRIC_ARTICLE': 'COLOR'})
            df_subset = df_load_plan_transformed[["STYLE", "COLOR", "OC_NO", "LINE", "ORDER_NO", "BUYER", "WEEK", "RAW_STYLE", "RAW_FABRIC_ARTICLE", "RAW_OC_NO"]]
            df_subset = df_subset.drop_duplicates(subset=["STYLE", "COLOR", "OC_NO", "LINE", "ORDER_NO", "BUYER", "WEEK",], keep="first")

            # Merge dfA with dfB to bring raw_* columns where style, color, and oc_no match
            updated_manning_df = updated_manning_df.merge(
                df_subset[["STYLE", "COLOR", "OC_NO", "LINE", "ORDER_NO", "BUYER", "WEEK", "RAW_STYLE", "RAW_FABRIC_ARTICLE", "RAW_OC_NO"]],
                on=["STYLE", "COLOR", "OC_NO", "LINE", "ORDER_NO", "BUYER", "WEEK",],
                how="left"
            )
            updated_manning_df.drop_duplicates(inplace=True, ignore_index=True)
            
            # Save the results
            results[f"updated_manning_{suffix}_df"] = updated_manning_df
            unallocated_collection[df_name] = unallocated_employees
            all_processed_dfs.append(updated_manning_df)

            logger.info(f"Successfully processed period {PERIOD}:")
            logger.info(f"  - Created manning sheet with {len(updated_manning_df)} rows")
            logger.info()
        else:
            logger.info(f"Warning: Dataframe for period {PERIOD} not found, skipping.")
    except Exception as e:
        logger.info(f"Error processing period {PERIOD}: {e}")
    
    # Process unallocated data
    unallocated_results = process_unallocated_data(unallocated_collection, {"suffix": str(PERIOD), "period": PERIOD, "df": manning_df, "df_name": df_name})
    results.update(unallocated_results)
    
    # Create consolidated dataframe
    try:
        if all_processed_dfs:
            consolidated_df = pd.concat(all_processed_dfs, ignore_index=True)
            for col in ['OC NO', 'BUYER', 'STYLE', 'COLOR']:
                if col in consolidated_df.columns:
                    consolidated_df[col] = consolidated_df[col].str.upper()

            results["consolidated_manning_df"] = consolidated_df
            
            if "all_unallocated_employees" in results:
                skill_gap_results = analyze_skill_gaps(consolidated_df, results["all_unallocated_employees"])
                results.update(skill_gap_results)
            
            logger.info(f"Successfully created consolidated manning dataframe with {len(consolidated_df)} total rows")
        else:
            logger.info("No dataframes were processed successfully for consolidation")
    except Exception as e:
        logger.info(f"Error creating consolidated dataframe: {e}")
    
    end_time = time.time()
    elapsed_time = end_time - start_time
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"[{timestamp}] Manning allocation process completed in {elapsed_time:.2f} seconds.")
    
    return results





def process_manning_dataframe_parallel(manning_df, emp_fact_df, period, max_workers=None):
    """Process the manning dataframe using parallel processing with fixed capacity tracking
    
    Args:
        manning_df: DataFrame containing manning data
        emp_fact_df: DataFrame containing employee data
        period: Time period for processing
        max_workers: Maximum number of worker processes (defaults to CPU count if None)
    
    Returns:
        Tuple of (updated_manning_df, unallocated_employees_list)
    """
    unique_dates = sorted(manning_df["PLANNED_DATES"].unique())
    logger.info(f"Processing {len(unique_dates)} unique dates in parallel")
    
    logger.info(f"Using {max_workers} worker processes")
    
    # Create a partial function with fixed arguments
    process_date_partial = partial(
        process_date_wrapper, 
        manning_df=manning_df, 
        emp_fact_df=emp_fact_df, 
        period=period
    )
    
    # Using ProcessPoolExecutor for parallel processing
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Map process_date to all dates and collect results
        results = list(executor.map(process_date_partial, unique_dates))
    
    # Split results into manning dataframes and unallocated employees
    updated_manning_dfs = []
    unallocated_employees_list = []
    
    for date_df, unallocated_df in results:
        if date_df is not None and not date_df.empty:
            updated_manning_dfs.append(date_df)
        if unallocated_df is not None and not unallocated_df.empty:
            unallocated_employees_list.append(unallocated_df)
    
    # Combine results
    if updated_manning_dfs:
        updated_manning_df = pd.concat(updated_manning_dfs, ignore_index=True)
    else:
        updated_manning_df = pd.DataFrame(columns=manning_df.columns)
    
    return updated_manning_df, unallocated_employees_list

def process_date_wrapper(date, manning_df, emp_fact_df, period):
    """Wrapper function for process_date to handle exceptions
    
    This wrapper is needed because we can't directly use a try-except block
    with executor.map()
    """
    try:
        date_df, unallocated_df = process_date(date, manning_df, emp_fact_df, period)
        # print(f"Completed date: {date.strftime('%Y-%m-%d')}")
        return date_df, unallocated_df
    except Exception as e:
        logger.info(f"Error processing date {date}: {e}")
        return None, None



def process_date(date, manning_df, emp_fact_df, period):
    """Process a single date's data with fixed capacity tracking"""
    logger.info(f"Processing date: {date}")
    
    # Dictionary to track capacity used per employee
    employee_used_capacity = {}
    
    # Create a copy to avoid modifying the original
    emp_fact_df_copy = emp_fact_df.copy()
    
    # Initialize employee capacities
    for idx, emp_row in emp_fact_df_copy.iterrows():
        emp_id = emp_row["employee_id"]
        skill_capacity = emp_row["average_capacity"]
        
        # Initialize used capacity tracking
        if emp_id not in employee_used_capacity:
            employee_used_capacity[emp_id] = 0
            
        # Set initial remaining capacity 
        emp_fact_df_copy.at[idx, "remaining_capacity"] = skill_capacity
    
    # Get orders for this date
    daily_orders = manning_df[manning_df["PLANNED_DATES"] == date].copy()
    
    # Group orders by line, section, code
    grouped_orders = daily_orders.groupby(['LINE', 'SECTION', 'CODE'])
    
    new_rows = []
    
    # Process each group
    for (line, section, code), group_orders in grouped_orders:
        group_rows = process_order_group(
            line, section, code, group_orders, emp_fact_df_copy,
            employee_used_capacity, date, period
        )
        new_rows.extend(group_rows)
    
    # Get unallocated employees
    unallocated_employees = get_unallocated_employees(emp_fact_df_copy, daily_orders, date, period)
    unallocated_df = pd.DataFrame(unallocated_employees) if unallocated_employees else None
    
    unallocated_df.drop_duplicates(inplace=True, ignore_index=True)
    # Create dataframe for this date's results
    date_df = pd.DataFrame(new_rows) if new_rows else None
    
    return date_df, unallocated_df


def get_prioritized_employees(emp_df, employee_used_capacity, line=None, code=None, section=None, emp_type=None):
    """Get prioritized employees with optimized filtering"""
    # Make copy only of required columns to reduce memory usage
    required_cols = ["employee_id", "employee_name", "average_capacity", "line", 
                     "code", "section", "type", "factory", "floor", "machine", "designation"]
    emp_df_copy = emp_df[required_cols].copy()
    
    # Calculate remaining capacity in vectorized operation
    emp_ids = emp_df_copy["employee_id"].values
    skill_capacities = emp_df_copy["average_capacity"].values
    
    # Vectorized calculation of effective remaining capacity
    already_used = np.array([employee_used_capacity.get(emp_id, 0) for emp_id in emp_ids])
    remaining = np.maximum(0, skill_capacities - already_used)
    emp_df_copy["effective_remaining_capacity"] = remaining
    
    # Apply all filters at once for efficiency
    query = (emp_df_copy["effective_remaining_capacity"] > 0)
    if line:
        query &= (emp_df_copy["line"] == line)
    if code:
        query &= (emp_df_copy["code"] == code)
    if section:
        query &= (emp_df_copy["section"] == section)
    if emp_type:
        query &= (emp_df_copy["type"] == emp_type)
    
    filtered_df = emp_df_copy[query].copy()
    
    # Sort efficiently
    filtered_df = filtered_df.sort_values(
        by=["type", "effective_remaining_capacity"],
        ascending=[True, False]
    )
    
    return filtered_df



def process_order_group(line, section, code, group_orders, emp_fact_df, employee_used_capacity, date, period):
    """Process a group of orders with fixed capacity tracking"""
    # Calculate total quantity for this group
    total_planned_qty = group_orders['PLANNED_QTY'].sum()
    new_rows = []
    
    # Get available employees using reference implementation logic
    available_employees = get_prioritized_employees(
        emp_df=emp_fact_df,
        employee_used_capacity=employee_used_capacity,
        line=line,
        code=code,
        section=section
    )
    
    if available_employees.empty:
        # Handle shortage case - same as before
        for _, row in group_orders.iterrows():
            shortage_row = row.copy()
            shortage_row["SHORTAGE_FLAG"] = "Shortage Unresolved"
            
            # Determine reason for shortage
            any_matching_code = emp_fact_df[emp_fact_df["code"] == code].shape[0] > 0
            if not any_matching_code:
                shortage_row["SHORTAGE_REASON"] = f"No employees with CODE={code} found in any line"
            else:
                other_lines = set(emp_fact_df[
                    (emp_fact_df["code"] == code) &
                    (emp_fact_df["line"] != line)
                ]["line"].unique())
                
                if other_lines:
                    shortage_row["SHORTAGE_REASON"] = f"CODE={code} found only in lines: {', '.join(other_lines)}"
                else:
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
        return new_rows
    
    # Pre-allocate employees - similar to reference implementation
    employee_allocations = []
    remaining_total_qty = total_planned_qty
    
    # Allocate capacity, matching reference implementation logic
    for _, emp in available_employees.iterrows():
        emp_id = emp["employee_id"]
        skill_capacity = emp["average_capacity"]
        already_used = employee_used_capacity.get(emp_id, 0)
        available_capacity = skill_capacity - already_used
        
        if available_capacity > 0 and remaining_total_qty > 0:
            allocation = min(remaining_total_qty, available_capacity)
            allocation = round(allocation, 2)
            
            if allocation > 0:
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
                    "SKILL_CAPACITY": skill_capacity
                })
                
                remaining_total_qty -= allocation
                remaining_total_qty = round(remaining_total_qty, 2)
                
                # Update used capacity
                employee_used_capacity[emp_id] = already_used + allocation

                emp_fact_df.loc[
                    (emp_fact_df["employee_id"] == emp["employee_id"]) &
                    (emp_fact_df["code"] == emp["code"]) &
                    (emp_fact_df["type"] == emp["type"]),
                    "remaining_capacity"
                ] = available_capacity - allocation
                
                # CRITICAL FIX: Update remaining capacity for ALL entries with this employee ID
                # This ensures consistency with the reference implementation
                emp_fact_df.loc[
                    emp_fact_df["employee_id"] == emp_id,
                    "remaining_capacity"
                ] = emp_fact_df.apply(
                    lambda row: max(0, row["average_capacity"] - employee_used_capacity[emp_id])
                    if row["employee_id"] == emp_id else row["remaining_capacity"],
                    axis=1
                )
    
    # Process individual orders - same as before
    sorted_orders = group_orders.sort_values(by="PLANNED_QTY", ascending=False)
    current_emp_index = 0
    
    for _, row in sorted_orders.iterrows():
        original_row = row.copy()
        planned_qty = row["PLANNED_QTY"]
        remaining_qty = planned_qty
        
        if not employee_allocations:
            shortage_row = original_row.copy()
            shortage_row["SHORTAGE_FLAG"] = "Shortage"
            shortage_row["SHORTAGE_REASON"] = f"No employees available for {line}/{section}/{code}"
            new_rows.append(shortage_row)
            continue
        
        split_count = 0
        split_order_id = f"{row['ORDER_NO']}_{row['STYLE']}_{line}_{code}_{date.strftime('%Y%m%d')}"
        
        while remaining_qty > 0 and current_emp_index < len(employee_allocations):
            current_emp = employee_allocations[current_emp_index]
            order_allocation = min(remaining_qty, current_emp["ALLOCATION"])
            
            if order_allocation > 0:
                split_count += 1
                current_row = original_row.copy()
                current_row["SPLIT_ORDER_ID"] = f"{split_order_id}_part{split_count}"
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
                
                remaining_qty -= order_allocation
                remaining_qty = round(remaining_qty, 2)
                current_emp["ALLOCATION"] -= order_allocation
                current_emp["ALLOCATION"] = round(current_emp["ALLOCATION"], 2)
                
                new_rows.append(current_row)
            
            if current_emp["ALLOCATION"] <= 0.001:
                current_emp_index += 1
        
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
    """Get unallocated employees with vectorized operations"""
    unallocated_employees = []
    
    # # Filter employees with capacity > 0
    # has_capacity = emp_fact_df["average_capacity"] > 0
    # relevant_emps = emp_fact_df[has_capacity]
    
    for _, emp in emp_fact_df.iterrows():
        initial_capacity = emp["average_capacity"]
        remaining_capacity = emp["remaining_capacity"]
        
        utilized_capacity = initial_capacity - remaining_capacity
        utilization_pct = (utilized_capacity / initial_capacity) * 100
        remaining_capacity = round(remaining_capacity, 2)
        utilization_pct = round(utilization_pct, 2)
        
        if remaining_capacity > 0:
            # Efficient filtering of orders
            line_orders = daily_orders[daily_orders["LINE"] == emp["line"]]
            matching_code_orders = line_orders[line_orders["CODE"] == emp["code"]]
            
            if matching_code_orders.empty:
                reason = "No matching orders for employee's skillset on this date"
                category = "Skillset not required"
            else:
                reason = "Partial allocation - capacity exceeds requirements"
                category = "Excess capacity"
            
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
                "PERIOD": period
            }
            
            unallocated_employees.append(unallocated_record)
    
    return unallocated_employees

def process_unallocated_data(unallocated_collection, manning_dataframes):
    """Process unallocated employee data with optimizations"""
    logger.info("\nProcessing unallocated employee data...")
    results = {}
    unallocated_all_periods = []
    df_name = manning_dataframes["df_name"]

    unallocated_dfs = unallocated_collection[manning_dataframes["df_name"]]
    logger.info(f"Processing unallocated data for {df_name}...")

    period = manning_dataframes["period"]
    
    if unallocated_dfs:
        combined_unallocated = pd.concat(unallocated_dfs, ignore_index=True)
    else:
        combined_unallocated = pd.DataFrame(columns=['DATE', 'EMPLOYEE ID', 'EMPLOYEE NAME', 'LINE', 'SECTION', 'CODE',
       'TYPE', 'INITIAL CAPACITY', 'REMAINING CAPACITY', 'UTILIZATION_PCT',
       'REASON', 'CATEGORY', 'PERIOD'])  # or define expected columns if needed
    
    if "PERIOD" not in combined_unallocated.columns:
        combined_unallocated["PERIOD"] = period

    results[f"unallocated_{df_name}"] = combined_unallocated
    unallocated_all_periods.append(combined_unallocated)

    if unallocated_all_periods:
        all_unallocated = pd.concat(unallocated_all_periods, ignore_index=True)
        results["all_unallocated_employees"] = all_unallocated
        
        logger.info(f"\nCreated consolidated unallocated employees dataframe with {len(all_unallocated)} total entries")
        # print(f"Saved to: {consolidated_path}")
        
        # More efficient training opportunities calculation
        training_opportunities = all_unallocated.copy()
        skillset_not_required = training_opportunities[
            training_opportunities["CATEGORY"] == "Skillset not required"]
        
        # Optimized groupby operation
        employee_cross_training = (
            skillset_not_required
            .groupby(["EMPLOYEE ID", "EMPLOYEE NAME", "LINE", "CODE"])
            .size()
            .reset_index(name="DAYS_UNALLOCATED")
            .sort_values(by=["DAYS_UNALLOCATED", "LINE"], ascending=[False, True])
        )
        
        results["training_opportunities"] = employee_cross_training
        
        logger.info(f"Created training opportunities report with {len(employee_cross_training)} entries")
        # print(f"Saved to: {training_path}")
    
    return results

def analyze_skill_gaps(consolidated_manning_df, all_unallocated_employees):
    """Analyze skill gaps with optimized operations"""
    results = {}
    logger.info("\nAnalyzing skill gaps...")
    
    # Optimized boolean filtering
    shortages = consolidated_manning_df[consolidated_manning_df["SHORTAGE_FLAG"].str.contains("Shortage")]
    
    if not shortages.empty:
        # Optimized groupby operation
        shortage_by_code = (
            shortages
            .groupby(["LINE", "CODE"])["PLANNED_QTY"]
            .sum()
            .reset_index()
            .sort_values(by="PLANNED_QTY", ascending=False)
            .rename(columns={"PLANNED_QTY": "SHORTAGE_QTY"})
        )
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

    df_merged.drop_duplicates(inplace=True, ignore_index=True)
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
    
    df_final_Information.drop_duplicates(inplace=True, ignore_index=True)

    if (len(df_final_Information) > 0):
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