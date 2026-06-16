import os
import math
import django

import time
import numpy as np
import pandas as pd
import multiprocessing as mp

from datetime import datetime


from .models import ManningGeneralInfo
from backend_laguna.utils import truncate_table

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
def filter_by_date_ranges_v6(df, today, date_thresholds, period):

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

    grouped = periodFilter.groupby(
        ["oc_no", "order_no", "buyer", "style", "fabric_article", "line", "week", "planned_dates"],
        as_index=False, sort = None
    )["planned_qty"].sum()

    grouped = grouped.rename(columns={'fabric_article': 'color'})

    mapped_values = pd.DataFrame(df["line"].apply(map_factory_floor).tolist(), index=df.index, columns=["FACTORY", "FLOOR"])

    # Then assign these columns to the original DataFrame
    grouped["FACTORY"] = mapped_values["FACTORY"]
    grouped["FLOOR"] = mapped_values["FLOOR"]
    grouped["Workdays"] = 6
    return grouped


def process_single_manning_df_v6(df, df_Style_OB):
    # Merge with Style OB data
    manning = df.merge(df_Style_OB, left_on=["style"], right_on=["style"], how="inner") # Removed color

    # manning = manning.drop_duplicates(inplace=True)

    # Sort by specified columns
    # manning = manning.sort_values(by=["style", "color", "section", "op_seq", "oc_no", "order_no", "line"])

    # Drop unnecessary columns
    manning = manning.drop(columns=["Matched Style", "UNNAMED: 0"], errors='ignore')

    # PRESERVE ORIGINAL ORDER - Store original order and group order
    manning['_original_order'] = range(len(manning))

    # Get first appearance order of each group to preserve group order
    first_appearance = manning.drop_duplicates(
        subset=["oc_no", "order_no", "buyer", "style", "color", "line", "section"]
    )[["oc_no", "order_no", "buyer", "style", "color", "line", "section", "_original_order"]]
    first_appearance = first_appearance.rename(columns={'_original_order': '_group_order'})

    # Group and sort
    # manning = manning.groupby(
    #     ["oc_no", "order_no", "buyer", "style", "color", "line", "section"], as_index=False
    # ).apply(lambda x: x.sort_values(by=["op_seq", "planned_dates"])).reset_index(drop=True)

    # Perform groupby operation
    manning = manning.groupby(
        ["oc_no", "order_no", "buyer", "style", "color", "line", "section"], as_index=False
    ).apply(lambda x: x.sort_values(by=["_original_order"])).reset_index(drop=True)

    # Merge back with group order and sort to preserve original sequence
    manning = manning.merge(first_appearance, on=["oc_no", "order_no", "buyer", "style", "color", "line", "section"])
    manning = manning.sort_values('_group_order').drop(columns=['_original_order', '_group_order']).reset_index(drop=True)

    # Convert column names to uppercase
    manning.columns = manning.columns.str.upper()

    # Apply the simple sorting
    manning_sorted = sort_by_op_seq_simple(manning)

    return manning_sorted


def sort_by_op_seq_simple(df):
    """
    Sort by OP_SEQ while keeping groups in their exact original order
    """
    # Define grouping columns
    grouping_cols = ['OC_NO', 'ORDER_NO', 'BUYER', 'STYLE', 'COLOR',
                    'LINE', 'WEEK', 'PLANNED_DATES', 'PLANNED_QTY',
                    'FACTORY', 'FLOOR', 'SECTION']

    # Add original index to track order
    df_copy = df.copy().reset_index(drop=True)
    df_copy['_original_index'] = df_copy.index

    # Find unique groups in order of first appearance
    seen_groups = set()
    ordered_groups = []

    for _, row in df_copy.iterrows():
        # Create group identifier
        group_id = tuple(row[col] for col in grouping_cols)

        if group_id not in seen_groups:
            ordered_groups.append(group_id)
            seen_groups.add(group_id)

    # Process each group in order
    sorted_groups = []

    for group_id in ordered_groups:
        # Filter for this group
        group_filter = True
        for i, col in enumerate(grouping_cols):
            group_filter = group_filter & (df_copy[col] == group_id[i])

        # Get group data and sort by OP_SEQ
        group_data = df_copy[group_filter].sort_values('OP_SEQ')
        sorted_groups.append(group_data)

    # Combine all groups
    result = pd.concat(sorted_groups, ignore_index=True)
    result = result.drop('_original_index', axis=1)

    return result



