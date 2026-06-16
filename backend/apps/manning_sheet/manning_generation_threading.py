import os
import django

# Setup Django before importing models
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend_laguna.settings")
django.setup()


import pandas as pd


from datetime import datetime
from django.db import transaction
from backend_laguna.utils import truncate_table
from .models import ManningSheetData, ManningGeneralInfo, SkillShortages, UnallocatedEmployees

from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import Pool, cpu_count, Manager
from functools import partial

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




def process_single_df(key, df):
    grouped = df.groupby(
        ["oc_no", "order_no", "buyer", "style", "fabric_article", "line", "week", "planned_dates"],
        as_index=False
    )["planned_qty"].sum()

    grouped = grouped.rename(columns={'fabric_article': 'color'})
    return key, grouped

def process_grouped_results(filtered_dfs):
    result_dfs = {}

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_single_df, key, df) for key, df in filtered_dfs.items()]

        for future in as_completed(futures):
            key, result = future.result()
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
    return result_dfs




def process_single_manning_df(key, df, df_Style_OB):
    # Merge with Style OB data
    manning = df.merge(df_Style_OB, left_on=["style"], right_on=["style"], how="inner") # Removed color

    # Sort by specified columns
    manning = manning.sort_values(by=["style", "color", "section", "op_seq", "oc_no", "order_no", "line"])

    # Drop unnecessary columns
    manning = manning.drop(columns=["Matched Style", "UNNAMED: 0"], errors='ignore')

    # Group and sort
    manning = manning.groupby(
        ["oc_no", "order_no", "buyer", "style", "color", "line", "section"], as_index=False
    ).apply(lambda x: x.sort_values(by=["planned_dates", "op_seq"])).reset_index(drop=True)

    # Convert column names to uppercase
    manning.columns = manning.columns.str.upper()

    return key, manning

def create_manning_dataframes(result_dfs, df_Style_OB):
    df_Style_OB = df_Style_OB.drop(columns=['color'], errors='ignore')
    manning_dfs = {}

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_single_manning_df, key, df, df_Style_OB) for key, df in result_dfs.items()]
        
        for future in as_completed(futures):
            key, manning = future.result()
            manning_dfs[key] = manning

    return manning_dfs


# Ensure filter_by_date_ranges, process_grouped_results, and map_factory_floor_for_results are properly defined
def filter_by_date_ranges_wrapper(*args):
    return filter_by_date_ranges(*args)

def process_grouped_results_wrapper(*args):
    return process_grouped_results(*args)

def map_factory_floor_for_results_wrapper(*args):
    return map_factory_floor_for_results(*args)


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


