import logging
logger = logging.getLogger(__name__)

import pandas as pd


from datetime import datetime
from django.db import transaction
from config.utils import truncate_table
from .models import ManningSheetData, ManningGeneralInfo, SkillShortages, UnallocatedEmployees

CHUNK_SIZE = 5000  # Larger chunk size for better efficiency


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
def filter_by_date_ranges(df, today, date_thresholds):
    filtered_dfs = {
        "60_days": df[
            (df["planned_dates"] > today) &
            (df["planned_dates"] <= date_thresholds["60_days"])
        ],
        "30_days": df[
            (df["planned_dates"] > today) &
            (df["planned_dates"] <= date_thresholds["30_days"])
        ],
        "7_days": df[
            (df["planned_dates"] > today) &
            (df["planned_dates"] <= date_thresholds["7_days"])
        ],
        "1_day": df[
            (df["planned_dates"] > today) &
            (df["planned_dates"] <= date_thresholds["1_day"])
        ],
        "0_day": df[df["planned_dates"] == today]
    }
    return filtered_dfs


# Group by ORDER_NO, MERCHANT, STYLE and sum Planned Qty for each period
def process_grouped_results(filtered_dfs):
    result_dfs = {}
    
    for key, df in filtered_dfs.items():
        result = df.groupby(["oc_no", "order_no", "buyer", "style", "fabric_article", "line", "week", "planned_dates"], as_index=False)["planned_qty"].sum()
        result = result.rename(columns={'fabric_article': 'color'})
        result_dfs[key] = result

    return result_dfs


# Apply mapping, ensuring empty DataFrames also have "FACTORY", "FLOOR" and "Workdays" columns
def map_factory_floor_for_results(result_dfs):
    for key, df in result_dfs.items():
        if not df.empty:
            df[["FACTORY", "FLOOR"]] = pd.DataFrame(df["line"].apply(map_factory_floor).tolist(), index=df.index)
        else:
            df[["FACTORY", "FLOOR"]] = [["Unknown", "Unknown"]]  # ✅ Assign default values to empty DataFrames
        df["Workdays"] = 6


# Merge with Style OB table based on exact match and drop unmatched rows
def create_manning_dataframes(result_dfs, df_Style_OB):
    manning_dfs = {}
    
    for key, df in result_dfs.items():
        manning = df.merge(df_Style_OB, left_on=["style", "color"], right_on=["style", "color"], how="inner")
        manning = manning.sort_values(by=["style", "color", "section", "op_seq", "oc_no", "order_no", "line"])
        manning = manning.drop(columns=["Matched Style", "UNNAMED: 0"], errors='ignore')
        manning = manning.groupby(
            ["oc_no", "order_no", "buyer", "style", "color", "line", "section"], as_index=False
        ).apply(lambda x: x.sort_values(by=["planned_dates", "op_seq"])).reset_index(drop=True)
        manning.columns = manning.columns.str.upper()
        manning_dfs[key] = manning
    
    return manning_dfs


# Function to fetch prioritized employees based on constraints
def get_prioritized_employees(emp_df, line=None, code=None, section=None, emp_type=None):
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
    query = (emp_df["remaining_capacity"] > 0)

    if line:
        query &= (emp_df["line"] == line)
    if code: # Ensure employee only works on assigned CODE
        query &= (emp_df["code"] == code)
    if section:
        query &= (emp_df["section"] == section)
    if emp_type:
        query &= (emp_df["type"] == emp_type)
    
    # Prioritize PRIMARY first, then by REMAINING CAPACITY in descending order
    return emp_df[query].sort_values(by=["type", "remaining_capacity"], ascending=[True, False])


# Add allocation columns in manning
allocation_columns = [
    "ALLOCATED EMP ID", "ALLOCATED EMP NAME", "ALLOCATED CAPACITY",
    "ALLOCATED_FRM_LINE", "ALLOCATED_FRM_FACTORY", "ALLOCATED_FRM_FLOOR",
    "SKILL_TYPE", "MACHINE_EMP_FACT", "SHORTAGE_FLAG", "SHORTAGE_REASON", "DESIGNATION",
    "TARGET@100%", "TARGET@90%", "SPLIT_ORDER_ID", "PERIOD"
]