def run_manning_allocation_v6(PERIOD, manning_df, emp_fact_df, df_load_plan_transformed):
    """
    Main function to run the manning allocation process

    Parameters:
    -----------------------------------------------------------------------------------
    manning_dataframes_dict : dict
        Dictionary with keys as period suffixes (0, 1, 7, etc.) and values as dataframes
        Example: {"0": manning_0, "1": manning_1, "7": manning_7, etc.}
        These should be your existing dataframes
    emp_fact_df : pandas.DataFrame
        Employee data with capacity information
    df_unique_smv : pandas.DataFrame, optional
        SMV data for styles
    output_dir : str, optional
        Directory to save output files

    Returns:
    --------
    dictaAAaAA
        Dictionary containing all processed dataframes and analysis results
        Access them by keys like "consolidated_manning_df", "updated_manning_0_df", etc.
    """
    # Add timestamp for logging
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] Starting manning allocation process...")

    # Dictionary to store all results
    results = {}

    suffix = str(PERIOD)
    manning_df = manning_df.copy()
    df_name = f"manning_{suffix}_df"

    # Pre-filter and optimize employee dataframe
    emp_fact_df_original = emp_fact_df.copy()
    emp_fact_df_original = emp_fact_df_original[emp_fact_df_original["type"].isin(["Primary", "Secondary"])]

    all_processed_dfs = []
    unallocated_collection = {}


    try:
        # Check if the dataframe exists
        if manning_df is not None:
            print(f"Processing manning data for period {PERIOD}...")

            # Store the df_name for compatibility with original code
            df_name = f"manning_{suffix}_df"

            # Process the manning dataframe
            updated_manning_df, unallocated_employees = process_manning_dataframe(
                manning_df,
                emp_fact_df_original.copy(),
                PERIOD
            )

            # Store results
            results[f"updated_manning_{suffix}_df"] = updated_manning_df

            # Store unallocated employees in collection using the original df_name format
            unallocated_collection[df_name] = unallocated_employees

            # Add to our collection for consolidation
            all_processed_dfs.append(updated_manning_df)

            print(f"Successfully processed period {PERIOD}:")
            print(f"  - Created manning sheet with {len(updated_manning_df)} rows")
        else:
            print(f"Warning: Dataframe for period {PERIOD} not found, skipping.")

    except Exception as e:
        print(f"Error processing period {PERIOD}: {e}")

    # Process unallocated employee data
    unallocated_results = process_unallocated_data(unallocated_collection, {"suffix": str(PERIOD), "period": PERIOD, "df": manning_df, "df_name": df_name})
    results.update(unallocated_results)

    # Create consolidated dataframe from all processed dataframes
    try:
        if all_processed_dfs:
            # Consolidate all dataframes
            consolidated_df = pd.concat(all_processed_dfs, ignore_index=True)

            # Standardize some columns to uppercase
            for col in ['OC NO', 'BUYER', 'STYLE', 'COLOR']:
                if col in consolidated_df.columns:
                    consolidated_df[col] = consolidated_df[col].str.upper()


            # Store in results
            results["consolidated_manning_df"] = consolidated_df

            # Analyze skill gaps if possible
            if "all_unallocated_employees" in results:
                skill_gap_results = analyze_skill_gaps(consolidated_df, results["all_unallocated_employees"])
                results.update(skill_gap_results)

            print(f"Successfully created consolidated manning dataframe with {len(consolidated_df)} total rows")

        else:
            print("No dataframes were processed successfully for consolidation")
    except Exception as e:
        print(f"Error creating consolidated dataframe: {e}")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] Manning allocation process completed.")

    return results