def run_manning_allocation(manning_dataframes_dict, emp_fact_df_original, df_unique_smv=None):
    """
    Main function to run the manning allocation process with multithreading support
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] Starting manning allocation process...")

    truncate_table(UnallocatedEmployees)

    results = {}
    all_processed_dfs = []
    unallocated_collection = {}

    # Filter emp_fact_df
    # emp_fact_df_original = emp_fact_df.copy()
    emp_fact_df_original = emp_fact_df_original[emp_fact_df_original["type"].isin(["Primary", "Secondary"])]

    # Define manning dataframes and their metadata
    manning_dataframes = [
        {"suffix": str(period), "period": period, "df": manning_dataframes_dict.get(str(period))}
        for period in [0, 1, 7, 30, 60]
    ]

    def process_wrapper(df_info):
        try:
            suffix = df_info['suffix']
            period = df_info['period']
            manning_df = df_info['df']
            df_name = f"manning_{suffix}_df"

            if manning_df is not None:
                print(f"Processing manning data for period {period}...")

                updated_df, unallocated = process_manning_dataframe(
                    manning_df,
                    emp_fact_df_original,
                    period,
                    df_unique_smv
                )

                print(f"Successfully processed period {period}:")
                print(f"  - Created manning sheet with {len(updated_df)} rows")

                return {
                    "suffix": suffix,
                    "df_name": df_name,
                    "updated_df": updated_df,
                    "unallocated": unallocated
                }
            else:
                print(f"Warning: Dataframe for period {period} not found, skipping.")
        except Exception as e:
            print(f"Error processing period {df_info['period']}: {e}")
        return None

    # Run processing in parallel
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(process_wrapper, info) for info in manning_dataframes]
        for future in as_completed(futures):
            result = future.result()
            if result:
                suffix = result["suffix"]
                results[f"updated_manning_{suffix}_df"] = result["updated_df"]
                unallocated_collection[result["df_name"]] = result["unallocated"]
                all_processed_dfs.append(result["updated_df"])

    # Process unallocated employee data
    unallocated_results = process_unallocated_data(unallocated_collection, manning_dataframes)
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

            # data_dicts = consolidated_df.to_dict("records")
            consolidated_df.drop_duplicates(inplace=True) # Removing the duplicate rows

            # data_dicts = []
            # for _, row in consolidated_df.iterrows():
            #     data_dicts.append({
            #         'oc_no': row['OC_NO'],
            #         'order_no': row['ORDER_NO'],
            #         'buyer': row['BUYER'],
            #         'style': row['STYLE'],
            #         'line': row['LINE'],
            #         'week': row['WEEK'],
            #         'planned_dates': row['PLANNED_DATES'],
            #         'planned_qty': row['PLANNED_QTY'],
            #         'factory': row['FACTORY'],
            #         'floor': row['FLOOR'],
            #         'workdays': row['WORKDAYS'],
            #         'section': row['SECTION'],
            #         'op_seq': row['OP_SEQ'],
            #         'operation': row['OPERATION'],
            #         'code': row['CODE'],
            #         'sam': row['SAM'],
            #         'smv': row['smv'],
            #         'allocated_emp_id': int(row['ALLOCATED EMP ID']),
            #         'allocated_emp_name': row['ALLOCATED EMP NAME'],
            #         'allocated_capacity': row['ALLOCATED CAPACITY'],
            #         'allocated_frm_line': row['ALLOCATED_FRM_LINE'],
            #         'allocated_frm_factory': row['ALLOCATED_FRM_FACTORY'],
            #         'allocated_frm_floor': row['ALLOCATED_FRM_FLOOR'],
            #         'skill_type': row['SKILL_TYPE'],
            #         'machine': row['MACHINE_EMP_FACT'],
            #         'shortage_flag': row['SHORTAGE_FLAG'],
            #         'shortage_reason': row['SHORTAGE_REASON'],
            #         'designation': row['DESIGNATION'],
            #         'target_100': row['TARGET@100%'],
            #         'target_90': row['TARGET@90%'],
            #         'split_order_id': row['SPLIT_ORDER_ID'],
            #         'forecast_period': row['PERIOD'],
            #         'machinist': row['MACHINIST'],
            #         'machine_type': row['MACHINE_TYPE'],
            #         'color': row['COLOR']
            #     })

            # # Chunk insert to avoid memory issues
            # for i in range(0, len(data_dicts), CHUNK_SIZE):
            #     chunk = data_dicts[i:i + CHUNK_SIZE]
            #     instances = [ManningSheetData(**d) for d in chunk]
            #     with transaction.atomic():
            #         ManningSheetData.objects.bulk_create(instances)
            #     print(f"Inserted chunk {i//CHUNK_SIZE + 1} with {len(chunk)} records")

            
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

            print(f"Inserting {len(data_dicts)} unallocated records in {len(chunked_data)} chunks...")
            with ThreadPoolExecutor(max_workers=10) as executor:
                executor.map(insert_chunk, chunked_data)

                
            results["consolidated_manning_df"] = consolidated_df

            if "all_unallocated_employees" in results:
                skill_gap_results = analyze_skill_gaps(consolidated_df, results["all_unallocated_employees"])
                results.update(skill_gap_results)

            print(f"Successfully created consolidated manning dataframe with {len(consolidated_df)} total rows")
        else:
            print("No dataframes were processed successfully for consolidation")
    except Exception as e:
        raise ValueError(f"Error creating consolidated dataframe: {e}")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] Manning allocation process completed.")

    return results





def process_date_allocation(date, manning_df, emp_fact_df_base, period):
    """
    Handles allocation for a specific date.
    Returns new_rows and unallocated_employees for that date.
    """
    emp_fact_df = emp_fact_df_base.copy(deep=True)  # Deep copy to isolate capacity for each date

    # Reset employee capacity
    emp_fact_df["remaining_capacity"] = emp_fact_df["average_capacity"].clip(lower=0).round(2)

    # Filter for current date
    daily_orders = manning_df[manning_df["PLANNED_DATES"] == date].copy()
    grouped_orders = daily_orders.groupby(['LINE', 'SECTION', 'CODE'])

    new_rows = []

    for (line, section, code), group_orders in grouped_orders:
        group_rows = process_order_group(line, section, code, group_orders, emp_fact_df, date, period)
        new_rows.extend(group_rows)

    unallocated_employees = get_unallocated_employees(emp_fact_df, daily_orders, date, period)
    
    return date, new_rows, unallocated_employees


def process_manning_dataframe(manning_df, emp_fact_df, period, df_unique_smv=None):
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
    emp_fact_df_base = emp_fact_df.copy(deep=True)  # Base copy to isolate per-thread edits

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(process_date_allocation, date, manning_df, emp_fact_df_base, period)
            for date in unique_dates
        ]

        for future in as_completed(futures):
            date, new_rows, unallocated = future.result()

            if new_rows:
                date_df = pd.DataFrame(new_rows)
                updated_manning_df = pd.concat([updated_manning_df, date_df], ignore_index=True)

            if unallocated:
                unallocated_employees_list.append(pd.DataFrame(unallocated))

    # # Prepare arguments for starmap as a list of tuples
    # args_list = [
    #     (date, manning_df, emp_fact_df_base, period)
    #     for date in unique_dates
    # ]

    # with Pool(processes=cpu_count()) as pool:
    #     results_list = pool.starmap(process_date_allocation, args_list)

    # for result in results_list:
    #     date, new_rows, unallocated = result

    #     if new_rows:
    #         date_df = pd.DataFrame(new_rows)
    #         updated_manning_df = pd.concat([updated_manning_df, date_df], ignore_index=True)

    #     if unallocated:
    #         unallocated_employees_list.append(pd.DataFrame(unallocated))

    # Merge SMV if available
    try:
        if df_unique_smv is not None:
            updated_manning_df = updated_manning_df.merge(
                df_unique_smv[['style', 'smv']], left_on='STYLE', right_on='style', how='left'
            )
    except Exception as e:
        raise ValueError(f"SMV data error. Message: {e}")

    return updated_manning_df, unallocated_employees_list



def process_order_group(line, section, code, group_orders, emp_fact_df, date, period):
    total_planned_qty = group_orders['PLANNED_QTY'].sum()
    new_rows = []

    def build_shortage_reason():
        if emp_fact_df[emp_fact_df["code"] == code].empty:
            return f"No employees with CODE={code} found in any line"
        other_lines = emp_fact_df[
            (emp_fact_df["code"] == code) & (emp_fact_df["line"] != line)
        ]["line"].unique()
        if len(other_lines) > 0:
            return f"CODE={code} found only in lines: {', '.join(map(str, other_lines))}"
        zero_capacity = emp_fact_df[
            (emp_fact_df["code"] == code) & 
            (emp_fact_df["line"] == line) & 
            (emp_fact_df["remaining_capacity"] == 0)
        ]
        if not zero_capacity.empty:
            return f"Employees with CODE={code} in LINE={line} have no remaining capacity"
        return f"No matching employees for LINE={line} and CODE={code}"

    def process_shortage_row(row):
        r = row.copy()
        r["SHORTAGE_FLAG"] = "Shortage Unresolved"
        r["SHORTAGE_REASON"] = build_shortage_reason()
        r["SPLIT_ORDER_ID"] = ""
        return r

    available_employees = get_prioritized_employees(emp_fact_df, line=line, code=code, section=section)

    if available_employees.empty:
        # No employees -> all rows marked as shortage in parallel
        with ThreadPoolExecutor(max_workers=10) as executor:
            new_rows = list(executor.map(process_shortage_row, [r for _, r in group_orders.iterrows()]))
        return new_rows

    # PHASE 1: Allocate employees
    employee_allocations = []
    remaining_total_qty = total_planned_qty

    while remaining_total_qty > 0 and not available_employees.empty:
        emp = available_employees.iloc[0]
        allocation = round(min(remaining_total_qty, emp["remaining_capacity"]), 2)

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
                "DESIGNATION": emp["designation"]
            })

            remaining_total_qty = round(remaining_total_qty - allocation, 2)

            new_capacity = round(emp["remaining_capacity"] - allocation, 2)
            if abs(new_capacity) < 0.001:
                new_capacity = 0

            emp_fact_df.loc[
                (emp_fact_df["employee_id"] == emp["employee_id"]) &
                (emp_fact_df["code"] == emp["code"]) &
                (emp_fact_df["type"] == emp["type"]),
                "remaining_capacity"
            ] = new_capacity

        available_employees = get_prioritized_employees(emp_fact_df, line=line, code=code, section=section)

    # PHASE 2: Distribute allocations
    sorted_orders = group_orders.sort_values(by="PLANNED_QTY", ascending=False)
    current_emp_index = 0

    for _, row in sorted_orders.iterrows():
        original_row = row
        planned_qty = row["PLANNED_QTY"]
        remaining_qty = planned_qty
        split_count = 0
        split_order_id = f"{row['ORDER_NO']}_{row['STYLE']}_{line}_{code}_{date.strftime('%Y%m%d')}"

        if not employee_allocations:
            shortage_row = original_row.copy()
            shortage_row["SHORTAGE_FLAG"] = "Shortage"
            shortage_row["SHORTAGE_REASON"] = f"No employees available for {line}/{section}/{code}"
            new_rows.append(shortage_row)
            continue

        first_allocation = True

        while remaining_qty > 0 and current_emp_index < len(employee_allocations):
            current_emp = employee_allocations[current_emp_index]
            order_allocation = round(min(remaining_qty, current_emp["ALLOCATION"]), 2)

            if order_allocation > 0:
                current_row = original_row.copy()
                split_count += 1
                current_row["SPLIT_ORDER_ID"] = f"{split_order_id}_part{split_count}" if not first_allocation else f"{split_order_id}_part1"
                first_allocation = False

                # Allocation details
                current_row["ALLOCATED EMP ID"] = current_emp["EMPLOYEE ID"]
                current_row["ALLOCATED EMP NAME"] = current_emp["EMPLOYEE NAME"]
                current_row["ALLOCATED CAPACITY"] = order_allocation
                current_row["ALLOCATED_FRM_LINE"] = current_emp["LINE"]
                current_row["ALLOCATED_FRM_FACTORY"] = current_emp["FACTORY"]
                current_row["ALLOCATED_FRM_FLOOR"] = current_emp["FLOOR"]
                current_row["SKILL_TYPE"] = current_emp["TYPE"]
                current_row["MACHINE_EMP_FACT"] = current_emp["MACHINE"]
                current_row["DESIGNATION"] = current_emp["DESIGNATION"]
                current_row["TARGET@100%"] = order_allocation
                current_row["TARGET@90%"] = round(order_allocation * 0.9, 2)
                current_row["PLANNED_QTY"] = order_allocation
                current_row["PERIOD"] = period

                new_rows.append(current_row)
                remaining_qty = round(remaining_qty - order_allocation, 2)
                current_emp["ALLOCATION"] = round(current_emp["ALLOCATION"] - order_allocation, 2)

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
            shortage_row["SHORTAGE_REASON"] = f"Insufficient capacity: Needed {round(remaining_qty, 1)} more units"
            new_rows.append(shortage_row)

    return new_rows



def get_unallocated_employees(emp_fact_df, daily_orders, date, period):
    """
    Track unallocated employees for a specific date using threading for performance.
    """
    # Preprocess: create a set of (line, code) tuples that have orders
    line_code_set = set(zip(daily_orders["LINE"], daily_orders["CODE"]))

    def process_employee(emp):
        initial_capacity = emp["average_capacity"]
        remaining_capacity = emp["remaining_capacity"]

        if initial_capacity <= 0 or remaining_capacity <= 0:
            return None

        utilization_pct = round((initial_capacity - remaining_capacity) / initial_capacity * 100, 2)
        remaining_capacity = round(remaining_capacity, 2)

        emp_key = (emp["line"], emp["code"])
        if emp_key not in line_code_set:
            reason = "No matching orders for employee's skillset on this date"
            category = "Skillset not required"
        else:
            reason = "Partial allocation - capacity exceeds requirements"
            category = "Excess capacity"

        return {
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

    # Use multithreading for performance
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(process_employee, [row for _, row in emp_fact_df.iterrows()]))

    # Filter out None (e.g., employees with zero or full capacity)
    unallocated_employees = [res for res in results if res is not None]

    return unallocated_employees




def process_unallocated_data(unallocated_collection, manning_dataframes):
    """
    Process unallocated employee data across all manning periods using threading
    """
    print("\nProcessing unallocated employee data...")

    results = {}
    unallocated_all_periods = []

    # Process each manning dataframe's unallocated employees
    for df_name, unallocated_dfs in unallocated_collection.items():
        if not unallocated_dfs:
            continue

        print(f"Processing unallocated data for {df_name}...")

        # Extract period from metadata
        period = None
        for df_info in manning_dataframes:
            if df_info["suffix"] in df_name:
                period = df_info["period"]
                break

        combined_unallocated = pd.concat(unallocated_dfs, ignore_index=True)
        if "PERIOD" not in combined_unallocated.columns:
            combined_unallocated["PERIOD"] = period

        results[f"unallocated_{df_name}"] = combined_unallocated
        unallocated_all_periods.append(combined_unallocated)

    # Consolidated view of all unallocated employees
    if unallocated_all_periods:
        all_unallocated = pd.concat(unallocated_all_periods, ignore_index=True)
        results["all_unallocated_employees"] = all_unallocated

        print(f"\nCreated consolidated unallocated employees dataframe with {len(all_unallocated)} total entries")

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

        print(f"Inserting {len(data_dicts)} unallocated records in {len(chunked_data)} chunks...")
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

        print(f"Created training opportunities report with {len(employee_cross_training)} entries")

    return results




# # Global functions for multiprocessing (must not be nested)
# def _filter_shortages(df):
#     return df[df["SHORTAGE_FLAG"].str.contains("Shortage", na=False)]

# def _group_and_aggregate(shortages):
#     grouped = shortages.groupby(["LINE", "CODE"])["PLANNED_QTY"].sum().reset_index()
#     grouped.rename(columns={"PLANNED_QTY": "SHORTAGE_QTY"}, inplace=True)
#     return grouped.sort_values(by="SHORTAGE_QTY", ascending=False)

# def analyze_skill_gaps(consolidated_manning_df, all_unallocated_employees):
#     """
#     Analyze skill gaps by comparing shortages with unallocated employees
#     using multiprocessing for large DataFrames.
#     """
#     print("\nAnalyzing skill gaps...")