def run_manning_allocation(manning_dataframes_dict, emp_fact_df, df_unique_smv=None):
    """
    Main function to run the manning allocation process

    Parameters:
    -----------
    manning_dataframes_dict : dict
        Dictionary with keys as period suffixes (0, 1, 7, etc.) and values as dataframes
        Example: {"0": manning_0, "1": manning_1, "7": manning_7, etc.}
        These should be your existing dataframes
    emp_fact_df : pandas.DataFrame
        Employee data with capacity information
    df_unique_smv : pandas.DataFrame, optional
        SMV data for styles

    Returns:
    --------
    dict
        Dictionary containing all processed dataframes and analysis results
        Access them by keys like "consolidated_manning_df", "updated_manning_0_df", etc.
    """

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"[{timestamp}] Starting manning allocation process...")
    
    truncate_table(UnallocatedEmployees)

    # Dictionary to store all results
    results = {}

    # List of manning dataframes to process with metadata
    manning_dataframes = [
        {"suffix": "0", "period": 0, "df": manning_dataframes_dict.get("0")},
        {"suffix": "1", "period": 1, "df": manning_dataframes_dict.get("1")},
        {"suffix": "7", "period": 7, "df": manning_dataframes_dict.get("7")},
        {"suffix": "30", "period": 30, "df": manning_dataframes_dict.get("30")},
        {"suffix": "60", "period": 60, "df": manning_dataframes_dict.get("60")}
    ]

    emp_fact_df_original = emp_fact_df.copy()
    emp_fact_df_original = emp_fact_df_original[emp_fact_df_original["type"].isin(["Primary", "Secondary"])]

    # Process each manning dataframe
    all_processed_dfs = []  # To store all processed dataframes for consolidation
    unallocated_collection = {}  # To store unallocated employee data

    for df_info in manning_dataframes:
        suffix = df_info['suffix']
        period = df_info['period']
        manning_df = df_info['df'] #manning_dataframes_dict.get(suffix)

        try:
            # Check if the dataframe exists
            if manning_df is not None:
                logger.info(f"Processing manning data for period {period}...")

                # Store the df_name for compatibility with original code
                df_name = f"manning_{suffix}_df"

                # Process the manning dataframe
                updated_manning_df, unallocated_employees = process_manning_dataframe(
                    manning_df,
                    emp_fact_df_original.copy(),
                    period,
                    df_unique_smv
                )
    
                # Store results
                results[f"updated_manning_{suffix}_df"] = updated_manning_df

                # Store unallocated employees in collection using the original df_name format
                unallocated_collection[df_name] = unallocated_employees

                # Add to our collection for consolidation
                all_processed_dfs.append(updated_manning_df)

                logger.info(f"Successfully processed period {period}:")
                logger.info(f"  - Created manning sheet with {len(updated_manning_df)} rows")
            else:
                logger.info(f"Warning: Dataframe for period {period} not found, skipping.")

        except Exception as e:
            logger.info(f"Error processing period {period}: {e}")

    # Process unallocated employee data
    unallocated_results = process_unallocated_data(unallocated_collection, manning_dataframes)
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

            # Prepare all data as a list of dictionaries first (faster than processing row by row)
            data_dicts = []
            consolidated_df['STYLE'] = consolidated_df['STYLE'].str.lower()
            
            # Convert DataFrame to list of dicts (much faster than row iteration)
            for _, row in consolidated_df.iterrows():
                data_dict = {
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
                    'allocated_emp_id': int(row['ALLOCATED EMP ID']) if pd.notna(row['ALLOCATED EMP ID']) else 0,
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
                data_dicts.append(data_dict)
            
            # Process in chunks to avoid memory issues
            for i in range(0, len(data_dicts), CHUNK_SIZE):
                chunk_dicts = data_dicts[i:i + CHUNK_SIZE]
                
                # Convert dictionaries to model instances
                model_instances = [ManningSheetData(**d) for d in chunk_dicts]
                
                # Use a single transaction for the chunk
                with transaction.atomic():
                    ManningSheetData.objects.bulk_create(model_instances)
                
                logger.info(f"Inserted chunk {i//CHUNK_SIZE + 1}/{(len(data_dicts)-1)//CHUNK_SIZE + 1} with {len(chunk_dicts)} records")

            # Save consolidated dataframe
            results["consolidated_manning_df"] = consolidated_df

            # Analyze skill gaps if possible
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



def process_manning_dataframe(manning_df, emp_fact_df, period, df_unique_smv=None):
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
    manning_df = manning_df.copy()

    # Convert PLANNED_DATES to datetime for accurate merging
    manning_df["PLANNED_DATES"] = pd.to_datetime(manning_df["PLANNED_DATES"])

    # Create a new dataframe to store the split order lines
    updated_manning_df = pd.DataFrame(columns=manning_df.columns)


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

    # Unique dates in the manning dataframe
    unique_dates = manning_df["PLANNED_DATES"].unique()

    # List to store unallocated employees for each date
    unallocated_employees_list = []

    # Perform allocation with strict prioritization for each date
    for date in sorted(unique_dates):
        # print(f"Processing date: {date}")

        # Reset daily capacity for each employee
        for _, emp_row in emp_fact_df.iterrows():
            emp_fact_df.loc[
                (emp_fact_df["employee_id"] == emp_row["employee_id"]) &
                (emp_fact_df["code"] == emp_row["code"]) &
                (emp_fact_df["type"] == emp_row["type"]),
                "remaining_capacity"
            ] = emp_row["average_capacity"]

        # Round to 2 decimal places to avoid floating point issues
        emp_fact_df["remaining_capacity"] = emp_fact_df["remaining_capacity"].round(2) #----ROUND TO 1 PREFERRED

        # Add validation to ensure no negative initial capacities
        if (emp_fact_df["remaining_capacity"] < 0).any():
            # print(f"WARNING: Found negative initial capacities on {date}!")
            # Fix any negative values by setting to 0
            emp_fact_df.loc[emp_fact_df["remaining_capacity"] < 0, "remaining_capacity"] = 0

        # Filter orders for the current date
        daily_orders = manning_df[manning_df["PLANNED_DATES"] == date].copy()

        # Group orders by line, section, and code for more efficient allocation
        grouped_orders = daily_orders.groupby(['LINE', 'SECTION', 'CODE'])

        # Create a new list to collect all new rows (including splits)
        new_rows = []

        # Process each group separately to minimize employee usage
        for (line, section, code), group_orders in grouped_orders:
            # print(f"Processing line={line}, section={section}, code={code}, orders={len(group_orders)}")

            # Process this group of orders
            group_rows = process_order_group(
                line, section, code, group_orders, emp_fact_df, date, period
            )

            # Add to our results
            new_rows.extend(group_rows)

        # ----Track unallocated employees for this date
        unallocated_employees = get_unallocated_employees(emp_fact_df, daily_orders, date, period)

        if unallocated_employees:
            # Convert to DataFrame
            unallocated_df = pd.DataFrame(unallocated_employees)

            # Add to our collection
            unallocated_employees_list.append(unallocated_df)
            # print(f"Found {len(unallocated_employees)} unallocated/partially allocated employees for {date}")

        # Create DataFrame from new rows for this date and add to updated_manning_df
        if new_rows:
            date_df = pd.DataFrame(new_rows)
            updated_manning_df = pd.concat([updated_manning_df, date_df], ignore_index=True)

    try:
        if df_unique_smv is not None:
            updated_manning_df = updated_manning_df.merge(
                df_unique_smv[['style', 'smv']], left_on='STYLE', right_on='style', how='left'
            )
    except Exception as e:
        raise ValueError(f"SMV data error. Message: {e}")

    return updated_manning_df, unallocated_employees_list



def process_order_group(line, section, code, group_orders, emp_fact_df, date, period):
    """
    Process a group of orders with the same line, section, and code

    Parameters:
    -----------
    line : str
        Line value
    section : str
        Section value
    code : str
        Code value
    group_orders : pandas.DataFrame
        Orders with the same line, section, and code
    emp_fact_df : pandas.DataFrame
        Employee data with capacity information
    date : datetime
        Current date being processed
    period : int
        Period value

    Returns:
    --------
    list
        List of dictionaries representing new rows
    """
    # PHASE 1: Calculate total quantity and pre-allocate employees
    total_planned_qty = group_orders['PLANNED_QTY'].sum()
    # print(f"Total quantity for this group: {total_planned_qty}")

    # New rows to return
    new_rows = []

    # Get available employees for this skill combination
    available_employees = get_prioritized_employees(
        emp_fact_df, line=line, code=code, section=section
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
        return new_rows

    # Pre-allocate employees to minimize count - this is the key improvement
    employee_allocations = []  # List to track which employees to use and how much
    remaining_total_qty = total_planned_qty

    # First pass: determine which employees to use and how much capacity from each
    while remaining_total_qty > 0 and not available_employees.empty:
        emp = available_employees.iloc[0]  # Get highest priority employee

        # How much can this employee handle?
        allocation = min(remaining_total_qty, emp["remaining_capacity"])
        allocation = round(allocation, 2)  # Avoid floating point issues

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
                "DESIGNATION": emp["designation"]
            })

            # Update remaining quantity
            remaining_total_qty -= allocation
            remaining_total_qty = round(remaining_total_qty, 2)

            # Update this employee's capacity
            new_capacity = emp["remaining_capacity"] - allocation
            if abs(new_capacity) < 0.001:  # Fix floating point issues
                new_capacity = 0

            emp_fact_df.loc[
                (emp_fact_df["employee_id"] == emp["employee_id"]) &
                (emp_fact_df["code"] == emp["code"]) &
                (emp_fact_df["type"] == emp["type"]),
                "remaining_capacity"
            ] = new_capacity

        # Get next available employee
        available_employees = get_prioritized_employees(
            emp_fact_df, line=line, code=code, section=section
        )

    # Check if we have a shortage after allocation planning
    # if remaining_total_qty > 0:
    #     print(f"WARNING: Group shortage of {remaining_total_qty} units for {line}/{section}/{code}")

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

        first_allocation = True
        split_count = 0
        split_order_id = f"{row['ORDER_NO']}_{row['STYLE']}_{line}_{code}_{date.strftime('%Y%m%d')}"

        # Allocate this order using pre-determined employees
        while remaining_qty > 0 and current_emp_index < len(employee_allocations):
            current_emp = employee_allocations[current_emp_index]

            # How much can this employee take from the current order?
            order_allocation = min(remaining_qty, current_emp["ALLOCATION"])

            if order_allocation > 0:
                # Create a row for this allocation
                if first_allocation:
                    current_row = original_row.copy()
                    first_allocation = False
                    current_row["SPLIT_ORDER_ID"] = f"{split_order_id}_part1"
                    split_count = 1
                else:
                    current_row = original_row.copy()
                    split_count += 1
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
            new_rows.append(shortage_row)

    return new_rows