def analyze_skill_gaps(consolidated_manning_df, all_unallocated_employees):
    """Analyze skill gaps with optimized operations"""
    try:
        results = {}
        print("\nAnalyzing skill gaps...")
        
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
            print(f"Created skill shortages report with {len(shortage_by_code)} entries")
        return results
    except Exception as e:
        print(f"Error in analyze_skill_gaps function: {e}")


def process_unallocated_data(unallocated_collection, manning_dataframes):
    """Process unallocated employee data with optimizations"""
    try: 
        print("\nProcessing unallocated employee data...")
        results = {}
        unallocated_all_periods = []
        df_name = manning_dataframes["df_name"]

        unallocated_dfs = unallocated_collection[manning_dataframes["df_name"]]
        print(f"Processing unallocated data for {df_name}...")

        period = manning_dataframes["period"]

        if unallocated_dfs:
            combined_unallocated = pd.concat(unallocated_dfs, ignore_index=True)
        else:
            combined_unallocated = pd.DataFrame(columns=['DATE', 'employee_id', 'EMPLOYEE NAME', 'LINE', 'SECTION', 'CODE',
                'TYPE', 'INITIAL CAPACITY', 'REMAINING CAPACITY', 'UTILIZATION_PCT',
                'REASON', 'CATEGORY', 'PERIOD'])  # or define expected columns if needed

        if "PERIOD" not in combined_unallocated.columns:
            combined_unallocated["PERIOD"] = period

        results[f"unallocated_{df_name}"] = combined_unallocated
        unallocated_all_periods.append(combined_unallocated)

        if unallocated_all_periods:
            all_unallocated = pd.concat(unallocated_all_periods, ignore_index=True)
            results["all_unallocated_employees"] = all_unallocated
            
            print(f"\nCreated consolidated unallocated employees dataframe with {len(all_unallocated)} total entries")
            # print(f"Saved to: {consolidated_path}")
            
            # More efficient training opportunities calculation
            training_opportunities = all_unallocated.copy()
            skillset_not_required = training_opportunities[
                training_opportunities["CATEGORY"] == "Skillset not required"]
            
            # Optimized groupby operation
            employee_cross_training = (
                skillset_not_required
                .groupby(["employee_id", "EMPLOYEE NAME", "LINE", "CODE"])
                .size()
                .reset_index(name="DAYS_UNALLOCATED")
                .sort_values(by=["DAYS_UNALLOCATED", "LINE"], ascending=[False, True])
            )
            
            results["training_opportunities"] = employee_cross_training
            
            print(f"Created training opportunities report with {len(employee_cross_training)} entries")
        
        return results
    except Exception as e:
        print(f"Error in process_unallocated_data function: {e}")


def process_manning_dataframe(manning_df, emp_fact_df, period): #df_unique_smv=None
    """
    Process a single manning dataframe

    Parameters:
    -----------
    manning_df : pandas.DataFrame
        Manning dataframe to process
    emp_fact_df : pandas.DataFrame
        Employee data with capacity information
    period : int
        Period value for this dataframe
    df_unique_smv : pandas.DataFrame, optional
        SMV data for styles

    Returns:
    --------
    tuple
        (updated_manning_df, unallocated_employees_list)
    """

    # manning_df = manning_df.copy()
    # manning_df["PLANNED_DATES"] = pd.to_datetime(manning_df["PLANNED_DATES"])

    # # ADD: Preserve original order
    # manning_df = manning_df.reset_index(drop=True)
    # manning_df['_global_original_index'] = manning_df.index

    # changed 17-06

    manning_df = manning_df.copy()
    manning_df = manning_df.reset_index(drop=True)
    manning_df['_global_original_index'] = manning_df.index
    manning_df["PLANNED_DATES"] = pd.to_datetime(manning_df["PLANNED_DATES"])

    updated_manning_df = pd.DataFrame(columns=manning_df.columns)

    # Add allocation columns
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
                manning_df[col] = period
            else:
                manning_df[col] = None

    unique_dates = manning_df["PLANNED_DATES"].unique()
    unallocated_employees_list = []
    all_processed_rows = []  # ADD: Store all rows for final sorting

    for date in sorted(unique_dates):
        print(f"Processing date: {date}")

        # NEW LOGIC: Track capacity used per employee by skill type
        # Structure: {emp_id: {skill_type_code: used_amount}}
        employee_used_capacity = {}

        # Reset remaining capacity with new logic
        for idx, emp_row in emp_fact_df.iterrows():
            emp_id = emp_row["employee_id"]
            skill_capacity = emp_row["average_capacity"]
            skill_type = emp_row["type"]
            code = emp_row["code"]

            # Initialize used capacity tracking with nested dictionary structure
            if emp_id not in employee_used_capacity:
                employee_used_capacity[emp_id] = {}

            # Calculate effective capacity with Primary capacity ceiling
            primary_capacity = get_employee_primary_capacity(emp_fact_df, emp_id)
            effective_capacity = min(skill_capacity, primary_capacity)

            # Set remaining capacity to effective capacity (will be updated during allocation)
            emp_fact_df.at[idx, "remaining_capacity"] = effective_capacity