#     results = {}

#     with Pool(processes=min(cpu_count(), 4)) as pool:  # limit to avoid memory overhead
#         # Step 1: Filter shortages
#         shortages = pool.apply(_filter_shortages, (consolidated_manning_df,))

#         if not shortages.empty:
#             print(f"Found {len(shortages)} shortage rows. Aggregating...")

#             # Step 2: Aggregate
#             shortage_by_code = pool.apply(_group_and_aggregate, (shortages,))
#             results["skill_shortages"] = shortage_by_code

#             print(f"Created skill shortages report with {len(shortage_by_code)} entries")

#     return results



def analyze_skill_gaps(consolidated_manning_df, all_unallocated_employees):
    """
    Analyze skill gaps by comparing shortages with unallocated employees
    using threaded processing for large DataFrames.
    """
    results = {}

    print("\nAnalyzing skill gaps...")

    # --- Step 1: Filter shortages using a thread ---
    def filter_shortages():
        return consolidated_manning_df[
            consolidated_manning_df["SHORTAGE_FLAG"].str.contains("Shortage", na=False)
        ]

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_shortages = executor.submit(filter_shortages)
        shortages = future_shortages.result()

    if not shortages.empty:
        print(f"Found {len(shortages)} shortage rows. Aggregating...")

        # --- Step 2: Group and aggregate shortages using a thread ---
        def group_and_aggregate():
            grouped = shortages.groupby(["LINE", "CODE"])["PLANNED_QTY"].sum().reset_index()
            grouped.rename(columns={"PLANNED_QTY": "SHORTAGE_QTY"}, inplace=True)
            grouped_sorted = grouped.sort_values(by="SHORTAGE_QTY", ascending=False)
            return grouped_sorted

        with ThreadPoolExecutor(max_workers=10) as executor:
            future_agg = executor.submit(group_and_aggregate)
            shortage_by_code = future_agg.result()

        results["skill_shortages"] = shortage_by_code
        print(f"Created skill shortages report with {len(shortage_by_code)} entries")

    return results