def get_unallocated_employees(emp_fact_df, daily_orders, date, period):
    """
    Track unallocated employees for a specific date

    Parameters:
    -----------
    emp_fact_df : pandas.DataFrame
        Employee data with capacity information
    daily_orders : pandas.DataFrame
        Orders for the current date
    date : datetime
        Current date being processed
    period : int
        Period value for the dataframe being processed

    Returns:
    --------
    list
        List of dictionaries with unallocated employee info
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
    Process unallocated employee data across all manning periods

    Parameters:
    -----------
    unallocated_collection : dict
        Dictionary with keys as df_names and values as lists of dataframes
    manning_dataframes : list
        List of dictionaries with dataframe metadata

    Returns:
    --------
    dict
        Dictionary with processed unallocated data
    """
    logger.info("\nProcessing unallocated employee data...")

    results = {}
    unallocated_all_periods = []

    # Process each manning dataframe's unallocated employees
    for df_name, unallocated_dfs in unallocated_collection.items():
        if not unallocated_dfs:
            continue

        logger.info(f"Processing unallocated data for {df_name}...")

        # Extract the period from the dataframe name
        period = None
        for df_info in manning_dataframes:
            # Extract suffix from df_name (like "manning_30_df" -> "30")
            if df_info["suffix"] in df_name:
                period = df_info["period"]
                break

        # Combine all dates for this dataframe
        combined_unallocated = pd.concat(unallocated_dfs, ignore_index=True)

        # Add period information if it's not already there
        if "PERIOD" not in combined_unallocated.columns:
            combined_unallocated["PERIOD"] = period

        # Store in results
        results[f"unallocated_{df_name}"] = combined_unallocated

        # Add to overall collection
        unallocated_all_periods.append(combined_unallocated)

    # Create consolidated view of all unallocated employees across all periods
    if unallocated_all_periods:
        all_unallocated = pd.concat(unallocated_all_periods, ignore_index=True)

        # Store in results
        results["all_unallocated_employees"] = all_unallocated

        logger.info(f"\nCreated consolidated unallocated employees dataframe with {len(all_unallocated)} total entries")

        # Prepare all data as a list of dictionaries first (faster than processing row by row)
        data_dicts = []
        
        # Convert DataFrame to list of dicts (much faster than row iteration)
        for _, row in all_unallocated.iterrows():
            data_dict = {
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
            data_dicts.append(data_dict)
        
        # Process in chunks to avoid memory issues
        for i in range(0, len(data_dicts), CHUNK_SIZE):
            chunk_dicts = data_dicts[i:i + CHUNK_SIZE]
            
            # Convert dictionaries to model instances
            model_instances = [UnallocatedEmployees(**d) for d in chunk_dicts]
            
            # Use a single transaction for the chunk
            with transaction.atomic():
                UnallocatedEmployees.objects.bulk_create(model_instances)
        

        # Generate training opportunity report
        training_opportunities = all_unallocated.copy()

        # Focus on employees with skillset not required
        skillset_not_required = training_opportunities[
            training_opportunities["CATEGORY"] == "Skillset not required"]

        # Group by employee to see which employees need cross-training
        employee_cross_training = skillset_not_required.groupby(
            ["EMPLOYEE ID", "EMPLOYEE NAME", "LINE", "CODE"]
        )["DATE"].count().reset_index()

        # Rename columns for clarity
        employee_cross_training.rename(columns={"DATE": "DAYS_UNALLOCATED"}, inplace=True)

        # Sort by days unallocated (descending)
        employee_cross_training = employee_cross_training.sort_values(
            by=["DAYS_UNALLOCATED", "LINE"], ascending=[False, True])

        # Store in results
        results["training_opportunities"] = employee_cross_training

        logger.info(f"Created training opportunities report with {len(employee_cross_training)} entries")

    return results



def analyze_skill_gaps(consolidated_manning_df, all_unallocated_employees):
    """
    Analyze skill gaps by comparing shortages with unallocated employees

    Parameters:
    -----------
    consolidated_manning_df : pandas.DataFrame
        Consolidated manning dataframe with all allocations
    all_unallocated_employees : pandas.DataFrame
        Consolidated unallocated employees dataframe

    Returns:
    --------
    dict
        Dictionary with skill gap analysis results
    """
    results = {}

    logger.info("\nAnalyzing skill gaps...")

    # Find all shortage rows
    shortages = consolidated_manning_df[
        consolidated_manning_df["SHORTAGE_FLAG"].str.contains("Shortage")]

    if not shortages.empty:
        # Group shortages by code to see which skills have the highest need
        shortage_by_code = shortages.groupby(["LINE", "CODE"])[
            "PLANNED_QTY"].sum().reset_index()

        # Sort by quantity (descending)
        shortage_by_code = shortage_by_code.sort_values(
            by="PLANNED_QTY", ascending=False)

        # Rename for clarity
        shortage_by_code.rename(
            columns={"PLANNED_QTY": "SHORTAGE_QTY"}, inplace=True)

        # Store in results
        results["skill_shortages"] = shortage_by_code

        logger.info(f"Created skill shortages report with {len(shortage_by_code)} entries")

    return results



def process_general_info(manning_sheets, df_emp_fact):

    df_results = []

    for period, df_manning in manning_sheets.items():

        # Check if 'ALLOCATED CAPACITY' column exists
        if 'ALLOCATED CAPACITY' in df_manning.columns:

            # Ensure PLANNED_QTY and ALLOCATED CAPACITY are integers and fill missing values
            df_manning['PLANNED_QTY'] = df_manning['PLANNED_QTY'].fillna(0).astype(int)
            df_manning['ALLOCATED CAPACITY'] = df_manning['ALLOCATED CAPACITY'].fillna(0).astype(int)

            # Group by STYLE, LINE, SECTION, CODE
            df_manning = df_manning.groupby(['STYLE', 'LINE', 'SECTION', 'CODE','MACHINE_TYPE'], as_index=False)[['PLANNED_QTY', 'ALLOCATED CAPACITY']].sum()
            df_manning['SHORTAGE CAPACITY'] = df_manning['PLANNED_QTY'] - df_manning['ALLOCATED CAPACITY']

            # ✅ Assign `Manning_Sheet_Period` AFTER grouping to prevent data loss
            df_manning["Manning_Sheet_Period"] = period

        # Filter only Primary and Secondary operations from Employee Fact Data
        df_emp_fact_filtered = df_emp_fact[df_emp_fact["type"].isin(["Primary", "Secondary"])]

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

        df_merged_filtered = df_merged_filtered.merge(machine_data, on="code", how="left")

        df_results.append(df_merged_filtered)


    truncate_table(ManningGeneralInfo)

    # Concatenate all results into a final dataframe
    df_final_Information = pd.concat(df_results, ignore_index=True)
    drop_c = ["OC NO", "ORDER NO", "BUYER", "COLOR", "WEEK", "PLANNED DATES", "FACTORY", "FLOOR",
                    "UNNAMED: 0", "OP_SEQ", "OPERATION", "SAM", "MACHINIST", "SMV"]

    df_final_Information.drop(columns=[col for col in drop_c if col in df_final_Information.columns], inplace=True)
    # df_final_Information['STYLE'] = df_final_Information['STYLE'].str.upper()

    # Prepare all data as a list of dictionaries first (faster than processing row by row)
    data_dicts = []
    
    # Convert DataFrame to list of dicts (much faster than row iteration)
    for _, row in df_final_Information.iterrows():
        data_dict = {
            'style':row['STYLE'],
            'line':row['LINE'],
            'section':row['SECTION'],
            'code':row['CODE'],
            'planned_qty':row['PLANNED_QTY'],
            'allocated_capacity':row['ALLOCATED CAPACITY'],
            'shortage_capacity':row['SHORTAGE CAPACITY'],
            'forecast_period':row['Manning_Sheet_Period'],
            'median_average_capacity':row['Median_Average_Capacity'],
            'section_average_capacity':row['Section_Average_Capacity'],
            'total_active_operators':row['Total_Active_Operators'],
            'machinist_available':row['Total_Machinist_Available'],
            'non_machinist_available':row['Total_Non_Machinist_Available'],
            'total_operators_required':row['Total_Operators_Required'],
            'machinist_required':row['Machinist_Required'],
            'non_machinist_required':row['Non_Machinist_Required'],
            'machine':row['MACHINE_TYPE']
        }
        data_dicts.append(data_dict)
    
    # Process in chunks to avoid memory issues
    for i in range(0, len(data_dicts), CHUNK_SIZE):
        chunk_dicts = data_dicts[i:i + CHUNK_SIZE]
        
        # Convert dictionaries to model instances
        model_instances = [ManningGeneralInfo(**d) for d in chunk_dicts]
        
        # Use a single transaction for the chunk
        with transaction.atomic():
            ManningGeneralInfo.objects.bulk_create(model_instances)

    return df_results