############################## FIXED: Preserve original order ######################################################
        # Process orders for this date - PRESERVE ORIGINAL ORDER
        daily_orders = manning_df[manning_df["PLANNED_DATES"] == date].copy()

        # REPLACE groupby with manual ordering to preserve original sequence
        ordered_groups = []
        seen_groups = set()

        # Collect groups in order of first appearance
        for _, row in daily_orders.sort_values('_global_original_index').iterrows():
            group_key = (row['LINE'], row['SECTION'], row['CODE'])
            if group_key not in seen_groups:
                ordered_groups.append(group_key)
                seen_groups.add(group_key)

        print(f"Processing groups in original order: {[f'{line}/{section}/{code}' for line, section, code in ordered_groups]}")

###############################################################################################################
        for line, section, code in ordered_groups:
            print(f"Processing line={line}, section={section}, code={code}")

            # Get all rows for this group and sort by original index
            group_orders = daily_orders[
                (daily_orders['LINE'] == line) &
                (daily_orders['SECTION'] == section) &
                (daily_orders['CODE'] == code)
            ].sort_values('_global_original_index')

            group_rows = process_order_group(
                line, section, code, group_orders, emp_fact_df,
                employee_used_capacity, date, period
            )
            ##################change 17-06-2025 ###########################
            # # ADD: Store rows with original index for final sorting
            # for i, row in enumerate(group_rows):
            #     if isinstance(row, dict):
            #         # Get the source original index from the group
            #         source_idx = group_orders.iloc[i % len(group_orders)]['_global_original_index']
            #         row['_source_original_index'] = source_idx
            #         all_processed_rows.append(row)
            #     elif hasattr(row, 'to_dict'):  # pandas Series
            #         row_dict = row.to_dict()
            #         source_idx = group_orders.iloc[i % len(group_orders)]['_global_original_index']
            #         row_dict['_source_original_index'] = source_idx
            #         all_processed_rows.append(row_dict)
            #     else:
            #         # Fallback for other types
            #         all_processed_rows.append(row)

            all_processed_rows.extend(group_rows)

        # Track unallocated employees
        unallocated_employees = get_unallocated_employees(emp_fact_df, daily_orders, date, period)
        if unallocated_employees:
            unallocated_df = pd.DataFrame(unallocated_employees)
            unallocated_employees_list.append(unallocated_df)

    # CHANGED: Create final dataframe sorted by original order
    if all_processed_rows:
        updated_manning_df = pd.DataFrame(all_processed_rows)

        # Sort by original index to maintain original order
        if '_source_original_index' in updated_manning_df.columns:
            updated_manning_df = updated_manning_df.sort_values('_source_original_index')
            # Clean up the temporary column
            updated_manning_df = updated_manning_df.drop('_source_original_index', axis=1)

        updated_manning_df = updated_manning_df.reset_index(drop=True)

    return updated_manning_df, unallocated_employees_list