import threading

def process_general_info(manning_sheets, df_emp_fact):
    df_results = []
    lock = threading.Lock()

    # Global filter of Employee Fact Data (Primary and Secondary only)
    df_emp_fact_filtered = df_emp_fact[df_emp_fact["type"].isin(["Primary", "Secondary"])]

    # Precomputed shared data for merging
    df_median_capacity = df_emp_fact_filtered.groupby(["code", "line", "section"], as_index=False)["average_capacity"].median()
    df_median_capacity.rename(columns={"average_capacity": "Median_Average_Capacity"}, inplace=True)

    df_section_avg_capacity = df_emp_fact_filtered.groupby(["section", "line"], as_index=False)["average_capacity"].median()
    df_section_avg_capacity.rename(columns={"average_capacity": "Section_Average_Capacity"}, inplace=True)

    df_total_active_operators = df_emp_fact_filtered.groupby(["code", "line", "section"], as_index=False)["employee_id"].count()
    df_total_active_operators.rename(columns={"employee_id": "Total_Active_Operators"}, inplace=True)

    df_machinist_count = df_emp_fact_filtered[df_emp_fact_filtered["designation"] == "Machinist"].groupby(["code", "line", "section"], as_index=False)["employee_id"].count()
    df_machinist_count.rename(columns={"employee_id": "Total_Machinist_Available"}, inplace=True)

    df_non_machinist_count = df_emp_fact_filtered[df_emp_fact_filtered["designation"] != "Machinist"].groupby(["code", "line", "section"], as_index=False)["employee_id"].count()
    df_non_machinist_count.rename(columns={"employee_id": "Total_Non_Machinist_Available"}, inplace=True)

    machine_data = df_emp_fact_filtered.groupby("code")["machine"].unique().reset_index()
    machine_data["machine"] = machine_data["machine"].apply(lambda x: ', '.join([m for m in x if m not in ["Unknown", "-"]]))

    machinist_codes = set(df_emp_fact_filtered[df_emp_fact_filtered["designation"] == "Machinist"]["code"].values)

    def process_period(period, df_manning):
        if 'ALLOCATED CAPACITY' not in df_manning.columns:
            return

        df_manning = df_manning.copy()
        df_manning['PLANNED_QTY'] = df_manning['PLANNED_QTY'].fillna(0).astype(int)
        df_manning['ALLOCATED CAPACITY'] = df_manning['ALLOCATED CAPACITY'].fillna(0).astype(int)

        df_manning = df_manning.groupby(['PLANNED_DATES', 'STYLE', 'LINE', 'SECTION', 'CODE', 'MACHINE_TYPE'], as_index=False)[['PLANNED_QTY', 'ALLOCATED CAPACITY']].sum()
        df_manning['SHORTAGE CAPACITY'] = df_manning['PLANNED_QTY'] - df_manning['ALLOCATED CAPACITY']
        df_manning["Manning_Sheet_Period"] = period

        df_merged = df_manning \
            .merge(df_median_capacity, left_on=["CODE", "LINE", "SECTION"], right_on=["code", "line", "section"], how="left") \
            .merge(df_section_avg_capacity, on=["section", "line"], how="left") \
            .merge(df_total_active_operators, on=["code", "line", "section"], how="left") \
            .merge(df_machinist_count, on=["code", "line", "section"], how="left") \
            .merge(df_non_machinist_count, on=["code", "line", "section"], how="left") \
            .merge(machine_data, on="code", how="left")

        df_merged["Median_Average_Capacity"].fillna(df_merged["Section_Average_Capacity"], inplace=True)
        df_merged["Median_Average_Capacity"].replace(0, 1, inplace=True)
        df_merged[["Total_Active_Operators", "Total_Machinist_Available", "Total_Non_Machinist_Available"]] = \
            df_merged[["Total_Active_Operators", "Total_Machinist_Available", "Total_Non_Machinist_Available"]].fillna(0)

        df_merged["Total_Operators_Required"] = (df_merged["PLANNED_QTY"] / df_merged["Median_Average_Capacity"]).round(1)

        df_merged["Machinist_Required"] = df_merged.apply(
            lambda row: row["Total_Operators_Required"] if row["code"] in machinist_codes else 0, axis=1)
        df_merged["Non_Machinist_Required"] = df_merged.apply(
            lambda row: row["Total_Operators_Required"] if row["code"] not in machinist_codes else 0, axis=1)

        with lock:
            df_results.append(df_merged)

    # Run each period in a separate thread
    with ThreadPoolExecutor(max_workers=10) as executor:
        for period, df_manning in manning_sheets.items():
            executor.submit(process_period, period, df_manning)

    truncate_table(ManningGeneralInfo)

    df_final_Information = pd.concat(df_results, ignore_index=True)

    drop_c = ["OC NO", "ORDER NO", "BUYER", "COLOR", "WEEK", "PLANNED DATES", "FACTORY", "FLOOR",
              "UNNAMED: 0", "OP_SEQ", "OPERATION", "SAM", "MACHINIST", "SMV"]
    df_final_Information.drop(columns=[col for col in drop_c if col in df_final_Information.columns], inplace=True)


    def safe_get(value, default=0):
        if pd.isna(value):
            return default
        return value

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

    for i in range(0, len(data_dicts), CHUNK_SIZE):
        chunk_dicts = data_dicts[i:i + CHUNK_SIZE]
        model_instances = [ManningGeneralInfo(**d) for d in chunk_dicts]
        with transaction.atomic():
            ManningGeneralInfo.objects.bulk_create(model_instances)

    return df_results