def get_employee_primary_capacity(emp_fact_df, emp_id):
    try:
        primary_rows = emp_fact_df[
            (emp_fact_df["employee_id"] == emp_id) &
            (emp_fact_df["type"] == "Primary")
        ]
        if len(primary_rows) > 0:
            return primary_rows["average_capacity"].iloc[0]
        else:
            # If no Primary skill found, return the maximum capacity among all skills
            # This handles edge cases where employee might only have Secondary skills
            emp_rows = emp_fact_df[emp_fact_df["employee_id"] == emp_id]
            return emp_rows["average_capacity"].max() if len(emp_rows) > 0 else 0
    except Exception as e:
        print(f"Error in get_employee_primary_capacity function: {e}")



def process_order_group(line, section, code, group_orders, emp_fact_df, employee_used_capacity, date, period):
    try:

        """Process a group of orders with time-based multi-skill capacity tracking"""
        # Calculate total quantity for this group
        total_planned_qty = group_orders['PLANNED_QTY'].sum()
        new_rows = []
        
        # Get available employees using time-based logic
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
                shortage_row["_source_original_index"] = row["_global_original_index"]
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
        
        # Pre-allocate employees with time-based multi-skill support
        employee_allocations = []
        remaining_total_qty = total_planned_qty
        
        # Allocate capacity based on remaining hours and hourly rates
        for _, emp in available_employees.iterrows():
            emp_id = emp["employee_id"]
            skill_type = emp["type"]
            
            # Use the time-based function to get actual available capacity
            available_capacity = get_employee_skill_allocation_potential(
                emp_fact_df, emp_id, code, employee_used_capacity
            )
            
            if available_capacity > 0 and remaining_total_qty > 0:
                allocation = min(remaining_total_qty, available_capacity)
                allocation = custom_round_quantity(allocation)  # Apply custom rounding
                
                if allocation > 0:
                    employee_allocations.append({
                        "employee_id": emp["employee_id"],
                        "EMPLOYEE NAME": emp["employee_name"],
                        "ALLOCATION": allocation,
                        "LINE": emp["line"],
                        "FACTORY": emp["factory"],
                        "FLOOR": emp["floor"],
                        "TYPE": emp["type"],
                        "MACHINE": emp["machine"],
                        "DESIGNATION": emp["designation"],
                        "SKILL_CAPACITY": emp["average_capacity"]
                    })
                    
                    remaining_total_qty -= allocation
                    remaining_total_qty = custom_round_quantity(remaining_total_qty) if remaining_total_qty > 0 else 0
                    
                    # Update capacity tracking with time-based logic
                    update_employee_capacity_tracking(
                        emp_id=emp_id,
                        skill_type=skill_type,
                        code=code,
                        allocation=allocation,
                        employee_used_capacity=employee_used_capacity,
                        emp_fact_df=emp_fact_df
                    )
        
        # Check if we have a shortage after allocation planning
        if remaining_total_qty > 0:
            shortage_qty = remaining_total_qty
            # print(f"WARNING: Group shortage of {shortage_qty} units for {line}/{section}/{code}")
        
        # Process individual orders - same as before
        # sorted_orders = group_orders.sort_values(by="PLANNED_QTY", ascending=False)
        sorted_orders = group_orders.copy()  # Preserve original order
        current_emp_index = 0
        
        #####################Change 17-06-2025#########################
        for _, row in sorted_orders.iterrows():
            # original_row = row.copy()
            # planned_qty = row["PLANNED_QTY"]
            # remaining_qty = planned_qty

            original_row = row.copy()
            original_row["_source_original_index"] = row["_global_original_index"]
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
                    ##########################added 17-06-2025############################
                    current_row["_source_original_index"] = row["_global_original_index"]

                    current_row["SPLIT_ORDER_ID"] = f"{split_order_id}_part{split_count}"
                    current_row["ALLOCATED EMP ID"] = current_emp["employee_id"]
                    current_row["ALLOCATED EMP NAME"] = current_emp["EMPLOYEE NAME"]
                    current_row["ALLOCATED CAPACITY"] = int(order_allocation)  # Convert to integer
                    current_row["ALLOCATED_FRM_LINE"] = current_emp["LINE"]
                    current_row["ALLOCATED_FRM_FACTORY"] = current_emp["FACTORY"]
                    current_row["ALLOCATED_FRM_FLOOR"] = current_emp["FLOOR"]
                    current_row["SKILL_TYPE"] = current_emp["TYPE"]
                    current_row["MACHINE_EMP_FACT"] = current_emp["MACHINE"]
                    current_row["DESIGNATION"] = current_emp["DESIGNATION"]
                    current_row["TARGET@100%"] = int(order_allocation)  # Convert to integer
                    current_row["TARGET@90%"] = int(order_allocation * 0.9)  # Convert to integer
                    current_row["PLANNED_QTY"] = int(order_allocation)  # Convert to integer
                    current_row["PERIOD"] = period
                    current_row["SHORTAGE_FLAG"] = "Fulfilled"
                    current_row["SHORTAGE_REASON"] = ""
                    
                    remaining_qty -= order_allocation
                    remaining_qty = custom_round_quantity(remaining_qty) if remaining_qty > 0 else 0
                    current_emp["ALLOCATION"] -= order_allocation
                    current_emp["ALLOCATION"] = custom_round_quantity(current_emp["ALLOCATION"]) if current_emp["ALLOCATION"] > 0 else 0
                    
                    new_rows.append(current_row)
                
                if current_emp["ALLOCATION"] <= 0.001:
                    current_emp_index += 1
            
            if remaining_qty > 0:
                shortage_row = original_row.copy()
                ##############added 17-06-2025 #######################################
                shortage_row["_source_original_index"] = row["_global_original_index"]
                shortage_row["SHORTAGE_FLAG"] = "Partial Shortage"
                shortage_row["PLANNED_QTY"] = int(remaining_qty)  # Convert to integer
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
    except Exception as e:
        print(f"Error in process_order_group function: {e}")



def custom_round_quantity(value):
    """
    Custom rounding logic:
    - If decimal >= 0.5: round up (ceil)
    - If decimal < 0.5: round down (floor)
    """
    decimal_part = value - math.floor(value)
    if decimal_part >= 0.5:
        return math.ceil(value)
    else:
        return math.floor(value)
    

def update_employee_capacity_tracking(emp_id, skill_type, code, allocation, employee_used_capacity, emp_fact_df):
    try:
        # Initialize if not exists
        if emp_id not in employee_used_capacity:
            employee_used_capacity[emp_id] = {}
        
        # Track allocation by skill type and code
        skill_key = f"{skill_type}_{code}"
        if skill_key not in employee_used_capacity[emp_id]:
            employee_used_capacity[emp_id][skill_key] = 0
        employee_used_capacity[emp_id][skill_key] += allocation
        
        # Calculate total hours used across all skills
        total_hours_used = get_employee_total_used_hours(emp_id, employee_used_capacity, emp_fact_df)
        
        # Update remaining capacity for ALL skill types of this employee
        for idx, row in emp_fact_df[emp_fact_df["employee_id"] == emp_id].iterrows():
            skill_capacity = row["average_capacity"]
            current_skill_type = row["type"]
            current_code = row["code"]
            
            # Calculate hourly rate for this skill
            hourly_rate = skill_capacity / 9  # pcs per hour
            
            # Calculate remaining hours (9 hours total per day)
            remaining_hours = max(0, 9 - total_hours_used)
            
            # Calculate remaining capacity for this skill
            remaining_capacity = remaining_hours * hourly_rate
            
            # Apply custom rounding to the remaining capacity
            remaining_capacity = custom_round_quantity(remaining_capacity)
            
            emp_fact_df.at[idx, "remaining_capacity"] = remaining_capacity
    except Exception as e:
        print(f"Error in update_employee_capacity_tracking function: {e}")