# # Function to process each period in parallel
# def process_period(period, df_manning, df_median_capacity, df_section_avg_capacity, df_total_active_operators, 
#                    df_machinist_count, df_non_machinist_count, machine_data, machinist_codes, lock, result_list):
#     if 'ALLOCATED CAPACITY' not in df_manning.columns:
#         return

#     df_manning = df_manning.copy()
#     df_manning['PLANNED_QTY'] = df_manning['PLANNED_QTY'].fillna(0).astype(int)
#     df_manning['ALLOCATED CAPACITY'] = df_manning['ALLOCATED CAPACITY'].fillna(0).astype(int)

#     df_manning = df_manning.groupby(['PLANNED_DATES', 'STYLE', 'LINE', 'SECTION', 'CODE', 'MACHINE_TYPE'], as_index=False)[['PLANNED_QTY', 'ALLOCATED CAPACITY']].sum()
#     df_manning['SHORTAGE CAPACITY'] = df_manning['PLANNED_QTY'] - df_manning['ALLOCATED CAPACITY']
#     df_manning["Manning_Sheet_Period"] = period

#     df_merged = df_manning \
#         .merge(df_median_capacity, left_on=["CODE", "LINE", "SECTION"], right_on=["code", "line", "section"], how="left") \
#         .merge(df_section_avg_capacity, on=["section", "line"], how="left") \
#         .merge(df_total_active_operators, on=["code", "line", "section"], how="left") \
#         .merge(df_machinist_count, on=["code", "line", "section"], how="left") \
#         .merge(df_non_machinist_count, on=["code", "line", "section"], how="left") \
#         .merge(machine_data, on="code", how="left")