def get_employee_total_used_hours(emp_id, employee_used_capacity, emp_fact_df):
    """Calculate total hours used by employee across all skills"""
    try:
        if emp_id not in employee_used_capacity:
            return 0
        
        total_hours = 0
        for skill_key, allocated_qty in employee_used_capacity[emp_id].items():
            # Extract skill type and code from skill_key (format: "type_code")
            skill_parts = skill_key.split('_', 1)
            if len(skill_parts) == 2:
                skill_type, skill_code = skill_parts
                
                # Find the hourly rate for this skill
                skill_rows = emp_fact_df[
                    (emp_fact_df["employee_id"] == emp_id) &
                    (emp_fact_df["type"] == skill_type) &
                    (emp_fact_df["code"] == skill_code)
                ]
                
                if len(skill_rows) > 0:
                    skill_capacity = skill_rows["average_capacity"].iloc[0]
                    hourly_rate = skill_capacity / 9  # Assuming 9 hours per day
                    hours_used = round(allocated_qty / hourly_rate, 1)  # Round to 1 decimal place
                    total_hours += hours_used
        
        return total_hours
    except Exception as e:
        print(f"Error in get_employee_total_used_hours function: {e}")


def get_unallocated_employees(emp_fact_df, daily_orders, date, period):
    """Get unallocated employees with vectorized operations"""
    try:
        unallocated_employees = []

        for _, emp in emp_fact_df.iterrows():
            initial_capacity = emp["average_capacity"]
            remaining_capacity = emp["remaining_capacity"]
            
            utilized_capacity = initial_capacity - remaining_capacity
            if utilized_capacity < 1:
                utilization_pct = 0.0
            else:
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
                    "employee_id": emp["employee_id"],
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
    except Exception as e:
        print(f"Error in get_unallocated_employees function: {e}")


    
def get_prioritized_employees(emp_df, employee_used_capacity, line=None, code=None, section=None, emp_type=None):
    try:
        emp_df_copy = emp_df.copy()
        
        for idx, row in emp_df_copy.iterrows():
            emp_id = row["employee_id"]
            skill_capacity = row["average_capacity"]
            skill_type = row["type"]
            skill_code = row["code"]
            
            # Calculate total hours used across all skills
            total_hours_used = get_employee_total_used_hours(emp_id, employee_used_capacity, emp_df)
            
            # Calculate remaining hours (9 hours total per day)
            remaining_hours = max(0, 9 - total_hours_used)
            
            # Calculate hourly rate for this specific skill
            hourly_rate = skill_capacity / 9  # pcs per hour
            
            # Calculate effective remaining capacity for this skill
            effective_remaining_capacity = remaining_hours * hourly_rate
            
            # Apply custom rounding to the remaining capacity
            effective_remaining_capacity = custom_round_quantity(effective_remaining_capacity)
            
            emp_df_copy.at[idx, "effective_remaining_capacity"] = effective_remaining_capacity
        
        # Apply filters
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
        
        # Sort by TYPE (Primary first) and effective remaining capacity (descending)
        filtered_df = filtered_df.sort_values(
            by=["type", "effective_remaining_capacity"],
            ascending=[True, False]  # Primary first, then highest capacity
        )
        
        return filtered_df
    except Exception as e:
        print(f"Error in get_prioritized_employees function: {e}")



def get_employee_skill_allocation_potential(emp_fact_df, emp_id, target_code, employee_used_capacity):
    """
    Calculate how much capacity an employee has available for a specific skill,
    based on remaining hours and skill's hourly rate
    """
    try:
        # Calculate total hours used across all skills
        total_hours_used = get_employee_total_used_hours(emp_id, employee_used_capacity, emp_fact_df)
        
        # Calculate remaining hours (9 hours total per day)
        remaining_hours = max(0, 9 - total_hours_used)
        
        if remaining_hours <= 0:
            return 0
        
        # Find the specific skill capacity for the target code
        skill_rows = emp_fact_df[
            (emp_fact_df["employee_id"] == emp_id) &
            (emp_fact_df["code"] == target_code)
        ]
        
        if len(skill_rows) == 0:
            return 0  # Employee doesn't have this skill
        
        # Get the skill capacity and calculate hourly rate
        skill_capacity = skill_rows["average_capacity"].iloc[0]
        hourly_rate = skill_capacity / 9  # pcs per hour
        
        # Available capacity = remaining hours × hourly rate for this skill
        available_capacity = remaining_hours * hourly_rate
        
        return max(0, available_capacity)
    except Exception as e:
        print(f"Error in get_employee_skill_allocation_potential function: {e}")