#     df_merged["Median_Average_Capacity"].fillna(df_merged["Section_Average_Capacity"], inplace=True)
#     df_merged["Median_Average_Capacity"].replace(0, 1, inplace=True)
#     df_merged[["Total_Active_Operators", "Total_Machinist_Available", "Total_Non_Machinist_Available"]] = \
#         df_merged[["Total_Active_Operators", "Total_Machinist_Available", "Total_Non_Machinist_Available"]].fillna(0)

#     df_merged["Total_Operators_Required"] = (df_merged["PLANNED_QTY"] / df_merged["Median_Average_Capacity"]).round(1)

#     df_merged["Machinist_Required"] = df_merged.apply(
#         lambda row: row["Total_Operators_Required"] if row["code"] in machinist_codes else 0, axis=1)
#     df_merged["Non_Machinist_Required"] = df_merged.apply(
#         lambda row: row["Total_Operators_Required"] if row["code"] not in machinist_codes else 0, axis=1)

#     # Lock and append the result
#     with lock:
#         result_list.append(df_merged)

# def process_general_info(manning_sheets, df_emp_fact):
#     # Create a manager to hold results in a shared list
#     manager = Manager()
#     result_list = manager.list()

#     # Global filter of Employee Fact Data (Primary and Secondary only)
#     df_emp_fact_filtered = df_emp_fact[df_emp_fact["type"].isin(["Primary", "Secondary"])]

#     # Precomputed shared data for merging
#     df_median_capacity = df_emp_fact_filtered.groupby(["code", "line", "section"], as_index=False)["average_capacity"].median()
#     df_median_capacity.rename(columns={"average_capacity": "Median_Average_Capacity"}, inplace=True)

#     df_section_avg_capacity = df_emp_fact_filtered.groupby(["section", "line"], as_index=False)["average_capacity"].median()
#     df_section_avg_capacity.rename(columns={"average_capacity": "Section_Average_Capacity"}, inplace=True)

#     df_total_active_operators = df_emp_fact_filtered.groupby(["code", "line", "section"], as_index=False)["employee_id"].count()
#     df_total_active_operators.rename(columns={"employee_id": "Total_Active_Operators"}, inplace=True)

#     df_machinist_count = df_emp_fact_filtered[df_emp_fact_filtered["designation"] == "Machinist"].groupby(["code", "line", "section"], as_index=False)["employee_id"].count()
#     df_machinist_count.rename(columns={"employee_id": "Total_Machinist_Available"}, inplace=True)

#     df_non_machinist_count = df_emp_fact_filtered[df_emp_fact_filtered["designation"] != "Machinist"].groupby(["code", "line", "section"], as_index=False)["employee_id"].count()
#     df_non_machinist_count.rename(columns={"employee_id": "Total_Non_Machinist_Available"}, inplace=True)

#     machine_data = df_emp_fact_filtered.groupby("code")["machine"].unique().reset_index()
#     machine_data["machine"] = machine_data["machine"].apply(lambda x: ', '.join([m for m in x if m not in ["Unknown", "-"]]))

#     machinist_codes = set(df_emp_fact_filtered[df_emp_fact_filtered["designation"] == "Machinist"]["code"].values)

#     # Use Pool for parallel processing
#     with Pool(processes=cpu_count()) as pool:
#         # Partial function for easier arguments passing
#         func = partial(process_period, 
#                        df_median_capacity=df_median_capacity, 
#                        df_section_avg_capacity=df_section_avg_capacity, 
#                        df_total_active_operators=df_total_active_operators, 
#                        df_machinist_count=df_machinist_count, 
#                        df_non_machinist_count=df_non_machinist_count, 
#                        machine_data=machine_data, 
#                        machinist_codes=machinist_codes, 
#                        lock=manager.Lock(), 
#                        result_list=result_list)
        
#         # Apply the function to each period
#         pool.starmap(func, manning_sheets.items())

#     # Combine all results into a final DataFrame
#     df_final_information = pd.concat(list(result_list), ignore_index=True)

#     # Drop unnecessary columns
#     drop_c = ["OC NO", "ORDER NO", "BUYER", "COLOR", "WEEK", "PLANNED DATES", "FACTORY", "FLOOR",
#               "UNNAMED: 0", "OP_SEQ", "OPERATION", "SAM", "MACHINIST", "SMV"]
#     df_final_information.drop(columns=[col for col in drop_c if col in df_final_information.columns], inplace=True)

#     # Prepare the bulk data
#     data_dicts = df_final_information.apply(lambda row: {
#         'style': row['STYLE'],
#         'line': row['LINE'],
#         'section': row['SECTION'],
#         'code': row['CODE'],
#         'planned_qty': row['PLANNED_QTY'],
#         'allocated_capacity': row['ALLOCATED CAPACITY'],
#         'shortage_capacity': row['SHORTAGE CAPACITY'],
#         'forecast_period': row['Manning_Sheet_Period'],
#         'median_average_capacity': row['Median_Average_Capacity'] if row['Median_Average_Capacity'] else 0,
#         'section_average_capacity': row['Section_Average_Capacity'] if row['Section_Average_Capacity'] else 0,
#         'total_active_operators': int(row['Total_Active_Operators']) if row['Total_Active_Operators'] else 0,
#         'machinist_available': float(row['Total_Machinist_Available']) if row['Total_Machinist_Available'] else 0,
#         'non_machinist_available': float(row['Total_Non_Machinist_Available']) if row['Total_Non_Machinist_Available'] else 0,
#         'total_operators_required': float(row['Total_Operators_Required']) if row['Total_Operators_Required'] else 0,
#         'machinist_required': float(row['Machinist_Required']) if row['Machinist_Required'] else 0,
#         'non_machinist_required': float(row['Non_Machinist_Required']) if row['Non_Machinist_Required'] else 0,
#         'machine': row['MACHINE_TYPE'],
#         'planned_dates': row['PLANNED_DATES']
#     }, axis=1).tolist()

#     # Insert data into the database in chunks
#     for i in range(0, len(data_dicts), CHUNK_SIZE):
#         chunk_dicts = data_dicts[i:i + CHUNK_SIZE]
#         model_instances = [ManningGeneralInfo(**d) for d in chunk_dicts]
#         with transaction.atomic():
#             ManningGeneralInfo.objects.bulk_create(model_instances)

#     return df_final_information
