import os
import ast
import math
import pytz
import pandas as pd

from itertools import count
from datetime import datetime
from django.utils import timezone

from .models import ManningSheetData, DDayData
from apps.absenteeism.utils import is_allowed_working_day

MORNING_TIME="08:50"
NOON_TIME="12:45"
EVENING_TIME="17:30"



def get_ist_time(override_time: str = None):
    """
    Get current time in IST timezone.
    :param override_time: Optional string in "HH:MM" format (24-hour) to simulate time, e.g., "12:45"
    """
    ist = pytz.timezone('Asia/Kolkata')

    if override_time:
        try:
            hours, minutes = map(int, override_time.split(":"))
            today = timezone.now().astimezone(ist).date()
            simulated_time = datetime(today.year, today.month, today.day, hours, minutes)
            return ist.localize(simulated_time)
        except Exception as e:
            raise ValueError("Invalid override_time format. Use 'HH:MM'. Error: " + str(e))
    
    now_utc = timezone.now()
    return now_utc.astimezone(ist)



def safe_eval_history(history):
    """
    Safely evaluate history string, handling potential malformed inputs
    """
    if pd.isna(history):
        return []
    try:
        return ast.literal_eval(history)
    except (ValueError, SyntaxError):
        return []



def get_run_type_for_testing(use_fake_time=True, fake_time_str=None):
    """
    Get the run type based on either real time or a manually specified time

    Parameters:
    use_fake_time (bool): Whether to use a fake time for testing
    fake_time_str (str): Time string in format "HH:MM" (24-hour format)
                        Examples: "08:50", "12:45", "17:30"

    Returns:
    str: Run type ("morning", "noon", or "evening")
    """
    # Define threshold times
    morning_time = datetime.strptime(MORNING_TIME, "%H:%M").time()
    noon_time = datetime.strptime(NOON_TIME, "%H:%M").time()
    evening_time = datetime.strptime(EVENING_TIME, "%H:%M").time()

    if use_fake_time and fake_time_str:
        # Use the manually specified time
        try:
            fake_time = datetime.strptime(fake_time_str, "%H:%M").time()
            print(f"Using fake time: {fake_time_str}")
            current_time = fake_time
        except ValueError:
            print(f"Invalid time format: {fake_time_str}. Using real time instead.")
            current_time = datetime.now().time()
    else:
        # Use the real current time
        current_time = datetime.now().time()
        print(f"Using real time: {current_time.strftime('%H:%M')}")

    # Determine run type based on the time
    if current_time >= evening_time:
        return "evening"
    elif current_time >= noon_time:
        return "noon"
    else:
        return "morning"



################## Employee Prioritization Functions ############################
def get_prioritized_employees(emp_fact_df, line=None, factory=None, floor=None, code=None, emp_type=None, absent_employees=None):
    """
    Consistent prioritization logic from original D-day system
    """
    query = (emp_fact_df["remaining_capacity"] > 0)

    # Filter out absent employees
    if absent_employees and len(absent_employees) > 0:
        # Convert absent_employees to set for faster lookups
        if not isinstance(absent_employees, set):
            absent_set = set(absent_employees)
        else:
            absent_set = absent_employees
        # Filter out absent employees
        query &= ~emp_fact_df["employee_id"].isin(absent_set)

    if line:
        query &= (emp_fact_df["line"] == line)
    if factory:
        query &= (emp_fact_df["factory"] == factory)
    if floor:
        query &= (emp_fact_df["floor"] == floor)
    if code:
        query &= (emp_fact_df["code"] == code)

    if emp_type:
        query &= (emp_fact_df["type"] == emp_type)  # This ensures Primary and Secondary are handled separately

    return emp_fact_df[query].sort_values(by=["type", "remaining_capacity"], ascending=[True, False])



def check_floaters_for_allocation(emp_fact_df, code, line=None, factory=None, floor=None, absent_employees=None):
    """
    Check specifically for floaters with matching skills
    Simplified version to ensure compatibility
    """
    # Make a copy of the employee dataframe
    # emp_df = emp_fact_df.copy()

    # Base query for employees with positive capacity and matching code
    query = (emp_fact_df["remaining_capacity"] > 0) & (emp_fact_df["code"] == code)

    # Add filter for absent employees
    if absent_employees and len(absent_employees) > 0:
        # Convert absent_employees to set for faster lookups
        if not isinstance(absent_employees, set):
            absent_set = set(absent_employees)
        else:
            absent_set = absent_employees
        # Filter out absent employees
        query &= ~emp_fact_df["employee_id"].isin(absent_set)

    # Check if FLOATER column exists
    if "FLOATER" in emp_fact_df.columns:
        query &= (emp_fact_df["FLOATER"] == True)
    elif "designation" in emp_fact_df.columns:
        # Look for "Floater" in designation
        query &= emp_fact_df["designation"].str.contains("Floaters", case=False, na=False)
    else:
        # Consider employees with empty line as potential floaters
        query &= (emp_fact_df["line"].isna() | (emp_fact_df["line"] == ""))

    # Apply location filters if specified
    if line:
        query &= (emp_fact_df["line"] == line)
    if factory:
        query &= (emp_fact_df["factory"] == factory)
    if floor:
        query &= (emp_fact_df["floor"] == floor)

    # Return prioritized floaters
    return emp_fact_df[query].sort_values(by=["type", "remaining_capacity"], ascending=[True, False])



def find_preferred_employees(emp_fact_df, code=None, line=None, factory=None, floor=None, current_emp_id=None, absent_employees=None):
    """
    Find preferred employees using the same prioritization logic as get_prioritized_employees
    Returns a comma-separated string of employee names with their line
    Now also includes unassigned employees with matching skills

    Parameters:
    emp_fact_df (DataFrame): The employee fact table
    code (str): The skill code to match
    line (str): The line to match (optional)
    factory (str): The factory to match (optional)
    floor (str): The floor to match (optional)
    current_emp_id (str): The currently allocated employee ID to exclude

    Returns:
    str: Comma-separated list of preferred employees with their line
    """
    # Create lists to store employees at each level of prioritization
    preferred_same_line = []
    preferred_same_factory = []
    preferred_same_floor = []
    preferred_anywhere = []


    # Create a set of absent employees for faster lookups
    if absent_employees and len(absent_employees) > 0:
        if not isinstance(absent_employees, set):
            absent_set = set(absent_employees)
        else:
            absent_set = absent_employees
    else:
        absent_set = set()

    # First try same line
    if line:
        same_line_employees = get_prioritized_employees(emp_fact_df, line=line, code=code, absent_employees=absent_set)
        if not same_line_employees.empty:
            # Exclude current employee
            if current_emp_id is not None and not pd.isna(current_emp_id):
                same_line_employees = same_line_employees[same_line_employees["employee_id"] != current_emp_id]

            if not same_line_employees.empty:
                # Create list with employee names and their line
                preferred_same_line = [f"{row['employee_name']} - {row['employee_id']} [Line: {row['line']}, Capacity: {row['remaining_capacity']}]"
                                     for _, row in same_line_employees.iterrows()]

    # Try same factory
    if factory:
        same_factory_employees = get_prioritized_employees(emp_fact_df, factory=factory, code=code, absent_employees=absent_set)
        if not same_factory_employees.empty:
            # Exclude current employee and those already in same line
            same_factory_employees = same_factory_employees[
                (same_factory_employees["employee_id"] != current_emp_id) &
                (same_factory_employees["line"] != line)
            ]

            if not same_factory_employees.empty:
                preferred_same_factory = [f"{row['employee_name']} - {row['employee_id']}  [Line: {row['line']}, Capacity: {row['remaining_capacity']}]"
                                        for _, row in same_factory_employees.iterrows()]

    # Try same floor
    if floor:
        same_floor_employees = get_prioritized_employees(emp_fact_df, floor=floor, code=code, absent_employees=absent_set)
        if not same_floor_employees.empty:
            # Exclude current employee and those from same line or factory
            if factory:
                same_floor_employees = same_floor_employees[
                    (same_floor_employees["employee_id"] != current_emp_id) &
                    (same_floor_employees["line"] != line) &
                    (same_floor_employees["factory"] != factory)
                ]
            else:
                same_floor_employees = same_floor_employees[
                    (same_floor_employees["employee_id"] != current_emp_id) &
                    (same_floor_employees["line"] != line)
                ]

            if not same_floor_employees.empty:
                preferred_same_floor = [f"{row['employee_name']} - {row['employee_id']}  [Line: {row['line']}, Capacity: {row['remaining_capacity']}]"
                                      for _, row in same_floor_employees.iterrows()]

    # Try any location
    anywhere_employees = get_prioritized_employees(emp_fact_df, code=code, absent_employees=absent_set)
    if not anywhere_employees.empty:
        # Exclude current employee and those already included in other categories
        if floor and factory:
            anywhere_employees = anywhere_employees[
                (anywhere_employees["employee_id"] != current_emp_id) &
                (anywhere_employees["line"] != line) &
                (anywhere_employees["factory"] != factory) &
                (anywhere_employees["floor"] != floor)
            ]
        elif factory:
            anywhere_employees = anywhere_employees[
                (anywhere_employees["employee_id"] != current_emp_id) &
                (anywhere_employees["line"] != line) &
                (anywhere_employees["factory"] != factory)
            ]
        elif floor:
            anywhere_employees = anywhere_employees[
                (anywhere_employees["employee_id"] != current_emp_id) &
                (anywhere_employees["line"] != line) &
                (anywhere_employees["floor"] != floor)
            ]
        else:
            anywhere_employees = anywhere_employees[
                (anywhere_employees["employee_id"] != current_emp_id) &
                (anywhere_employees["line"] != line)
            ]

        if not anywhere_employees.empty:
            preferred_anywhere = [f"{row['employee_name']} - {row['employee_id']} [Line: {row['line']}, Capacity: {row['remaining_capacity']}]"
                                for _, row in anywhere_employees.iterrows()]

    # Combine all lists with clear section headers
    all_preferred = []

    if preferred_same_line:
        all_preferred.append("SAME LINE: " + ", ".join(preferred_same_line))

    if preferred_same_factory:
        all_preferred.append("SAME FACTORY: " + ", ".join(preferred_same_factory))

    if preferred_same_floor:
        all_preferred.append("SAME FLOOR: " + ", ".join(preferred_same_floor))

    if preferred_anywhere:
        all_preferred.append("OTHER LOCATIONS: " + ", ".join(preferred_anywhere))

    return " | ".join(all_preferred)



################## WIP and Allocation Loading Functions ############################
def add_wip_backlog(planned_manning_df, wip_df):
    """
    Add WIP quantities to planned quantities if they match on key combination fields
    Only used for evening planning (D+1) now, not for morning line balancing

    Parameters:
    planned_manning_df (DataFrame): The planned manning dataframe
    wip_df (DataFrame): The WIP dataframe containing backlog quantities

    Returns:
    DataFrame: Manning dataframe with updated quantities and backlog flag
    """
    # Create a copy to avoid modifying the original
    updated_manning = planned_manning_df.copy()

    # Add backlog flag column if it doesn't exist
    if 'backlog_flag' not in updated_manning.columns:
        updated_manning['backlog_flag'] = None

    # Add original planned qty column to track the initial values
    if 'original_planned_qty' not in updated_manning.columns:
        updated_manning['original_planned_qty'] = updated_manning['planned_qty']

    # Define the columns to join on - these identify a unique operation
    join_columns = [
        'oc_no', 'order_no', 'buyer', 'sytle', 'line', 'color',
        'section', 'operation', 'code'
    ]

    # Make sure all join columns exist in both dataframes
    join_columns = [col for col in join_columns if col in updated_manning.columns and col in wip_df.columns]

    # If there are no common columns to join on, return the original dataframe
    if not join_columns:
        print("Warning: No common columns found between manning and WIP dataframes")
        return updated_manning

    # Convert join columns to a consistent type (string in this case)
    for col in join_columns:
        wip_df[col] = wip_df[col].astype(str)
        planned_manning_df[col] = planned_manning_df[col].astype(str)

    # Perform the merge to identify matching rows
    merged_df = pd.merge(
        updated_manning,
        wip_df[join_columns + ['wip_qty']],
        on=join_columns,
        how='left'
    )

    # Fill NaN WIP quantities with 0
    merged_df['wip_qty'] = merged_df['wip_qty'].fillna(0)

    # Update planned quantities and set backlog flag
    for idx, row in merged_df.iterrows():
        if row['wip_qty'] > 0:
            # Add WIP quantity to the planned quantity
            updated_manning.loc[idx, 'planned_qty'] = row['original_planned_qty'] + row['wip_qty']
            updated_manning.loc[idx, 'backlog_flag'] = 'Backlog Included'
            planned_qty = row['planned_qty']

            # Also update allocated capacity and target capacities based on new planned quantities
            if 'target_100' in updated_manning.columns:
                # If this row has been allocated, update the capacity and targets proportionally
                if pd.notna(updated_manning.loc[idx, 'allocated_capacity']):
                    # Calculate the ratio of allocation to original planned quantity
                    ratio = updated_manning.loc[idx, 'allocated_capacity'] / row['original_planned_qty']

                    # Calculate new total quantity (original + WIP)
                    new_total_qty = row['original_planned_qty'] + row['wip_qty']

                    # Update the allocated capacity proportionally
                    new_allocated_capacity = new_total_qty * ratio
                    updated_manning.loc[idx, 'allocated_capacity'] = new_allocated_capacity

                    # Update targets based on new allocated capacity
                    # updated_manning.loc[idx, 'target_100'] = planned_qty
                    # updated_manning.loc[idx, 'target_90'] = planned_qty * 0.9

                    # Update targets based on new allocated capacity
                    updated_manning.loc[idx, 'target_100'] = new_allocated_capacity
                    updated_manning.loc[idx, 'target_90'] = new_allocated_capacity * 0.9

                    # Log the change for debugging
                    print(f"Updated allocated capacity for idx {idx}: {row['original_planned_qty']} -> {new_total_qty}, "
                          f"Allocated: {updated_manning.loc[idx, 'allocated_capacity']} -> {new_allocated_capacity}")

    print(f"Added backlog to {merged_df[merged_df['wip_qty'] > 0].shape[0]} operations")
    return updated_manning



def load_planned_allocation(allocation_date, wip_df=None, add_backlog=False):
    """
    Load the planned allocation from the 0-day plan only,
    optionally adding WIP backlog quantities (now only used for evening planning)

    Parameters:
    allocation_date (datetime): The date for which to load allocation
    wip_df (DataFrame, optional): WIP dataframe containing backlog quantities
    add_backlog (bool): Whether to add WIP backlog to planned quantities

    Returns:
    tuple: (Manning dataframe, source description)
    """
    # Load D-day plan
    manning_0_df = ManningSheetData.objects.filter(planned_dates=allocation_date).values()
    manning_0_df = pd.DataFrame(list(manning_0_df))
    if manning_0_df.empty:
        raise ValueError(f"No manning sheet data found for allocation date: {allocation_date}")
    manning_0_df['planned_dates'] = pd.to_datetime(manning_0_df['planned_dates'])
    manning_0_df['allocated_emp_name'] = 'Allocated_Employee_Name' # Assigning dummy value to 'allocated_emp_name' as fetching from emp_fact while inserting
    # Filter for the specific date
    plan_0 = manning_0_df[manning_0_df['planned_dates'] == allocation_date]

    if not plan_0.empty:
        # Add WIP backlog if WIP dataframe is provided and add_backlog is True
        if wip_df is not None and add_backlog:
            plan_0 = add_wip_backlog(plan_0, wip_df)
            return plan_0, 'D-day with Backlog'
        return plan_0, 'D-day'
    else:
        raise ValueError(f"No D-day planned allocation found for date: {allocation_date}")



def identify_affected_allocations(planned_manning_df, absent_employees, handle_shortages=True):
    """
    Identify allocations that need to be modified due to:
    1. Attendance issues (absences, early departures)
    2. Partial shortages or unresolved shortages (if handle_shortages=True)
    """
    # First identify allocations affected by attendance
    affected_allocations = planned_manning_df[
        planned_manning_df['allocated_emp_id'].isin(absent_employees)
    ].copy()

    # If requested, also identify allocations with shortage flags
    if handle_shortages:
        shortage_allocations = planned_manning_df[
            planned_manning_df['shortage_flag'].isin(["Partial Shortage", "Shortage Unresolved"])
        ].copy()

        # Combine with attendance-affected allocations (without duplicates)
        affected_allocations = pd.concat([affected_allocations, shortage_allocations]).drop_duplicates()

    # Mark the original allocation details for tracking
    affected_allocations['original_allocation'] = affected_allocations.apply(
        lambda row: {
            'emp_id': row['allocated_emp_id'],
            'emp_name': row['allocated_emp_name'],
            'line': row['allocated_frm_line'],
            'capacity': row['allocated_capacity'],
            'shortage_flag': row['shortage_flag'] if 'shortage_flag' in row else None
        },
        axis=1
    ).astype(str)

    return affected_allocations



def balance_by_operation_sequence_enhanced(planned_manning_df, emp_fact_df, wip_df=None, absent_employees=None):
    """
    Enhanced balancing function that considers WIP ratios, minimum staffing, and optimal buffers

    Parameters:
    planned_manning_df (DataFrame): The planned manning dataframe
    emp_fact_df (DataFrame): Employee fact table with capacity information
    wip_df (DataFrame, optional): WIP data containing quantities at each operation

    Returns:
    DataFrame: Manning dataframe with balanced allocation across OP_SEQs
    """
    # Create a copy to avoid modifying the original
    balanced_manning = planned_manning_df.copy()

    # Convert absent_employees to a set for faster lookups
    if absent_employees is not None and not isinstance(absent_employees, set):
        absent_set = set(absent_employees)
    else:
        absent_set = absent_employees or set()

    # Ensure op_seq column exists
    if 'op_seq' not in balanced_manning.columns:
        print("Warning: op_seq column not found. Creating dummy sequence.")
        # Create a temporary sequence based on operation order
        balanced_manning['op_seq'] = balanced_manning.groupby(['line', 'section']).cumcount() + 1

    # Sort by LINE and op_seq for sequential processing
    balanced_manning = balanced_manning.sort_values(by=['line', 'op_seq'])

    # Add columns for WIP analysis and convert to appropriate data types to avoid FutureWarning
    balanced_manning['wip_quantity'] = 0.0 # Initialize as float
    balanced_manning['wip_ratio'] = 0.0 # Initialize as float
    balanced_manning['optimal_wip_buffer'] = 0.0 # Initialize as float
    balanced_manning['excess_capacity'] = 0.0 # Initialize as float
    balanced_manning['resource_status'] = None

    # IMPROVED: Create a comprehensive allocation tracker for all employees
    # This will help avoid over-allocation by tracking all employees' capacity usage
    employee_allocation_tracker = {}

    # Pre-populate with all existing allocations
    for idx, row in balanced_manning.iterrows():
        emp_id = row['allocated_emp_id']
        if pd.notna(emp_id) and emp_id not in absent_set and row.get('shortage_flag') != 'Completed':
            allocation_capacity = row.get('allocated_capacity', 0)
            if allocation_capacity > 0:
                if emp_id not in employee_allocation_tracker:
                    # Initialize employee record
                    emp_data = emp_fact_df[emp_fact_df['employee_id'] == emp_id]
                    if not emp_data.empty:
                        total_capacity = emp_data['average_capacity'].iloc[0]
                        employee_allocation_tracker[emp_id] = {
                            'total_capacity': total_capacity,
                            'used_capacity': allocation_capacity,
                            'allocations': [{
                                'row_idx': idx,
                                'capacity': allocation_capacity,
                                'line': row.get('line', ''),
                                'section': row.get('section', '')
                            }]
                        }
                else:
                    # Add to existing employee record
                    employee_allocation_tracker[emp_id]['used_capacity'] += allocation_capacity
                    employee_allocation_tracker[emp_id]['allocations'].append({
                        'row_idx': idx,
                        'capacity': allocation_capacity,
                        'line': row.get('line', ''),
                        'section': row.get('section', '')
                    })

    # Print summary of the allocation tracker
    print(f"Balance operation: Initialized allocation tracker with {len(employee_allocation_tracker)} employees")


    # Join WIP data if available
    if wip_df is not None:
        # Define columns to join on
        join_columns = [col for col in ['line', 'section', 'operation', 'code']
                        if col in balanced_manning.columns and col in wip_df.columns]

        if join_columns:
            # Find WIP quantity column
            # wip_qty_col = next((col for col in wip_df.columns
            #                    if 'WIP' in col.upper() and 'QTY' in col.upper()), None).
            wip_qty_col = 'wip_qty'  # Assuming the WIP quantity column is named 'wip_qty'

            if wip_qty_col:
                # Prepare data types for joining
                for col in join_columns:
                    wip_df[col] = wip_df[col].astype(str)
                    balanced_manning[col] = balanced_manning[col].astype(str)

                # Merge WIP data
                merged_df = pd.merge(
                    balanced_manning,
                    wip_df[join_columns + [wip_qty_col]],
                    on=join_columns,
                    how='left'
                )

                # Update WIP quantities
                merged_df[wip_qty_col] = merged_df[wip_qty_col].fillna(0)
                balanced_manning['wip_quantity'] = merged_df[wip_qty_col].astype(float)  # Convert to float


    # 1. Calculate capacity metrics for each operation
    for idx, row in balanced_manning.iterrows():
        if pd.notna(row['allocated_capacity']) and row['allocated_capacity'] > 0:
            # Calculate hours needed based on planned quantity and allocated capacity
            planned_qty = row['planned_qty']
            allocated_capacity = row['allocated_capacity']

            # Calculate estimated hours to complete
            hours_needed = planned_qty / allocated_capacity if allocated_capacity > 0 else float('inf')
            balanced_manning.loc[idx, 'estimated_completion_time'] = min(hours_needed, 9)  # Use .loc instead of .at

            # Calculate standard expected hourly output
            hourly_output = allocated_capacity / 9  # Assuming 9-hour workday

            # Calculate optimal WIP buffer (2 hours of work for next operation)
            balanced_manning.loc[idx, 'optimal_wip_buffer'] = float(hourly_output * 2)  # Explicitly cast to float

            # Determine if operation has excess capacity
            if hours_needed < 6 and row['wip_quantity'] > hourly_output * 1:
                # Operation will finish early and has at least 1 hour of WIP buffer
                excess_hours = 6 - hours_needed
                balanced_manning.loc[idx, 'excess_capacity'] = float(excess_hours * (allocated_capacity / 8))  # Explicitly cast to float
                balanced_manning.at[idx, 'resource_status'] = 'EXCESS'
            elif hours_needed > 9:
                # Operation is understaffed
                balanced_manning.loc[idx, 'resource_status'] = 'SHORTAGE'
            else:
                # Operation is balanced
                balanced_manning.loc[idx, 'resource_status'] = 'BALANCED'

    # 2. Calculate WIP ratios between sequential operations
    for line, group in balanced_manning.groupby('line'):
        # Sort by operation sequence
        line_ops = group.sort_values('op_seq')

        # Calculate WIP ratios between consecutive operations
        for i in range(len(line_ops) - 1):
            current_op_idx = line_ops.iloc[i].name
            next_op_idx = line_ops.iloc[i+1].name


            current_wip = balanced_manning.loc[current_op_idx, 'wip_quantity']  # Use .loc instead of .at
            optimal_buffer = balanced_manning.loc[next_op_idx, 'optimal_wip_buffer']  # Use .loc instead of .at


            if optimal_buffer > 0:
                # Calculate ratio of current WIP to optimal buffer
                wip_ratio = float(current_wip / optimal_buffer)  # Explicitly cast to float
                balanced_manning.loc[next_op_idx, 'wip_ratio'] = wip_ratio  # Use .loc instead of .at

                # Categorize WIP status
                if wip_ratio > 1.5:
                    # More than enough WIP for next operation
                    balanced_manning.loc[current_op_idx, 'wip_status'] = 'EXCESS'  # Use .loc instead of .at
                elif wip_ratio < 0.5:
                    # Not enough WIP for next operation
                    balanced_manning.loc[current_op_idx, 'wip_status'] = 'SHORTAGE'  # Use .loc instead of .at
                else:
                    # Just right
                    balanced_manning.loc[current_op_idx, 'wip_status'] = 'OPTIMAL'  # Use .loc instead of .at


    # 3. Find operations that have excess capacity and could donate resources
    potential_donors = balanced_manning[
        (balanced_manning['resource_status'] == 'EXCESS') &
        (balanced_manning['excess_capacity'] > 0)
    ]

    # 4. Find operations that need more resources to prevent halts
    critical_recipients = balanced_manning[
        (balanced_manning['resource_status'] == 'SHORTAGE') &
        (balanced_manning['wip_ratio'] < 0.5)  # Low incoming WIP ratio
    ]

    # 5. Track reallocation actions
    reallocation_actions = []
    reallocation_count = 0

    # 6. First handle critical shortages that could halt production
    for idx, recipient in critical_recipients.iterrows():
        recipient_line = recipient['line']
        recipient_code = recipient['code']
        recipient_op = recipient['op_seq']

        # Look for donors in the same line first
        same_line_donors = potential_donors[
            (potential_donors['line'] == recipient_line) &
            (potential_donors['op_seq'] < recipient_op)  # Earlier operations first
        ]

        if not same_line_donors.empty:
            # Found potential donor in same line
            donor_found = False

            # Try each donor until we find one with capacity
            for donor_idx, donor in same_line_donors.iterrows():
                donor_emp_id = donor['allocated_emp_id']

                # Skip if donor is an absent employee or not valid
                if pd.isna(donor_emp_id) or donor_emp_id in absent_set:
                    continue

                # IMPROVED: Check if donor already has allocated capacity elsewhere
                actual_remaining_capacity = donor['excess_capacity']

                # Adjust based on our comprehensive tracker
                if donor_emp_id in employee_allocation_tracker:
                    emp_data = employee_allocation_tracker[donor_emp_id]
                    used_ratio = emp_data['used_capacity'] / emp_data['total_capacity']

                    # If employee is already heavily allocated (>80% of capacity), reduce available excess
                    if used_ratio > 0.8:
                        actual_remaining_capacity = actual_remaining_capacity * (1.0 - used_ratio)
                        if actual_remaining_capacity <= 0:
                            continue  # Skip this donor, they're already heavily utilized

                # Verify employee has the required skill
                emp_has_skill = False
                matching_skills = emp_fact_df[
                    (emp_fact_df['employee_id'] == donor_emp_id) &
                    (emp_fact_df['code'] == recipient_code)
                ]

                if not matching_skills.empty:
                    emp_has_skill = True

                if emp_has_skill:
                    # Calculate capacity to transfer (up to 50% of excess)
                    transfer_capacity = min(
                        actual_remaining_capacity * 0.5,
                        recipient['planned_qty'] / 4  # At most enough for 2 hours of work
                    )

                    if transfer_capacity > 0:
                        # Record reallocation action
                        reallocation_actions.append({
                            'from_line': donor['line'],
                            'from_op': donor['op_seq'],
                            'to_line': recipient_line,
                            'to_op': recipient_op,
                            'emp_id': donor_emp_id,
                            'capacity': transfer_capacity,
                            'reason': 'critical_shortage_prevention'
                        })

                        # Update donor's excess capacity
                        balanced_manning.loc[donor_idx, 'excess_capacity'] -= transfer_capacity  # Use .loc instead of .at

                        # If donor no longer has excess, remove from potential donors
                        if balanced_manning.loc[donor_idx, 'excess_capacity'] <= 0:  # Use .loc instead of .at
                            balanced_manning.loc[donor_idx, 'resource_status'] = 'BALANCED'  # Use .loc instead of .at
                            potential_donors = potential_donors[potential_donors.index != donor_idx]

                        # Verify available capacity in emp_fact_df before allocation
                        emp_data = emp_fact_df[emp_fact_df['employee_id'] == donor_emp_id]
                        if emp_data.empty or emp_data['remaining_capacity'].iloc[0] <= 0:
                            continue  # Skip if no capacity available

                        # Limit transfer_capacity to what's actually available
                        current_fact_capacity = emp_data['remaining_capacity'].iloc[0]
                        transfer_capacity = min(transfer_capacity, current_fact_capacity)

                        # Skip if no capacity to transfer
                        if transfer_capacity <= 0:
                            continue

                        # Update recipient's allocation
                        prev_emp_id = balanced_manning.loc[idx, 'allocated_emp_id']

                        # If recipient already has an allocation, store it for tracking
                        if pd.notna(prev_emp_id) and prev_emp_id != donor_emp_id:
                            balanced_manning.loc[idx, 'original_emp_id'] = prev_emp_id
                            balanced_manning.loc[idx, 'original_capacity'] = balanced_manning.loc[idx, 'allocated_capacity']

                        # Update the allocation
                        balanced_manning.loc[idx, 'allocated_emp_id'] = donor_emp_id
                        balanced_manning.loc[idx, 'allocated_capacity'] = transfer_capacity
                        balanced_manning.loc[idx, 'resource_status'] = 'BALANCED'
                        balanced_manning.loc[idx, 'reallocation_reason'] = 'WIP_optimization'
                        balanced_manning.loc[idx, 'reallocation_level'] = 'critical_shortage_prevention'
                        balanced_manning.loc[idx, 'shortage_flag'] = 'Reallocated via OP_SEQ'

                        # Update emp_fact_df remaining_capacity
                        emp_fact_df.loc[emp_fact_df['employee_id'] == donor_emp_id, 'remaining_capacity'] = max(0, current_fact_capacity - transfer_capacity)

                        # Update our allocation tracker
                        if donor_emp_id not in employee_allocation_tracker:
                            # Initialize employee record
                            total_capacity = emp_data['average_capacity'].iloc[0]
                            employee_allocation_tracker[donor_emp_id] = {
                                'total_capacity': total_capacity,
                                'used_capacity': transfer_capacity,
                                'allocations': [{
                                    'row_idx': idx,
                                    'capacity': transfer_capacity,
                                    'line': recipient_line,
                                    'section': recipient.get('section', '')
                                }]
                            }
                        else:
                            # Add to existing employee record
                            employee_allocation_tracker[donor_emp_id]['used_capacity'] += transfer_capacity
                            employee_allocation_tracker[donor_emp_id]['allocations'].append({
                                'row_idx': idx,
                                'capacity': transfer_capacity,
                                'line': recipient_line,
                                'section': recipient.get('section', '')
                            })

                        # Mark that we've found and used a donor
                        donor_found = True
                        reallocation_count += 1
                        break  # Stop looking for more donors for this recipient

            # If no suitable donor was found, continue to the next recipient
            if not donor_found:
                continue


        else:
            # Look for donors in other lines (cross-line balancing)
            other_line_donors = potential_donors[potential_donors['line'] != recipient_line]

            if not other_line_donors.empty:
                # Similar logic for cross-line balancing...
                # This would be a more extensive version of the same allocation logic
                # with additional checks for movement between lines
                pass


    # 7. Next, balance WIP across operations to optimize flow
    # After handling critical shortages, optimize WIP buffers
    for line, group in balanced_manning.groupby('line'):
        # Process each line separately
        line_ops = group.sort_values('op_seq')

        for i in range(len(line_ops) - 1):
            current_op_idx = line_ops.iloc[i].name
            next_op_idx = line_ops.iloc[i+1].name

            current_status = balanced_manning.at[current_op_idx, 'resource_status']
            next_status = balanced_manning.at[next_op_idx, 'resource_status']

            # If current operation has excess and next has shortage, balance them
            if (current_status == 'EXCESS' and
                next_status == 'SHORTAGE' and
                balanced_manning.loc[current_op_idx, 'excess_capacity'] > 0):

                # Similar allocation logic as above, but for WIP optimization
                # between consecutive operations
                pass

    # CRITICAL: Final verification step to catch any absent employee allocations
    absent_allocations_count = 0
    for idx, row in balanced_manning.iterrows():
        emp_id = row['allocated_emp_id']
        if pd.notna(emp_id) and emp_id in absent_set:
            absent_allocations_count += 1
            print(f"WARNING: Row {idx} has absent employee {emp_id} assigned in balance operation")
            balanced_manning.loc[idx, 'allocated_emp_id'] = None
            balanced_manning.loc[idx, 'allocated_emp_name'] = None
            balanced_manning.loc[idx, 'allocated_capacity'] = 0
            balanced_manning.loc[idx, 'shortage_flag'] = 'Reallocation Failed - Employee Absent'

    if absent_allocations_count > 0:
        print(f"Fixed {absent_allocations_count} absent employee allocations in balance operation")

    # Print summary of reallocations
    print(f"OP_SEQ balancing: Performed {reallocation_count} reallocations")

    return balanced_manning



# ################## Enhanced Reallocation Functions ############################
# def reallocate_work_enhanced(affected_allocations, emp_fact_df, allocation_date, wip_df=None, emp_type=None, absent_employees=None, full_manning_df=None):
#     """
#     Enhanced reallocation logic that considers floaters first and OP_SEQ

#     Parameters:
#     affected_allocations (DataFrame): Allocations that need to be modified
#     emp_fact_df (DataFrame): Employee fact table with capacity information
#     allocation_date (datetime): The date for which to perform allocation
#     wip_df (DataFrame, optional): WIP data containing quantities at each operation
#     emp_type (str, optional): Employee type to consider first (Primary or Secondary)

#     Returns:
#     tuple: (Reallocated allocations DataFrame, reallocation tracking list)
#     """

#     # Create a set from the absent_employees list for faster lookups
#     if absent_employees and len(absent_employees) > 0:
#         if not isinstance(absent_employees, set):
#             absent_set = set(absent_employees)
#         else:
#             absent_set = absent_employees
#         print(f"Processing {len(absent_set)} absent employees")
#     else:
#         absent_set = set()
#         print("No absent employees to process")

#     reallocation_tracking = []
#     affected_allocations['reallocation_level'] = None
#     affected_allocations['preferred_employees'] = None
#     affected_allocations['re_allocated_employee'] = None

#     # Sort affected allocations by LINE (for priority) and OP_SEQ if available
#     if 'op_seq' in affected_allocations.columns:
#         affected_allocations = affected_allocations.sort_values(by=['line', 'op_seq'])
#     else:
#         affected_allocations = affected_allocations.sort_values(by=['line'])

#     # CRITICAL FIX: Build consolidated employee capacity map
#     employee_capacity_map = build_employee_capacity_map(emp_fact_df)

#     # If full_manning_df is provided, pre-populate with existing allocations
#     if full_manning_df is not None:
#         print(f"Pre-populating capacity map with existing allocations from {len(full_manning_df)} rows")

#         for idx, row in full_manning_df.iterrows():
#             emp_id = row['allocated_emp_id']
#             if pd.notna(emp_id) and emp_id not in absent_set and row.get('shortage_flag') != 'Completed':
#                 allocation_capacity = row.get('allocated_capacity', 0)
#                 if allocation_capacity > 0 and emp_id in employee_capacity_map:
#                     # Allocate from consolidated capacity
#                     employee_capacity_map[emp_id]['remaining_capacity'] -= allocation_capacity
#                     employee_capacity_map[emp_id]['allocations'].append({
#                         'row_idx': idx,
#                         'allocation': allocation_capacity,
#                         'line': row.get('line', ''),
#                         'section': row.get('section', '')
#                     })

#     # Update emp_fact_df with consolidated remaining capacities
#     for emp_id, emp_data in employee_capacity_map.items():
#         emp_fact_df.loc[emp_fact_df['employee_id'] == emp_id, 'remaining_capacity'] = emp_data['remaining_capacity']

#     print(f"Initialized consolidated capacity tracking for {len(employee_capacity_map)} employees")

#     # Process each allocation that needs modification
#     for index, row in affected_allocations.iterrows():
#         # Skip rows that don't need reallocation
#         if row.get('shortage_flag') == 'Completed':
#             continue

#         line = row['line']
#         section = row['section']
#         code = row['code']
#         planned_qty = row['planned_qty']
#         factory = row['factory']
#         floor = row['floor']
#         op_sequence = row.get('op_seq', None)
#         current_emp_id = row['allocated_emp_id']

#         # IMPORTANT: If this allocation is being reallocated, free up the current employee's capacity
#         if pd.notna(current_emp_id) and current_emp_id in employee_capacity_map:
#             current_allocation = row.get('allocated_capacity', 0)
#             if current_allocation > 0:
#                 # Free up capacity in consolidated map
#                 employee_capacity_map[current_emp_id]['remaining_capacity'] += current_allocation

#                 # Remove this specific allocation
#                 employee_capacity_map[current_emp_id]['allocations'] = [
#                     alloc for alloc in employee_capacity_map[current_emp_id]['allocations']
#                     if alloc['row_idx'] != index
#                 ]

#                 # Update emp_fact_df
#                 emp_fact_df.loc[emp_fact_df['employee_id'] == current_emp_id, 'remaining_capacity'] = employee_capacity_map[current_emp_id]['remaining_capacity']

#                 print(f"Freed {current_allocation} capacity from employee {current_emp_id} for reallocation (row {index})")

#         # 1. Check floaters first
#         available_employee = check_floaters_for_allocation(emp_fact_df, code=code, absent_employees=absent_set)
#         allocation_level = 'floater'

#         # 2. If no floaters, follow the existing hierarchy
#         if available_employee.empty:
#             available_employee = get_prioritized_employees(emp_fact_df, line=line, code=code, emp_type=emp_type, absent_employees=absent_set)
#             allocation_level = 'same_line'

#         if available_employee.empty:
#             available_employee = get_prioritized_employees(emp_fact_df, line=line, code=code, emp_type="Secondary" if emp_type == "Primary" else "Primary", absent_employees=absent_set)
#             allocation_level = 'same_line_secondary'

#         if available_employee.empty:
#             available_employee = get_prioritized_employees(emp_fact_df, factory=factory, code=code, emp_type=emp_type, absent_employees=absent_set)
#             allocation_level = 'same_factory'

#         if available_employee.empty:
#             available_employee = get_prioritized_employees(emp_fact_df, factory=factory, code=code, emp_type="Secondary" if emp_type == "Primary" else "Primary", absent_employees=absent_set)
#             allocation_level = 'same_factory_secondary'

#         if available_employee.empty:
#             available_employee = get_prioritized_employees(emp_fact_df, floor=floor, code=code, emp_type=emp_type, absent_employees=absent_set)
#             allocation_level = 'same_floor'

#         if available_employee.empty:
#             available_employee = get_prioritized_employees(emp_fact_df, floor=floor, code=code, emp_type="Secondary" if emp_type == "Primary" else "Primary", absent_employees=absent_set)
#             allocation_level = 'same_floor_secondary'

#         if available_employee.empty:
#             available_employee = get_prioritized_employees(emp_fact_df, code=code, emp_type=emp_type, absent_employees=absent_set)
#             allocation_level = 'other_location'

#         if available_employee.empty:
#             available_employee = get_prioritized_employees(emp_fact_df, code=code, emp_type="Secondary" if emp_type == "Primary" else "Primary", absent_employees=absent_set)
#             allocation_level = 'other_location_secondary'

#         # 3. Check OP_SEQ and WIP (restored from your original logic)
#         # If we still don't have an employee AND we're working with a valid OP_SEQ
#         if available_employee.empty and op_sequence and wip_df is not None:
#             # Try to find an employee from the next operation in this line
#             next_sequence = op_sequence + 1

#             # Get the next operation's employees
#             next_op_rows = affected_allocations[
#                 (affected_allocations['line'] == line) &
#                 (affected_allocations['op_seq'] == next_sequence)
#             ]

#             if not next_op_rows.empty:
#                 next_op_row = next_op_rows.iloc[0]
#                 next_op_emp_id = next_op_row.get('allocated_emp_id')

#                 # CHECK: Check if employee is available based on our consolidated capacity
#                 if pd.notna(next_op_emp_id) and next_op_emp_id not in absent_set:
#                     # Check if this employee has remaining capacity
#                     remaining_capacity = 0

#                     if next_op_emp_id in employee_capacity_map:
#                         remaining_capacity = employee_capacity_map[next_op_emp_id]['remaining_capacity']
#                     else:
#                         # If not in capacity map, get from emp_fact_df
#                         emp_data = emp_fact_df[emp_fact_df['employee_id'] == next_op_emp_id]
#                         if not emp_data.empty:
#                             remaining_capacity = emp_data['remaining_capacity'].iloc[0]

#                     if remaining_capacity > 0:
#                         # Check if there's no WIP for the next operation
#                         has_wip_for_next = False

#                         # Check WIP data
#                         if wip_df is not None:
#                             # Create a key to match with WIP
#                             wip_key_cols = ['line', 'section', 'operation', 'code']
#                             wip_key_cols = [col for col in wip_key_cols if col in next_op_row.index and col in wip_df.columns]

#                             # Ensure boolean series
#                             wip_filter = pd.Series([True] * len(wip_df), index=wip_df.index)
#                             for col in wip_key_cols:
#                                 wip_filter &= (wip_df[col] == next_op_row[col])

#                             matching_wip = wip_df[wip_filter]

#                             if not matching_wip.empty:
#                                 # wip_qty_col = next((col for col in matching_wip.columns if 'WIP' in col.upper() and 'QTY' in col.upper()), None)
#                                 wip_qty_col = 'wip_qty'  # Assuming the WIP quantity column is named 'wip_qty'
#                                 if wip_qty_col and matching_wip[wip_qty_col].sum() > 0:
#                                     has_wip_for_next = True

#                         if not has_wip_for_next:
#                             # We can use this employee from the next operation
#                             emp_info = emp_fact_df[emp_fact_df['employee_id'] == next_op_emp_id]
#                             if not emp_info.empty:
#                                 # One more check that employee is not absent
#                                 if next_op_emp_id not in absent_set:
#                                     available_employee = emp_info
#                                     allocation_level = 'operation_sequence_based'

#         # Find and store preferred employees for manual assignment
#         preferred_employees = find_preferred_employees(
#             emp_fact_df,
#             code=code,
#             line=line,
#             factory=factory,
#             floor=floor,
#             current_emp_id=current_emp_id,
#             absent_employees=absent_set
#         )
#         affected_allocations.loc[index, 'preferred_employees'] = preferred_employees

#         # Process employee allocation if we found someone
#         if not available_employee.empty:
#             employee_allocated = False

#             for i in range(len(available_employee)):
#                 emp = available_employee.iloc[i]
#                 emp_id = emp['employee_id']

#                 # Skip if absent
#                 if emp_id in absent_set:
#                     print(f"WARNING: Found absent employee {emp_id} in available employees!")
#                     continue

#                 # Get remaining capacity from consolidated map
#                 if emp_id not in employee_capacity_map:
#                     print(f"WARNING: Employee {emp_id} not found in capacity map!")
#                     continue

#                 available_capacity = employee_capacity_map[emp_id]['remaining_capacity']

#                 # Skip if no capacity available
#                 if available_capacity <= 0:
#                     continue

#                 # Calculate allocation amount
#                 allocation = min(planned_qty, available_capacity)

#                 # Skip if allocation is too small
#                 if allocation <= 0:
#                     continue

#                 # Allocate capacity in consolidated map
#                 employee_capacity_map[emp_id]['remaining_capacity'] -= allocation
#                 employee_capacity_map[emp_id]['allocations'].append({
#                     'row_idx': index,
#                     'allocation': allocation,
#                     'line': line,
#                     'section': section
#                 })

#                 # Update emp_fact_df
#                 emp_fact_df.loc[emp_fact_df['employee_id'] == emp_id, 'remaining_capacity'] = employee_capacity_map[emp_id]['remaining_capacity']

#                 # Track reallocation
#                 reallocation = {
#                     'original_emp': row['allocated_emp_id'],
#                     'new_emp': emp_id,
#                     'line': line,
#                     'section': section,
#                     'allocation_level': allocation_level,
#                     'planned_qty': planned_qty,
#                     'allocated_qty': allocation,
#                     'remaining_capacity': employee_capacity_map[emp_id]['remaining_capacity'],
#                     'operation_sequence': op_sequence
#                 }
#                 reallocation_tracking.append(reallocation)

#                 # Update allocation details
#                 affected_allocations.loc[index, 'allocated_emp_id'] = emp_id
#                 affected_allocations.loc[index, 'allocated_emp_name'] = emp['employee_name']
#                 affected_allocations.loc[index, 'allocated_capacity'] = allocation
#                 affected_allocations.loc[index, 'allocated_frm_line'] = emp['line']
#                 affected_allocations.loc[index, 'allocated_frm_factory'] = emp['factory']
#                 affected_allocations.loc[index, 'allocated_frm_floor'] = emp['floor']
#                 affected_allocations.loc[index, 'skill_type'] = emp['type']
#                 affected_allocations.loc[index, 'machine'] = emp['machine']
#                 affected_allocations.loc[index, 'designation'] = emp['designation']
#                 affected_allocations.loc[index, 'target_100'] = planned_qty
#                 affected_allocations.loc[index, 'target_90'] = planned_qty * 0.9
#                 affected_allocations.loc[index, 'shortage_flag'] = f'Reallocated ({allocation_level})'
#                 affected_allocations.loc[index, 'reallocation_level'] = allocation_level
#                 affected_allocations.loc[index, 're_allocated_employee'] = emp['employee_name']

#                 employee_allocated = True
#                 break

#             # Mark as failed if no suitable employee was found
#             if not employee_allocated:
#                 affected_allocations.loc[index, 'shortage_flag'] = 'Reallocation Failed - No Capacity'
#         else:
#             affected_allocations.loc[index, 'shortage_flag'] = 'Reallocation Failed - No Matching Employee'

#     # Final verification: Check for over-allocation
#     over_allocated_count = 0
#     for emp_id, emp_data in employee_capacity_map.items():
#         if emp_data['remaining_capacity'] < 0:
#             over_allocated_count += 1
#             print(f"ERROR: Employee {emp_id} ({emp_data['name']}) is over-allocated! "
#                   f"Remaining capacity: {emp_data['remaining_capacity']}")
#             # Force fix
#             emp_data['remaining_capacity'] = 0
#             emp_fact_df.loc[emp_fact_df['employee_id'] == emp_id, 'remaining_capacity'] = 0

#     if over_allocated_count > 0:
#         print(f"Fixed {over_allocated_count} over-allocated employees")

#     # CRITICAL: Final verification step to catch any missed absent employees
#     absent_allocations_count = 0
#     for idx, row in affected_allocations.iterrows():
#         emp_id = row['allocated_emp_id']
#         if pd.notna(emp_id) and emp_id in absent_set:
#             absent_allocations_count += 1
#             print(f"WARNING: Row {idx} still has absent employee {emp_id} assigned")
#             affected_allocations.loc[idx, 'allocated_emp_id'] = None
#             affected_allocations.loc[idx, 'allocated_emp_name'] = None
#             affected_allocations.loc[idx, 'allocated_capacity'] = 0
#             affected_allocations.loc[idx, 'shortage_flag'] = 'Reallocation Failed - Employee Absent'

#     if absent_allocations_count > 0:
#         print(f"Fixed {absent_allocations_count} allocations that still had absent employees assigned")

#     # Print allocation statistics
#     print(f"Allocation summary: {len(reallocation_tracking)} reallocations performed")
#     successful_count = len(affected_allocations[affected_allocations['shortage_flag'].str.contains('Reallocated', na=False)])
#     failed_count = len(affected_allocations[affected_allocations['shortage_flag'].str.contains('Failed', na=False)])
#     print(f"Successful: {successful_count}, Failed: {failed_count}")

#     return affected_allocations, reallocation_tracking



def reallocate_work_enhanced(affected_allocations, emp_fact_df, allocation_date, wip_df=None, emp_type=None, absent_employees=None,full_manning_df=None):
    """
    Enhanced reallocation logic with consolidated capacity tracking
    : Now properly sets target_100 and target_90 to planned quantities when reallocation fails
    """
    # Create a set from the absent_employees list for faster lookups
    if absent_employees and len(absent_employees) > 0:
        if not isinstance(absent_employees, set):
            absent_set = set(absent_employees)
        else:
            absent_set = absent_employees
        print(f"Processing {len(absent_set)} absent employees")
    else:
        absent_set = set()
        print("No absent employees to process")

    reallocation_tracking = []
    affected_allocations['reallocation_level'] = None
    affected_allocations['preferred_employees'] = None
    affected_allocations['re_allocated_employee'] = None

    # Sort affected allocations by LINE (for priority) and op_seq if available
    if 'op_seq' in affected_allocations.columns:
        affected_allocations = affected_allocations.sort_values(by=['line', 'op_seq'])
    else:
        affected_allocations = affected_allocations.sort_values(by=['line'])

    # CRITICAL FIX: Build consolidated employee capacity map
    employee_capacity_map = build_employee_capacity_map(emp_fact_df)

    # If full_manning_df is provided, pre-populate with existing allocations
    if full_manning_df is not None:
        print(f"Pre-populating capacity map with existing allocations from {len(full_manning_df)} rows")

        for idx, row in full_manning_df.iterrows():
            emp_id = row['allocated_emp_id']
            if pd.notna(emp_id) and emp_id not in absent_set and row.get('shortage_flag') != 'Completed':
                allocation_capacity = row.get('allocated_capacity', 0)
                if allocation_capacity > 0 and emp_id in employee_capacity_map:
                    # Allocate from consolidated capacity
                    employee_capacity_map[emp_id]['remaining_capacity'] -= allocation_capacity
                    employee_capacity_map[emp_id]['allocations'].append({
                        'row_idx': idx,
                        'allocation': allocation_capacity,
                        'line': row.get('line', ''),
                        'section': row.get('section', '')
                    })

    # Update emp_fact_df with consolidated remaining capacities
    for emp_id, emp_data in employee_capacity_map.items():
        emp_fact_df.loc[emp_fact_df['employee_id'] == emp_id, 'remaining_capacity'] = emp_data['remaining_capacity']

    print(f"Initialized consolidated capacity tracking for {len(employee_capacity_map)} employees")

    # Process each allocation that needs modification
    for index, row in affected_allocations.iterrows():
        # Skip rows that don't need reallocation
        if row.get('shortage_flag') == 'Completed':
            continue

        line = row['line']
        section = row['section']
        code = row['code']
        planned_qty = row['planned_qty']
        factory = row['factory']
        floor = row['floor']
        op_sequence = row.get('op_seq', None)
        current_emp_id = row['allocated_emp_id']

        # IMPORTANT: If this allocation is being reallocated, free up the current employee's capacity
        if pd.notna(current_emp_id) and current_emp_id in employee_capacity_map:
            current_allocation = row.get('allocated_capacity', 0)
            if current_allocation > 0:
                # Free up capacity in consolidated map
                employee_capacity_map[current_emp_id]['remaining_capacity'] += current_allocation

                # Remove this specific allocation
                employee_capacity_map[current_emp_id]['allocations'] = [
                    alloc for alloc in employee_capacity_map[current_emp_id]['allocations']
                    if alloc['row_idx'] != index
                ]

                # Update emp_fact_df
                emp_fact_df.loc[emp_fact_df['employee_id'] == current_emp_id, 'remaining_capacity'] = employee_capacity_map[current_emp_id]['remaining_capacity']

                print(f"Freed {current_allocation} capacity from employee {current_emp_id} for reallocation (row {index})")

        # 1. Check floaters first
        available_employee = check_floaters_for_allocation(emp_fact_df, code=code, absent_employees=absent_set)
        allocation_level = 'floater'

        # 2. If no floaters, follow the existing hierarchy
        if available_employee.empty:
            available_employee = get_prioritized_employees(emp_fact_df, line=line, code=code, emp_type=emp_type, absent_employees=absent_set)
            allocation_level = 'same_line'

        if available_employee.empty:
            available_employee = get_prioritized_employees(emp_fact_df, line=line, code=code, emp_type="Secondary" if emp_type == "Primary" else "Primary", absent_employees=absent_set)
            allocation_level = 'same_line_secondary'

        if available_employee.empty:
            available_employee = get_prioritized_employees(emp_fact_df, factory=factory, code=code, emp_type=emp_type, absent_employees=absent_set)
            allocation_level = 'same_factory'

        if available_employee.empty:
            available_employee = get_prioritized_employees(emp_fact_df, factory=factory, code=code, emp_type="Secondary" if emp_type == "Primary" else "Primary", absent_employees=absent_set)
            allocation_level = 'same_factory_secondary'

        if available_employee.empty:
            available_employee = get_prioritized_employees(emp_fact_df, floor=floor, code=code, emp_type=emp_type, absent_employees=absent_set)
            allocation_level = 'same_floor'

        if available_employee.empty:
            available_employee = get_prioritized_employees(emp_fact_df, floor=floor, code=code, emp_type="Secondary" if emp_type == "Primary" else "Primary", absent_employees=absent_set)
            allocation_level = 'same_floor_secondary'

        if available_employee.empty:
            available_employee = get_prioritized_employees(emp_fact_df, code=code, emp_type=emp_type, absent_employees=absent_set)
            allocation_level = 'other_location'

        if available_employee.empty:
            available_employee = get_prioritized_employees(emp_fact_df, code=code, emp_type="Secondary" if emp_type == "Primary" else "Primary", absent_employees=absent_set)
            allocation_level = 'other_location_secondary'

        # 3. Check op_seq and WIP (restored from your original logic)
        # If we still don't have an employee AND we're working with a valid op_seq
        if available_employee.empty and op_sequence and wip_df is not None:
            # Try to find an employee from the next operation in this line
            next_sequence = op_sequence + 1

            # Get the next operation's employees
            next_op_rows = affected_allocations[
                (affected_allocations['line'] == line) &
                (affected_allocations['op_seq'] == next_sequence)
            ]

            if not next_op_rows.empty:
                next_op_row = next_op_rows.iloc[0]
                next_op_emp_id = next_op_row.get('allocated_emp_id')

                # CHECK: Check if employee is available based on our consolidated capacity
                if pd.notna(next_op_emp_id) and next_op_emp_id not in absent_set:
                    # Check if this employee has remaining capacity
                    remaining_capacity = 0

                    if next_op_emp_id in employee_capacity_map:
                        remaining_capacity = employee_capacity_map[next_op_emp_id]['remaining_capacity']
                    else:
                        # If not in capacity map, get from emp_fact_df
                        emp_data = emp_fact_df[emp_fact_df['employee_id'] == next_op_emp_id]
                        if not emp_data.empty:
                            remaining_capacity = emp_data['remaining_capacity'].iloc[0]

                    if remaining_capacity > 0:
                        # Check if there's no WIP for the next operation
                        has_wip_for_next = False

                        # Check WIP data
                        if wip_df is not None:
                            # Create a key to match with WIP
                            wip_key_cols = ['line', 'section', 'operation', 'code']
                            wip_key_cols = [col for col in wip_key_cols if col in next_op_row.index and col in wip_df.columns]

                            # Ensure boolean series
                            wip_filter = pd.Series([True] * len(wip_df), index=wip_df.index)
                            for col in wip_key_cols:
                                wip_filter &= (wip_df[col] == next_op_row[col])

                            matching_wip = wip_df[wip_filter]

                            if not matching_wip.empty:
                                wip_qty_col = next((col for col in matching_wip.columns if 'WIP' in col.upper() and 'QTY' in col.upper()), None)
                                if wip_qty_col and matching_wip[wip_qty_col].sum() > 0:
                                    has_wip_for_next = True

                        if not has_wip_for_next:
                            # We can use this employee from the next operation
                            emp_info = emp_fact_df[emp_fact_df['employee_id'] == next_op_emp_id]
                            if not emp_info.empty:
                                # One more check that employee is not absent
                                if next_op_emp_id not in absent_set:
                                    available_employee = emp_info
                                    allocation_level = 'operation_sequence_based'

        # Find and store preferred employees for manual assignment
        preferred_employees = find_preferred_employees(
            emp_fact_df,
            code=code,
            line=line,
            factory=factory,
            floor=floor,
            current_emp_id=current_emp_id,
            absent_employees=absent_set
        )
        affected_allocations.loc[index, 'preferred_employees'] = preferred_employees

        # Process employee allocation if we found someone
        if not available_employee.empty:
            employee_allocated = False

            for i in range(len(available_employee)):
                emp = available_employee.iloc[i]
                emp_id = emp['employee_id']

                # Skip if absent
                if emp_id in absent_set:
                    print(f"WARNING: Found absent employee {emp_id} in available employees!")
                    continue

                # Get remaining capacity from consolidated map
                if emp_id not in employee_capacity_map:
                    print(f"WARNING: Employee {emp_id} not found in capacity map!")
                    continue

                available_capacity = employee_capacity_map[emp_id]['remaining_capacity']

                # Skip if no capacity available
                if available_capacity <= 0:
                    continue

                # Calculate allocation amount
                allocation = min(planned_qty, available_capacity)

                # Skip if allocation is too small
                if allocation <= 0:
                    continue

                # Allocate capacity in consolidated map
                employee_capacity_map[emp_id]['remaining_capacity'] -= allocation
                employee_capacity_map[emp_id]['allocations'].append({
                    'row_idx': index,
                    'allocation': allocation,
                    'line': line,
                    'section': section
                })

                # Update emp_fact_df
                emp_fact_df.loc[emp_fact_df['employee_id'] == emp_id, 'remaining_capacity'] = employee_capacity_map[emp_id]['remaining_capacity']

                # Track reallocation
                reallocation = {
                    'original_emp': row['allocated_emp_id'],
                    'new_emp': emp_id,
                    'line': line,
                    'section': section,
                    'allocation_level': allocation_level,
                    'planned_qty': planned_qty,
                    'allocated_qty': allocation,
                    'remaining_capacity': employee_capacity_map[emp_id]['remaining_capacity'],
                    'operation_sequence': op_sequence
                }
                reallocation_tracking.append(reallocation)

                # Update allocation details
                affected_allocations.loc[index, 'allocated_emp_id'] = emp_id
                affected_allocations.loc[index, 'allocated_emp_name'] = emp['employee_name']
                affected_allocations.loc[index, 'allocated_capacity'] = allocation
                affected_allocations.loc[index, 'allocated_frm_line'] = emp['line']
                affected_allocations.loc[index, 'allocated_frm_factory'] = emp['factory']
                affected_allocations.loc[index, 'allocated_frm_floor'] = emp['floor']
                affected_allocations.loc[index, 'skill_type'] = emp['type']
                affected_allocations.loc[index, 'machine'] = emp['machine']
                affected_allocations.loc[index, 'designation'] = emp['designation']
                affected_allocations.loc[index, 'target_100'] = planned_qty  # Set to planned quantity
                affected_allocations.loc[index, 'target_90'] = planned_qty * 0.9  # Set to 90% of planned
                affected_allocations.loc[index, 'shortage_flag'] = f'Reallocated ({allocation_level})'
                affected_allocations.loc[index, 'reallocation_level'] = allocation_level
                affected_allocations.loc[index, 're_allocated_employee'] = emp['employee_name']

                employee_allocated = True
                break

            # : Mark as failed if no suitable employee was found - BUT STILL SET TARGETS TO planned_qty
            if not employee_allocated:
                affected_allocations.loc[index, 'shortage_flag'] = 'Reallocation Failed - No Capacity'
                # NEW: Set targets to planned quantities even when reallocation fails
                affected_allocations.loc[index, 'target_100'] = planned_qty
                affected_allocations.loc[index, 'target_90'] = planned_qty * 0.9
                
        else:
            # : No available employees found - BUT STILL SET TARGETS TO planned_qty
            affected_allocations.loc[index, 'shortage_flag'] = 'Reallocation Failed - No Matching Employee'
            # NEW: Set targets to planned quantities even when reallocation fails
            affected_allocations.loc[index, 'target_100'] = planned_qty
            affected_allocations.loc[index, 'target_90'] = planned_qty * 0.9

    # Final verification: Check for over-allocation
    over_allocated_count = 0
    for emp_id, emp_data in employee_capacity_map.items():
        if emp_data['remaining_capacity'] < 0:
            over_allocated_count += 1
            print(f"ERROR: Employee {emp_id} ({emp_data['name']}) is over-allocated! "
                  f"Remaining capacity: {emp_data['remaining_capacity']}")
            # Force fix
            emp_data['remaining_capacity'] = 0
            emp_fact_df.loc[emp_fact_df['employee_id'] == emp_id, 'remaining_capacity'] = 0

    if over_allocated_count > 0:
        print(f" {over_allocated_count} over-allocated employees")

    # : Final verification step to catch any missed absent employees - AND SET TARGETS
    absent_allocations_count = 0
    for idx, row in affected_allocations.iterrows():
        emp_id = row['allocated_emp_id']
        if pd.notna(emp_id) and emp_id in absent_set:
            absent_allocations_count += 1
            print(f"WARNING: Row {idx} still has absent employee {emp_id} assigned")
            planned_qty_for_target = row['planned_qty']  # Get planned qty for this row
            affected_allocations.loc[idx, 'allocated_emp_id'] = None
            affected_allocations.loc[idx, 'allocated_emp_name'] = None
            affected_allocations.loc[idx, 'allocated_capacity'] = 0
            affected_allocations.loc[idx, 'shortage_flag'] = 'Reallocation Failed - Employee Absent'
            # NEW: Set targets to planned quantities even when employee is absent
            affected_allocations.loc[idx, 'target_100'] = planned_qty_for_target
            affected_allocations.loc[idx, 'target_90'] = planned_qty_for_target * 0.9

    if absent_allocations_count > 0:
        print(f" {absent_allocations_count} allocations that still had absent employees assigned")

    # Print allocation statistics
    print(f"Allocation summary: {len(reallocation_tracking)} reallocations performed")
    successful_count = len(affected_allocations[affected_allocations['shortage_flag'].str.contains('Reallocated', na=False)])
    failed_count = len(affected_allocations[affected_allocations['shortage_flag'].str.contains('Failed', na=False)])
    print(f"Successful: {successful_count}, Failed: {failed_count}")

    return affected_allocations, reallocation_tracking


def build_employee_capacity_map(emp_fact_df):
    """
    Build a consolidated capacity map that properly handles employees with multiple skills
    The key insight: One employee = One total capacity, regardless of how many skills they have

    Parameters:
    emp_fact_df (DataFrame): Employee fact table with multiple skill rows per employee

    Returns:
    dict: Employee capacity map with consolidated capacity per employee
    """
    employee_capacity_map = {}

    # Group by employee to consolidate their skills and capacity
    for emp_id, emp_group in emp_fact_df.groupby('employee_id'):
        # Get employee basic info (should be same across all rows for this employee)
        emp_name = emp_group['employee_name'].iloc[0]
        emp_line = emp_group['line'].iloc[0]
        emp_factory = emp_group['factory'].iloc[0]
        emp_floor = emp_group['floor'].iloc[0]

        # CRITICAL: Use the MAXIMUM capacity across all their skills
        # This represents their total working capacity as a person
        max_capacity = emp_group['average_capacity'].max()

        # Collect all skills this employee has
        skills = []
        for _, skill_row in emp_group.iterrows():
            skills.append({
                'code': skill_row['code'],
                'type': skill_row['type'],  # Primary or Secondary
                'capacity': skill_row['average_capacity'],
                'operation': skill_row['operation']
            })

        employee_capacity_map[emp_id] = {
            'name': emp_name,
            'line': emp_line,
            'factory': emp_factory,
            'floor': emp_floor,
            'total_capacity': max_capacity,  # This is the person's actual working capacity
            'remaining_capacity': max_capacity,  # Initialize to total
            'skills': skills,
            'allocations': []  # Track all allocations for this person
        }

    print(f"Built capacity map for {len(employee_capacity_map)} unique employees")
    return employee_capacity_map



def update_emp_fact_df_with_consolidated_capacity(emp_fact_df, employee_capacity_map):
    """
    Update the emp_fact_df remaining_capacity based on consolidated employee capacity tracking

    Parameters:
    emp_fact_df (DataFrame): Employee fact table to update
    employee_capacity_map (dict): Consolidated capacity tracking
    """
    for emp_id, emp_data in employee_capacity_map.items():
        # Update ALL rows for this employee with the same remaining capacity
        # This ensures consistency across all their skill rows
        emp_fact_df.loc[emp_fact_df['employee_id'] == emp_id, 'remaining_capacity'] = emp_data['remaining_capacity']

    print("Updated emp_fact_df with consolidated remaining capacities")



def get_available_employees_with_skill(employee_capacity_map, code, emp_type=None, absent_employees=None,
                                     line=None, factory=None, floor=None):
    """
    Get available employees who have the required skill and remaining capacity

    Parameters:
    employee_capacity_map (dict): Consolidated capacity tracking
    code (str): Required skill code
    emp_type (str): 'Primary' or 'Secondary' skill type preference
    absent_employees (set): Set of absent employee IDs
    line, factory, floor (str): Location filters

    Returns:
    list: Available employees sorted by priority
    """
    available_employees = []

    if absent_employees is None:
        absent_employees = set()

    for emp_id, emp_data in employee_capacity_map.items():
        # Skip absent employees
        if emp_id in absent_employees:
            continue

        # Skip if no remaining capacity
        if emp_data['remaining_capacity'] <= 0:
            continue

        # Check if employee has the required skill
        has_skill = False
        skill_type = None
        skill_capacity = 0

        for skill in emp_data['skills']:
            if skill['code'] == code:
                has_skill = True
                skill_type = skill['type']
                skill_capacity = skill['capacity']
                break

        if not has_skill:
            continue

        # Apply skill type filter if specified
        if emp_type and skill_type != emp_type:
            continue

        # Apply location filters
        if line and emp_data['line'] != line:
            continue
        if factory and emp_data['factory'] != factory:
            continue
        if floor and emp_data['floor'] != floor:
            continue

        # Add to available list
        available_employees.append({
            'emp_id': emp_id,
            'emp_data': emp_data,
            'skill_type': skill_type,
            'skill_capacity': skill_capacity
        })

    # Sort by skill type (Primary first) and remaining capacity (highest first)
    available_employees.sort(key=lambda x: (
        0 if x['skill_type'] == 'Primary' else 1,  # Primary skills first
        -x['emp_data']['remaining_capacity']  # Higher capacity first
    ))

    return available_employees


def allocate_employee_capacity(employee_capacity_map, emp_id, allocation_amount, row_idx, line, section):
    """
    Allocate capacity to an employee and track the allocation

    Parameters:
    employee_capacity_map (dict): Consolidated capacity tracking
    emp_id: Employee ID
    allocation_amount (float): Capacity to allocate
    row_idx: Row index for tracking
    line, section (str): Location info for tracking

    Returns:
    bool: True if allocation successful, False if insufficient capacity
    """
    if emp_id not in employee_capacity_map:
        print(f"ERROR: Employee {emp_id} not found in capacity map")
        return False

    emp_data = employee_capacity_map[emp_id]

    # Check if sufficient capacity available
    if emp_data['remaining_capacity'] < allocation_amount:
        print(f"WARNING: Insufficient capacity for employee {emp_id}. "
              f"Requested: {allocation_amount}, Available: {emp_data['remaining_capacity']}")
        return False

    # Allocate the capacity
    emp_data['remaining_capacity'] -= allocation_amount
    emp_data['allocations'].append({
        'row_idx': row_idx,
        'allocation': allocation_amount,
        'line': line,
        'section': section
    })

    print(f"Allocated {allocation_amount} capacity to employee {emp_id}. "
          f"Remaining: {emp_data['remaining_capacity']}")

    return True

def free_employee_capacity(employee_capacity_map, emp_id, allocation_amount, row_idx):
    """
    Free up previously allocated capacity for an employee

    Parameters:
    employee_capacity_map (dict): Consolidated capacity tracking
    emp_id: Employee ID
    allocation_amount (float): Capacity to free up
    row_idx: Row index to identify the allocation

    Returns:
    bool: True if successfully freed, False if allocation not found
    """
    if emp_id not in employee_capacity_map:
        print(f"ERROR: Employee {emp_id} not found in capacity map")
        return False

    emp_data = employee_capacity_map[emp_id]

    # Find and remove the specific allocation
    for i, allocation in enumerate(emp_data['allocations']):
        if allocation['row_idx'] == row_idx and allocation['allocation'] == allocation_amount:
            # Free up the capacity
            emp_data['remaining_capacity'] += allocation_amount
            emp_data['allocations'].pop(i)

            print(f"Freed {allocation_amount} capacity from employee {emp_id}. "
                  f"New remaining: {emp_data['remaining_capacity']}")
            return True

    print(f"WARNING: Could not find allocation to free for employee {emp_id}, "
          f"row {row_idx}, amount {allocation_amount}")
    return False


def reallocate_work(affected_allocations, emp_fact_df, allocation_date, emp_type=None):
    """
    Original reallocation function preserved for backward compatibility
    Calls the enhanced version
    """
    return reallocate_work_enhanced(affected_allocations, emp_fact_df, allocation_date, None, emp_type)




################## Core Allocation Functions ############################
def perform_dday_allocation_enhanced(allocation_date, attendance_df, emp_fact_df, wip_df=None,
                                    morning_manning=None, is_planning=False, planned_leaves=None):
    """
    Enhanced D-day allocation with additional parameters for noon and evening runs

    Parameters:
    allocation_date (datetime): The date for which to perform allocation
    attendance_df (DataFrame): Attendance data
    emp_fact_df (DataFrame): Employee fact table with capacity information
    wip_df (DataFrame, optional): WIP data containing backlog quantities
    morning_manning (DataFrame, optional): Results from morning allocation (for noon run)
    is_planning (bool): Whether this is a planning run for the next day
    planned_leaves (list, optional): List of employee IDs with planned leaves

    Returns:
    tuple: (Final manning DataFrame, statistics dict, reallocation tracking list)
    """
    # Reset daily capacity for this run
    emp_fact_df['remaining_capacity'] = emp_fact_df['average_capacity']
    run_timestamp = get_ist_time()

    # If we're planning for tomorrow and have planned leaves, mark those employees as unavailable
    if is_planning and planned_leaves:
        emp_fact_df.loc[emp_fact_df['employee_id'].isin(planned_leaves), 'remaining_capacity'] = 0

    # Load D-day plan
    if morning_manning is not None:
        # For noon run, use the morning allocation as a base
        planned_manning = morning_manning
        plan_source = 'Morning Allocation'
    else:
        # For morning or evening run, load from base data
        planned_manning, plan_source = load_planned_allocation(allocation_date)

    # Ensure op_seq column exists for sorting purposes
    if 'op_seq' not in planned_manning.columns:
        print("Warning: op_seq column not found. Creating sequence numbers.")
        # Create a sequence number within each line and section
        planned_manning['op_seq'] = planned_manning.groupby(['line', 'section']).cumcount() + 1

    # Sort by line (for priority) and op_seq
    working_manning = planned_manning.copy().sort_values(by=['line', 'op_seq'])

    # Ensure all tracking columns exist
    tracking_columns = [
        'run_history',
        'current_run',
        'original_emp',
        'original_emp_name',
        'new_emp',
        'reallocation_level',
        're_allocated_employee',
        'preferred_employees',
        'reallocation_reason',
        'average_capacity_per_hour',
        'attendance_status',
        'estimated_completed_time',
        'wip_quantity',
        'completed_qty'  # New column for tracking completion (for noon run)
    ]
    for col in tracking_columns:
        if col not in working_manning.columns:
            working_manning[col] = None

    # Add WIP information if available
    if wip_df is not None:
        # Join WIP information
        join_columns = [
            'oc_no', 'order_no', 'buyer', 'sytle', 'line', 'color',
            'section', 'operation', 'code'
        ]

        # Make sure all join columns exist in both dataframes
        join_columns = [col for col in join_columns if col in working_manning.columns and col in wip_df.columns]

        # Convert join columns to strings for consistent joining
        for col in join_columns:
            wip_df[col] = wip_df[col].astype(str)
            working_manning[col] = working_manning[col].astype(str)

        # Perform the merge to add WIP information
        # wip_qty_col = next((col for col in wip_df.columns if 'WIP' in col.upper() and 'QTY' in col.upper()), None)
        wip_qty_col = 'wip_qty'
        if wip_qty_col and join_columns:
            merged_df = pd.merge(
                working_manning,
                wip_df[join_columns + [wip_qty_col]],
                on=join_columns,
                how='left'
            )

            # Fill NaN WIP quantities with 0
            merged_df[wip_qty_col] = merged_df[wip_qty_col].fillna(0)

            # Store WIP quantity in our tracking column
            working_manning['wip_quantity'] = merged_df[wip_qty_col]
        else:
            print("Warning: Could not add WIP information - missing columns")
            working_manning['wip_quantity'] = 0

    # For noon run, update based on completion status
    if morning_manning is not None and 'completed_qty' in morning_manning.columns:
        # Update the planned quantities based on what's already completed
        for idx in working_manning.index:
            if pd.notna(working_manning.loc[idx, 'completed_qty']) and working_manning.loc[idx, 'completed_qty'] > 0:
                # Reduce planned quantity by completed amount
                original_qty = working_manning.loc[idx, 'planned_qty']
                completed_qty = working_manning.loc[idx, 'completed_qty']
                remaining_qty = max(0, original_qty - completed_qty)

                # Update the planned quantity to what remains
                working_manning.loc[idx, 'original_planned_qty'] = original_qty
                working_manning.loc[idx, 'planned_qty'] = remaining_qty

                # If fully completed, mark for removal from allocation
                if remaining_qty == 0:
                    working_manning.loc[idx, 'shortage_flag'] = 'Completed'

    # Process attendance
    attendance_df['attendance_date'] = pd.to_datetime(attendance_df['attendance_date'])

    # Filter attendance for the allocation date
    daily_attendance = attendance_df[attendance_df['attendance_date'] == allocation_date]

    # Get latest status for each employee
    if not daily_attendance.empty:
        if 'last_updated' in daily_attendance.columns:
            daily_attendance['last_updated'] = pd.to_datetime(daily_attendance['last_updated'],format= '%Y-%m-%d %H:%M:%S', errors='coerce')
            latest_attendance = daily_attendance.sort_values('last_updated').groupby('employee_id').last()
        else:
            latest_attendance = daily_attendance.groupby('employee_id').first()

        # Identify employees who are absent OR have early departure
        current_absent = latest_attendance[
            (latest_attendance['status'] == 'A') |
            (latest_attendance['early_departure'] == True)
        ].index.tolist()

        # Convert employee IDs to the correct type (usually numeric)
        try:
            current_absent = [float(emp_id) for emp_id in current_absent]
        except ValueError:
            # If conversion fails, keep as string
            pass

        print(f"Identified {len(current_absent)} absent employees")

        # Identify present employees
        current_present = latest_attendance[latest_attendance['status'] == 'P'].index.tolist()

        # Create a Series mapping employee IDs to their attendance status
        attendance_status_map = latest_attendance['status'].copy()
        # Mark early departures
        early_departure_mask = latest_attendance['early_departure'] == True
        attendance_status_map[early_departure_mask] = attendance_status_map[early_departure_mask] + " (Early Departure)"
    else:
        current_absent = []
        current_present = []
        attendance_status_map = pd.Series(dtype='object')
        print("Warning: No attendance data found for this date!")

    # Add planned leaves to absent list for planning runs
    if is_planning and planned_leaves:
        current_absent.extend(planned_leaves)

    # Create a set of absent employees for faster lookups
    absent_set = set(current_absent)

    # Handle capacity for absent and early departure employees
    emp_fact_df.loc[emp_fact_df['employee_id'].isin(current_absent), 'remaining_capacity'] = 0

    # Find allocations affected by absences and shortage flags
    affected_allocations = identify_affected_allocations(working_manning, current_absent, handle_shortages=True)

    # Perform reallocation with enhanced logic
    reallocated_manning, reallocation_tracking = reallocate_work_enhanced(
        affected_allocations,
        emp_fact_df,
        allocation_date,
        wip_df,
        emp_type="Primary",  # Start with primary skills
        absent_employees=absent_set, # Pass absent
        full_manning_df=working_manning
    )

    # After initial reallocation, perform op_seq-based balancing
    balanced_manning = balance_by_operation_sequence_enhanced(
        working_manning,
        emp_fact_df,
        wip_df,
        absent_employees=absent_set  # Pass absent employees to balancing function
    )

    # Merge the results from reallocated_manning and balanced_manning
    final_manning = working_manning.copy()

    # First, update with reallocated data (for absences and shortages)
    for idx in reallocated_manning.index:
        # Determine reallocation reason
        if working_manning.loc[idx, 'allocated_emp_id'] in current_absent:
            reallocation_reason = 'attendance_issue'
        elif working_manning.loc[idx, 'shortage_flag'] in ["Partial Shortage", "Shortage Unresolved"]:
            reallocation_reason = 'shortage_resolution'
        else:
            reallocation_reason = 'other'

        # Preserve original employee information
        final_manning.loc[idx, 'original_emp'] = working_manning.loc[idx, 'allocated_emp_id']
        final_manning.loc[idx, 'new_emp'] = reallocated_manning.loc[idx, 'allocated_emp_id']
        final_manning.loc[idx, 'reallocation_level'] = reallocated_manning.loc[idx, 'reallocation_level']
        final_manning.loc[idx, 're_allocated_employee'] = reallocated_manning.loc[idx, 're_allocated_employee']
        final_manning.loc[idx, 'preferred_employees'] = reallocated_manning.loc[idx, 'preferred_employees']
        final_manning.loc[idx, 'reallocation_reason'] = reallocation_reason

        # Update key allocation columns
        columns_to_update = [
            'allocated_emp_id',
            'allocated_emp_name',
            'allocated_capacity',
            'allocated_frm_line',
            'allocated_frm_factory',
            'allocated_frm_floor',
            'skill_type',
            'machine',
            'designation',
            'target_100',
            'target_90',
            'shortage_flag'
        ]

        for col in columns_to_update:
            if col in reallocated_manning.columns and col in final_manning.columns:
                final_manning.loc[idx, col] = reallocated_manning.loc[idx, col]

    # Then, update with sequence-based balancing data (overrides any previous allocations)
    for idx in balanced_manning.index:
        # Only update rows that were affected by the sequence-based balancing
        if balanced_manning.loc[idx, 'shortage_flag'] == 'Reallocated via OP_SEQ':
            # Skip if balanced_manning is trying to allocate an absent employee
            if balanced_manning.loc[idx, 'allocated_emp_id'] in absent_set:
                print(f"WARNING: Skipping OP_SEQ balancing for row {idx} - would allocate absent employee")
                continue

            # Record original allocation for tracking
            if pd.isna(final_manning.loc[idx, 'original_emp']):
                final_manning.loc[idx, 'original_emp'] = final_manning.loc[idx, 'allocated_emp_id']

            if pd.isna(final_manning.loc[idx, 'original_emp_name']):
                final_manning.loc[idx, 'original_emp_name'] = final_manning.loc[idx, 'allocated_emp_name']


            # Update allocation details
            final_manning.loc[idx, 'allocated_emp_id'] = balanced_manning.loc[idx, 'allocated_emp_id']
            final_manning.loc[idx, 'allocated_emp_name'] = balanced_manning.loc[idx, 'allocated_emp_name']
            final_manning.loc[idx, 'allocated_capacity'] = balanced_manning.loc[idx, 'allocated_capacity']
            final_manning.loc[idx, 'allocated_frm_line'] = balanced_manning.loc[idx, 'allocated_frm_line']
            final_manning.loc[idx, 'shortage_flag'] = balanced_manning.loc[idx, 'shortage_flag']
            final_manning.loc[idx, 'reallocation_level'] = balanced_manning.loc[idx, 'reallocation_level']
            final_manning.loc[idx, 'reallocation_reason'] = 'operation_sequence_based'

            # Add to reallocation tracking
            reallocation = {
                'original_emp': final_manning.loc[idx, 'original_emp'],
                'new_emp': balanced_manning.loc[idx, 'allocated_emp_id'],
                'line': final_manning.loc[idx, 'line'],
                'section': final_manning.loc[idx, 'section'],
                'allocation_level': 'operation_sequence_based',
                'planned_qty': final_manning.loc[idx, 'planned_qty'],
                'allocated_qty': balanced_manning.loc[idx, 'allocated_capacity'],
                'operation_sequence': final_manning.loc[idx, 'op_seq']
            }
            reallocation_tracking.append(reallocation)

    # Update completion time estimates for all rows
    for idx, row in final_manning.iterrows():
        if pd.notna(row['allocated_capacity']) and row['allocated_capacity'] > 0:
            # Calculate hours needed based on planned quantity and allocated capacity
            planned_qty = row['planned_qty']
            allocated_capacity = row['allocated_capacity']

            # Calculate estimated hours to complete (assuming 8-hour workday)
            hours_needed = planned_qty / allocated_capacity if allocated_capacity > 0 else float('inf')

            # Cap at realistic workday limits (9 hours)
            hours_needed = min(hours_needed, 9)

            # Store estimated completion time (in hours from start of shift)
            final_manning.at[idx, 'estimated_completed_time'] = hours_needed
        else:
            # Mark operations with no allocation
            final_manning.at[idx, 'estimated_completed_time'] = float('inf')

    emp_fact_df['average_capacity/HR'] = emp_fact_df['average_capacity'] / 9
    # Add employee metadata from emp_fact_df
    # Create a Series mapping employee IDs to their average capacity per hour
    avg_capacity_per_hr_map = emp_fact_df.groupby('employee_id')['average_capacity/HR'].first()

    # Create a Series mapping employee IDs to their names
    emp_name_map = emp_fact_df.groupby('employee_id')['employee_name'].first()

    # Add the average capacity per hour based on the original employee ID (before reallocation)
    for idx in final_manning.index:
        emp_id = final_manning.loc[idx, 'original_emp']

        if pd.isna(emp_id) or emp_id == "":  # If original_emp is empty, use allocated_emp_id
            emp_id = final_manning.loc[idx, 'allocated_emp_id']

        # Add original employee name
        if emp_id in emp_name_map:
            final_manning.loc[idx, 'original_emp_name'] = emp_name_map[emp_id]
            final_manning.loc[idx, 'original_emp'] = emp_id

        # Add average capacity per hour
        if emp_id in avg_capacity_per_hr_map:
            final_manning.loc[idx, 'average_capacity_per_hour'] = avg_capacity_per_hr_map[emp_id]

        # Add attendance status for the original employee
        if emp_id in attendance_status_map:
            final_manning.loc[idx, 'attendance_status'] = attendance_status_map[emp_id]

    # FINAL VERIFICATION STEP: Check for any allocations that still have absent employees
    absent_allocations_count = 0
    for idx in final_manning.index:
        emp_id = final_manning.loc[idx, 'allocated_emp_id']
        if pd.notna(emp_id) and emp_id in absent_set:
            absent_allocations_count += 1
            print(f"WARNING: Row {idx} still has absent employee {emp_id} assigned")
            # Fix the allocation
            final_manning.loc[idx, 'allocated_emp_id'] = None
            final_manning.loc[idx, 'allocated_emp_name'] = None
            final_manning.loc[idx, 'allocated_capacity'] = 0
            final_manning.loc[idx, 'shortage_flag'] = 'Reallocation Failed - Employee Absent'

    if absent_allocations_count > 0:
        print(f"Fixed {absent_allocations_count} allocations that still had absent employees assigned")


    # Record this run's changes
    run_record = {
        'timestamp': run_timestamp,
        'absent_count': len(current_absent),
        'shortage_count': len(affected_allocations) - len(affected_allocations[affected_allocations['allocated_emp_id'].isin(current_absent)]),
        'reallocations': len(reallocation_tracking),
        'is_planning': is_planning,
        'status': 'completed'
    }

    # Update run history
    for idx in final_manning.index:
        history = safe_eval_history(final_manning.at[idx, 'run_history'])

        # Check if this row was reallocated
        was_reallocated = (
            pd.notna(final_manning.at[idx, 'original_emp']) and
            pd.notna(final_manning.at[idx, 'allocated_emp_id']) and
            final_manning.at[idx, 'original_emp'] != final_manning.at[idx, 'allocated_emp_id']
        )

        if was_reallocated:
            reason = final_manning.at[idx, 'reallocation_reason']
            history.append({
                'run_timestamp': run_timestamp,
                'previous_emp': final_manning.at[idx, 'original_emp'],
                'new_emp': final_manning.at[idx, 'allocated_emp_id'],
                'reason': reason
            })

        final_manning.at[idx, 'run_history'] = str(history)
        final_manning.at[idx, 'current_run'] = str(run_record)

    # Calculate statistics
    shortage_rows = working_manning[working_manning['shortage_flag'].isin(["Partial Shortage", "Shortage Unresolved"])]

    stats = {
        'run_timestamp': run_timestamp,
        'allocation_date': allocation_date,
        'plan_source': plan_source,
        'total_allocations': len(final_manning),
        'total_absent': len(current_absent),
        'total_shortages': len(shortage_rows),
        'allocations_affected': len(affected_allocations),
        'successful_reallocations': len(reallocation_tracking),
        'failed_reallocations': final_manning[final_manning['shortage_flag'].str.contains('Failed', na=False)].shape[0],
        'reallocation_by_level': pd.Series(final_manning['reallocation_level'].dropna()).value_counts().to_dict(),
        'reallocation_by_reason': pd.Series(final_manning['reallocation_reason'].dropna()).value_counts().to_dict(),
        'is_planning': is_planning
    }

    # Check for any over-utilization
    over_allocated = emp_fact_df[emp_fact_df["remaining_capacity"] < 0]
    if not over_allocated.empty:
        print(f"WARNING: {len(over_allocated)} employees have been over-allocated!")
        print(over_allocated[["employee_id", "employee_name", "remaining_capacity"]])
        stats['over_allocated_employees'] = len(over_allocated)
    else:
        stats['over_allocated_employees'] = 0

    return final_manning, stats, reallocation_tracking



def perform_dday_allocation(allocation_date, attendance_df, emp_fact_df, wip_df=None):
    """
    Original allocation function preserved for backward compatibility
    Calls the enhanced version
    """
    return perform_dday_allocation_enhanced(allocation_date, attendance_df, emp_fact_df, wip_df)


################## Reporting Functions ############################
def generate_reallocation_report(stats, reallocation_tracking):
    """
    Generate a detailed report of reallocations
    """
    report = f"""
        D-Day Allocation Report for {stats['allocation_date'].strftime('%Y-%m-%d')}
        Based on {stats['plan_source']} plan
        ------------------------------------------------
        Total Allocations: {stats['total_allocations']}
        Total Absent Employees: {stats['total_absent']}
        Total Shortage Issues: {stats['total_shortages']}
        Allocations Affected: {stats['allocations_affected']}
        Successful Reallocations: {stats['successful_reallocations']}
        Failed Reallocations: {stats['failed_reallocations']}
        Over-allocated Employees: {stats.get('over_allocated_employees', 0)}

        Reallocation by Level:
        {pd.DataFrame([stats['reallocation_by_level']]).to_string()}

        Reallocation by Reason:
        {pd.DataFrame([stats['reallocation_by_reason']]).to_string() if 'reallocation_by_reason' in stats else 'No reason data'}

        Detailed Reallocation Tracking:
        {pd.DataFrame(reallocation_tracking).to_string()}
    """
    return report



def analyze_skill_shortages(manning_df, emp_fact_df):
    """
    Analyze skill shortages and suggest OT based on next day's plan

    Parameters:
    manning_df (DataFrame): The manning dataframe with allocations
    emp_fact_df (DataFrame): Employee fact table with skill information

    Returns:
    dict: Summary of skill shortages and OT recommendations
    """
    # Find operations with failed allocations
    shortage_ops = manning_df[
        manning_df['shortage_flag'].str.contains('Failed', na=False)
    ]

    # Group shortages by code to see which skills are most needed
    skill_shortage_counts = shortage_ops.groupby('code').size()

    # Find which employees could potentially work OT to cover these shortages
    ot_recommendations = {}

    for code, count in skill_shortage_counts.items():
        # Find employees with this skill (both primary and secondary)
        primary_skilled = emp_fact_df[(emp_fact_df['code'] == code) & (emp_fact_df['type'] == 'Primary')]
        secondary_skilled = emp_fact_df[(emp_fact_df['code'] == code) & (emp_fact_df['type'] == 'Secondary')]

        # Combine and sort by capacity
        potential_ot = pd.concat([primary_skilled, secondary_skilled]).drop_duplicates('employee_id')
        potential_ot = potential_ot.sort_values(by='average_capacity', ascending=False)

        # Store top 5 employees who could work OT for this skill
        if not potential_ot.empty:
            ot_recommendations[code] = potential_ot[['employee_id', 'employee_name', 'line']].head(5).to_dict('records')
        else:
            ot_recommendations[code] = []

    return {
        'shortage_count_by_skill': skill_shortage_counts.to_dict(),
        'ot_recommendations': ot_recommendations
    }



def analyze_mass_absenteeism(attendance_df, allocation_date, emp_details):
    """
    Identify patterns of mass absenteeism in specific lines or departments

    Parameters:
    attendance_df (DataFrame): Attendance data
    allocation_date (datetime): The date for analysis

    Returns:
    dict: Summary of absenteeism patterns
    """
    # Filter attendance for the allocation date
    daily_attendance = attendance_df[attendance_df['attendance_date'] == allocation_date]

    # Skip if no attendance data
    if daily_attendance.empty:
        return {'mass_absenteeism_found': False}

    # Get latest status for each employee
    if 'last_updated' in daily_attendance.columns:
        daily_attendance['last_updated'] = pd.to_datetime(daily_attendance['last_updated'], errors='coerce')
        latest_attendance = daily_attendance.sort_values('last_updated').groupby('employee_id').last()
    else:
        latest_attendance = daily_attendance.groupby('employee_id').first()

    latest_attendance = latest_attendance.drop(columns=['line', 'factory', 'floor', 'section'], errors='ignore')

    # Count absences by different groupings
    # We'll need to merge with employee fact table to get these groupings
    try:
        # Add employee details for grouping
        merged_attendance = pd.merge(
            latest_attendance.reset_index(),
            emp_details[['employee_id', 'line', 'factory', 'floor', 'section']],
            on='employee_id',
            how='left'
        )

        # Calculate absence percentages
        by_line = merged_attendance.groupby('line').apply(
            lambda x: (x['status'] == 'A').mean() * 100
        ).sort_values(ascending=False)

        by_section = merged_attendance.groupby('section').apply(
            lambda x: (x['status'] == 'A').mean() * 100
        ).sort_values(ascending=False)

        by_floor = merged_attendance.groupby('floor').apply(
            lambda x: (x['status'] == 'A').mean() * 100
        ).sort_values(ascending=False)

        # Identify areas with high absenteeism (over 15%)
        high_absence_lines = by_line[by_line > 15].to_dict()
        high_absence_sections = by_section[by_section > 15].to_dict()
        high_absence_floors = by_floor[by_floor > 15].to_dict()

        mass_absenteeism_found = bool(high_absence_lines or high_absence_sections or high_absence_floors)

        return {
            'mass_absenteeism_found': mass_absenteeism_found,
            'high_absence_lines': high_absence_lines,
            'high_absence_sections': high_absence_sections,
            'high_absence_floors': high_absence_floors
        }

    except Exception as e:
        print(f"Error analyzing mass absenteeism: {e}")
        return {'mass_absenteeism_found': False, 'error': str(e)}



################## Time-Based Allocation Functions ############################
def run_intraday_allocation_enhanced(allocation_date, attendance_df, emp_fact_df, wip_df=None, run_type="morning"):
    """
    Run specific allocation logic based on time of day (morning, noon, or evening)

    Parameters:
    allocation_date (datetime): The date for which to perform allocation
    attendance_df (DataFrame): Attendance data
    emp_fact_df (DataFrame): Employee fact table with capacity information
    wip_df (DataFrame, optional): WIP data containing quantities at each operation
    run_type (str): Type of run - "morning" (8:50 AM), "noon" (12:45 PM), or "evening" (5:30 PM)

    Returns:
    tuple: (Manning dataframe, statistics dict, reallocation tracking list)
    """
    if run_type == "morning":
        # Morning run (8:50 AM): Initial line balancing with op_seq logic
        print("Running 8:50 AM allocation with op_seq prioritization")
        return perform_dday_allocation_enhanced(
            allocation_date=allocation_date, 
            attendance_df=attendance_df, 
            emp_fact_df=emp_fact_df, 
            wip_df=wip_df
        )

    elif run_type == "noon":
        # Noon run (12:45 PM): Re-evaluate based on morning progress
        print("Running 12:45 PM allocation with morning output evaluation")

        try:
            morning_manning = pd.DataFrame(list(
                DDayData.objects.all().values()
            ))
            print(f"Loaded morning Dday allocation..........")
        except Exception as e:
            print(f"Could not load morning allocation, starting fresh: {e}")
            # If we can't load morning results, just run a fresh allocation
            return perform_dday_allocation_enhanced(
                allocation_date=allocation_date, 
                attendance_df=attendance_df, 
                emp_fact_df=emp_fact_df, 
                wip_df=wip_df
            )

        # Run the allocation again with updated data
        # We'll use the morning_manning as a base to preserve the allocations that are working well
        # but react to new attendance issues and completion status
        return perform_dday_allocation_enhanced(
            allocation_date=allocation_date,
            attendance_df=attendance_df,
            emp_fact_df=emp_fact_df,
            wip_df=wip_df,
            morning_manning=morning_manning  # Pass the morning results
        )

    elif run_type == "evening":
        # Evening run (5:30 PM): Plan for next day with backlog
        print("Running 5:30 PM allocation for next day planning")

        # Calculate tomorrow's date
        next_day = allocation_date + pd.Timedelta(days=1)

        # Keep incrementing until a valid working day is found
        while True:
            isWorkingDay, reason = is_allowed_working_day(next_day.date())
            print(isWorkingDay, reason)
            if isWorkingDay:
                break
            next_day += pd.Timedelta(days=1)

        # 1. Calculate cumulative sum for D-day + D+1 day planned targets
        # Get tomorrow's planned allocation
        try:
            tomorrow_manning, _ = load_planned_allocation(next_day, None)
            print(f"Loaded planning data for {next_day.strftime('%Y-%m-%d')}")
        except Exception as e:
            print(f"No planning data found for tomorrow, using empty DataFrame: {e}")
            # Create an empty DataFrame with the same structure as today's
            today_manning, _ = load_planned_allocation(allocation_date, None)
            tomorrow_manning = today_manning.copy().iloc[0:0]  # Empty DataFrame with same columns

        # 2. Check WIP at end of D-day and add to next day's plan
        # Load latest WIP data
        # Add today's backlog to tomorrow's plan - here we DO add WIP to the planned quantities
        if wip_df is not None:
            try:
                tomorrow_with_backlog = add_wip_backlog(tomorrow_manning, wip_df)
                print("Loaded end-of-day WIP data")
            except Exception as e:
                print(f"No evening WIP update found, using existing WIP data: {e}")
                tomorrow_with_backlog = tomorrow_manning

        # 3. Check for planned leaves tomorrow
        try:
            # Check for planned leaves tomorrow
            leaves_df = pd.read_csv('csv_files/Planned_Leaves.csv')
            employee_id_col = 'Empployee ID' if 'Empployee ID' in leaves_df.columns else 'Employee ID'
            print("Loaded planned leaves data")

            # Filter for tomorrow's leaves
            leaves_df['Date'] = pd.to_datetime(leaves_df['Date'])
            tomorrow_leaves = leaves_df[leaves_df['Date'] == next_day][employee_id_col].tolist()


            # Mark these employees as unavailable
            emp_fact_df.loc[emp_fact_df['employee_id'].isin(tomorrow_leaves), 'PLANNED_LEAVE'] = True
        except Exception as e:
            print(f"No planned leaves data found: {e}")
            tomorrow_leaves = []

        # 4. Plan next day's allocation considering planned leaves
        tomorrow_allocation, stats, tracking = perform_dday_allocation_enhanced(
            next_day,
            attendance_df,  # We'll still use today's attendance as a base
            emp_fact_df,
            wip_df,
            morning_manning=tomorrow_with_backlog,
            is_planning=True,  # Flag to indicate this is planning mode, not execution
            planned_leaves=tomorrow_leaves
        )

        # 5. Identify skill shortages for potential OT
        skill_shortages = analyze_skill_shortages(tomorrow_allocation, emp_fact_df)

        # 6. Identify mass absenteeism
        mass_absenteeism = analyze_mass_absenteeism(attendance_df, allocation_date, emp_fact_df)

        # Add evening-specific reporting
        stats['skill_shortages_summary'] = skill_shortages
        stats['mass_absenteeism_summary'] = mass_absenteeism

        return tomorrow_allocation, stats, tracking

    else:
        # Invalid run type
        raise ValueError(f"Invalid run_type: {run_type}. Must be 'morning', 'noon', or 'evening'.")




################## Unallocated Report Functions ############################
def generate_unallocated_report(emp_fact_df, allocation_date, attendance_df=None, manning_df=None):
    """
    Generate report of employees who are truly unallocated (not in D-day allocation or additional employees)

    Parameters:
    emp_fact_df (DataFrame): Employee fact table
    allocation_date (datetime): The date for which allocation was performed
    attendance_df (DataFrame, optional): Attendance data for determining absence reasons
    manning_df (DataFrame, optional): Manning dataframe with allocations

    Returns:
    DataFrame: Report of truly unallocated employees
    """

    if manning_df is None:
        print("Warning: No manning dataframe provided. Cannot determine unallocated employees.")
        return pd.DataFrame()

    # Get all unique employee IDs from emp_fact_df
    all_employee_ids = set(emp_fact_df['employee_id'].unique())

    # Get allocated employee IDs from main allocation
    allocated_main = set()
    if 'allocated_emp_id' in manning_df.columns:
        allocated_main = set(manning_df['allocated_emp_id'].dropna().unique())

    # Get employee IDs from additional employees column
    allocated_additional = set()
    if 'additional_employees' in manning_df.columns:
        for additional_emp_info in manning_df['additional_employees'].dropna():
            if pd.notna(additional_emp_info) and additional_emp_info != "":
                # Extract employee ID from the additional employees string
                # Format is like: "+ John Doe (ID: 12345, Capacity: 150)"
                import re
                id_matches = re.findall(r'ID:\s*(\d+)', str(additional_emp_info))
                for emp_id in id_matches:
                    try:
                        allocated_additional.add(float(emp_id))  # Convert to float to match emp_fact_df format
                    except ValueError:
                        allocated_additional.add(emp_id)  # Keep as string if conversion fails

    # Combine all allocated employee IDs
    all_allocated = allocated_main.union(allocated_additional)

    # Find truly unallocated employees
    unallocated_employee_ids = all_employee_ids - all_allocated

    print(f"Total employees: {len(all_employee_ids)}")
    print(f"Allocated in main: {len(allocated_main)}")
    print(f"Allocated as additional: {len(allocated_additional)}")
    print(f"Total allocated: {len(all_allocated)}")
    print(f"Truly unallocated: {len(unallocated_employee_ids)}")

    # Create unallocated report
    unallocated_report = pd.DataFrame()

    # Process each unallocated employee
    for emp_id in unallocated_employee_ids:
        # Get employee records from emp_fact_df (may have multiple rows for different skills)
        emp_records = emp_fact_df[emp_fact_df['employee_id'] == emp_id]

        if emp_records.empty:
            continue

        # For each skill the employee has, create a report row
        for idx, emp_record in emp_records.iterrows():
            emp_name = emp_record['employee_name']
            line = emp_record.get('line', '')
            section = emp_record.get('section', '')
            code = emp_record.get('code', '')
            emp_type = emp_record.get('type', '')

            # Determine reason for not being allocated
            reason = determine_unallocation_reason(
                emp_id, emp_record, attendance_df, manning_df, allocation_date
            )

            # Create report record
            report_record = {
                'date': allocation_date.strftime('%Y-%m-%d'),
                'employee_id': emp_id,
                'employee_name': emp_name,
                'line': line if pd.notna(line) else '',
                'section': section if pd.notna(section) else '',
                'code': code if pd.notna(code) else '',
                'type': emp_type if pd.notna(emp_type) else '',
                'reason': reason
            }

            unallocated_report = pd.concat([unallocated_report, pd.DataFrame([report_record])], ignore_index=True)

    # Sort by employee ID and then by code
    if not unallocated_report.empty:
        unallocated_report = unallocated_report.sort_values(['employee_id', 'code'])

    return unallocated_report

def generate_unallocated_report_safe(emp_fact_df, allocation_date, attendance_df, manning_df):
    """
    Safe wrapper that doesn't depend on remaining_capacity column
    """
    try:
        return generate_unallocated_report(emp_fact_df, allocation_date, attendance_df, manning_df)
    except Exception as e:
        print(f"Error generating unallocated report: {e}")
        return pd.DataFrame()

def determine_unallocation_reason(emp_id, emp_record, attendance_df=None, manning_df=None, allocation_date=None):
    """
    Determine why an employee was not allocated

    Returns:
    str: Reason for non-allocation
    """

    # Check if employee was absent
    if attendance_df is not None and allocation_date is not None:
        try:
            daily_attendance = attendance_df[attendance_df['attendance_date'] == allocation_date]
            if not daily_attendance.empty:
                emp_attendance = daily_attendance[daily_attendance['employee_id'] == emp_id]
                if not emp_attendance.empty:
                    status = emp_attendance['status'].iloc[-1]  # Get latest status
                    if status == 'A':
                        return "Employee Absent"
                    elif 'early_departure' in emp_attendance.columns and emp_attendance['early_departure'].iloc[-1]:
                        return "Early Departure"
        except Exception as e:
            pass  # Continue with other checks if attendance check fails

    # Check if there was work available for this employee's skill
    if manning_df is not None:
        employee_skill = emp_record.get('code', '')
        employee_line = emp_record.get('line', '')

        if employee_skill:
            # Check if there was any work for this skill code
            matching_work = manning_df[manning_df['code'] == employee_skill]
            if matching_work.empty:
                return "No Work Available for Skill"

            # Check if there was work in their line
            if employee_line:
                same_line_work = matching_work[matching_work['line'] == employee_line]
                if same_line_work.empty:
                    return "No Work in Employee's Line"

            # Work was available in their line but they weren't selected
            return "Not Selected Despite Available Work"

    # Default reason
    return "Reason Unknown"

def analyze_unallocated_patterns(unallocated_report):
    """
    Analyze patterns in the unallocated employees report

    Parameters:
    unallocated_report (DataFrame): The unallocated report

    Returns:
    dict: Analysis summary with key insights
    """

    if unallocated_report.empty:
        return {
            'total_unallocated': 0,
            'message': 'All employees have been allocated!'
        }

    total_unallocated = len(unallocated_report)
    unique_employees = unallocated_report['employee_id'].nunique()

    # Analyze by reason
    reason_analysis = unallocated_report.groupby('reason').agg({
        'employee_id': 'nunique'
    }).rename(columns={
        'employee_id': 'Unique_Employees'
    }).sort_values('Unique_Employees', ascending=False)

    # Analyze by line
    line_analysis = unallocated_report.groupby('line').agg({
        'employee_id': 'nunique'
    }).rename(columns={
        'employee_id': 'Unique_Employees'
    }).sort_values('Unique_Employees', ascending=False)

    # Analyze by skill code
    skill_analysis = unallocated_report.groupby('code').agg({
        'employee_id': 'nunique'
    }).rename(columns={
        'employee_id': 'Unique_Employees'
    }).sort_values('Unique_Employees', ascending=False)

    # Analyze by employee type
    type_analysis = unallocated_report.groupby('type').agg({
        'employee_id': 'nunique'
    }).rename(columns={
        'employee_id': 'Unique_Employees'
    }).sort_values('Unique_Employees', ascending=False)

    # Get employees with multiple unallocated skills
    multi_skill_unallocated = unallocated_report.groupby('employee_id').size()
    multi_skill_employees = multi_skill_unallocated[multi_skill_unallocated > 1].sort_values(ascending=False)

    analysis_summary = {
        'total_unallocated_records': total_unallocated,
        'unique_unallocated_employees': unique_employees,
        'reason_breakdown': reason_analysis.to_dict('index'),
        'line_breakdown': line_analysis.head(10).to_dict('index'),
        'skill_breakdown': skill_analysis.head(10).to_dict('index'),
        'type_breakdown': type_analysis.to_dict('index'),
        'multi_skill_employees': multi_skill_employees.head(10).to_dict() if not multi_skill_employees.empty else {}
    }

    return analysis_summary

def print_unallocated_summary(analysis_summary):
    """
    Print a formatted summary of the unallocated analysis

    Parameters:
    analysis_summary (dict): Analysis summary from analyze_unallocated_patterns
    """

    if 'message' in analysis_summary:
        print("\n" + "="*80)
        print("UNALLOCATED EMPLOYEES ANALYSIS")
        print("="*80)
        print(analysis_summary['message'])
        return

    print("\n" + "="*80)
    print("UNALLOCATED EMPLOYEES ANALYSIS SUMMARY")
    print("="*80)

    print(f"Total Unallocated Records: {analysis_summary['total_unallocated_records']}")
    print(f"Unique Unallocated Employees: {analysis_summary['unique_unallocated_employees']}")

    print(f"\nREASON BREAKDOWN:")
    print("-" * 40)
    for reason, data in analysis_summary['reason_breakdown'].items():
        print(f"{reason}: {data['Unique_Employees']} employees")

    print(f"\nTOP LINES WITH UNALLOCATED EMPLOYEES:")
    print("-" * 40)
    for line, data in list(analysis_summary['line_breakdown'].items())[:5]:
        print(f"Line {line}: {data['Unique_Employees']} employees")

    print(f"\nTOP SKILLS WITH UNALLOCATED EMPLOYEES:")
    print("-" * 40)
    for skill, data in list(analysis_summary['skill_breakdown'].items())[:5]:
        print(f"Skill {skill}: {data['Unique_Employees']} employees")

    print(f"\nEMPLOYEE TYPE BREAKDOWN:")
    print("-" * 40)
    for emp_type, data in analysis_summary['type_breakdown'].items():
        print(f"{emp_type}: {data['Unique_Employees']} employees")

    if analysis_summary['multi_skill_employees']:
        print(f"\nEMPLOYEES WITH MULTIPLE UNALLOCATED SKILLS:")
        print("-" * 50)
        for emp_id, skill_count in list(analysis_summary['multi_skill_employees'].items())[:5]:
            print(f"Employee {emp_id}: {skill_count} unallocated skills")

    print("="*80)


def analyze_allocation_gaps(manning_df, unallocated_df):
    """
    Analyze gaps between what could be allocated vs what was allocated
    """
    # Find operations with unmet planned quantities
    unmet_operations = manning_df[
        (manning_df['planned_qty'] > manning_df['allocated_capacity'].fillna(0)) &
        (manning_df['shortage_flag'] != 'Completed')
    ].copy()

    if unmet_operations.empty:
        return {"message": "All planned quantities have been fully allocated!"}

    # Calculate unmet quantities by skill code
    unmet_operations['unmet_qty'] = unmet_operations['planned_qty'] - unmet_operations['allocated_capacity'].fillna(0)
    unmet_by_skill = unmet_operations.groupby('code')['unmet_qty'].sum().sort_values(ascending=False)

    # Find available capacity by skill code
    available_by_skill = unallocated_df[unallocated_df['remaining_capacity'] > 0].groupby('code')['remaining_capacity'].sum().sort_values(ascending=False)

    # Identify potential matches
    potential_matches = {}
    for skill_code in unmet_by_skill.index:
        unmet_qty = unmet_by_skill[skill_code]
        available_qty = available_by_skill.get(skill_code, 0)

        if available_qty > 0:
            potential_fulfillment = min(unmet_qty, available_qty)
            potential_matches[skill_code] = {
                'unmet_quantity': unmet_qty,
                'available_capacity': available_qty,
                'potential_fulfillment': potential_fulfillment,
                'fulfillment_percentage': (potential_fulfillment / unmet_qty * 100)
            }

    return {
        'unmet_operations_count': len(unmet_operations),
        'total_unmet_quantity': unmet_by_skill.sum(),
        'unmet_by_skill': unmet_by_skill.to_dict(),
        'available_by_skill': available_by_skill.to_dict(),
        'potential_matches': potential_matches,
        'total_potential_additional_allocation': sum([match['potential_fulfillment'] for match in potential_matches.values()])
    }


def perform_final_allocation_pass(manning_df, emp_fact_df, absent_employees=None):
    """
    Perform a final comprehensive allocation pass to maximize utilization
    of planned quantities with remaining employee capacity
    """
    print("Starting final allocation pass to maximize planned quantity fulfillment...")

    # Create absent set for faster lookups
    if absent_employees is None:
        absent_employees = set()
    elif not isinstance(absent_employees, set):
        absent_employees = set(absent_employees)

    # Create a copy to avoid modifying original
    enhanced_manning = manning_df.copy()

    # Build consolidated employee capacity map
    employee_capacity_map = build_employee_capacity_map(emp_fact_df)

    # Pre-populate with existing allocations to track current usage
    for idx, row in enhanced_manning.iterrows():
        emp_id = row['allocated_emp_id']
        if pd.notna(emp_id) and emp_id not in absent_employees:
            allocation_capacity = row.get('allocated_capacity', 0)
            if allocation_capacity > 0 and emp_id in employee_capacity_map:
                employee_capacity_map[emp_id]['remaining_capacity'] -= allocation_capacity
                employee_capacity_map[emp_id]['allocations'].append({
                    'row_idx': idx,
                    'allocation': allocation_capacity,
                    'line': row.get('line', ''),
                    'section': row.get('section', '')
                })

    # Find all rows with unmet planned quantities
    unmet_work = []
    for idx, row in enhanced_manning.iterrows():
        planned_qty = row['planned_qty']
        allocated_capacity = row.get('allocated_capacity', 0)

        # Skip completed work
        if row.get('shortage_flag') == 'Completed':
            continue

        # Check if planned quantity is not fully met
        if planned_qty > allocated_capacity:
            unmet_quantity = planned_qty - allocated_capacity
            unmet_work.append({
                'row_idx': idx,
                'unmet_quantity': unmet_quantity,
                'code': row['code'],
                'line': row['line'],
                'factory': row['factory'],
                'floor': row['floor'],
                'section': row['section'],
                'operation': row['operation'],
                'priority_score': calculate_priority_score(row)
            })

    # Sort unmet work by priority (higher priority first)
    unmet_work.sort(key=lambda x: x['priority_score'], reverse=True)

    print(f"Found {len(unmet_work)} operations with unmet planned quantities")

    additional_allocations = 0
    total_additional_capacity = 0

    # Try to fulfill unmet work with available employees
    for work_item in unmet_work:
        row_idx = work_item['row_idx']
        unmet_quantity = work_item['unmet_quantity']
        required_code = work_item['code']
        work_line = work_item['line']
        work_factory = work_item['factory']
        work_floor = work_item['floor']

        # Find available employees with matching skills using your existing function
        available_employee = get_prioritized_employees(emp_fact_df, line=work_line, code=required_code, absent_employees=absent_employees)

        # If no same-line employees, try same factory
        if available_employee.empty:
            available_employee = get_prioritized_employees(emp_fact_df, factory=work_factory, code=required_code, absent_employees=absent_employees)

        # If still no employees, try any location
        if available_employee.empty:
            available_employee = get_prioritized_employees(emp_fact_df, code=required_code, absent_employees=absent_employees)

        # Allocate to the best available employee
        if not available_employee.empty:
            best_emp = available_employee.iloc[0]
            emp_id = best_emp['employee_id']

            # Calculate how much we can allocate
            available_capacity = best_emp['remaining_capacity']
            allocation_amount = min(unmet_quantity, available_capacity)

            if allocation_amount > 0:
                # Check if this row already has an allocation
                current_allocation = enhanced_manning.loc[row_idx, 'allocated_capacity']

                if pd.isna(current_allocation) or current_allocation == 0:
                    # No existing allocation - create new one
                    enhanced_manning.loc[row_idx, 'allocated_emp_id'] = emp_id
                    enhanced_manning.loc[row_idx, 'allocated_emp_name'] = best_emp['employee_name']
                    enhanced_manning.loc[row_idx, 'allocated_capacity'] = allocation_amount
                    enhanced_manning.loc[row_idx, 'allocated_frm_line'] = best_emp['line']
                    enhanced_manning.loc[row_idx, 'allocated_frm_factory'] = best_emp['factory']
                    enhanced_manning.loc[row_idx, 'allocated_frm_floor'] = best_emp['floor']
                    enhanced_manning.loc[row_idx, 'shortage_flag'] = 'Final Pass Allocation'
                    enhanced_manning.loc[row_idx, 'reallocation_level'] = 'final_optimization'
                    enhanced_manning.loc[row_idx, 'reallocation_reason'] = 'maximize_planned_quantity'

                else:
                    # Existing allocation - increase it (multi-employee allocation)
                    enhanced_manning.loc[row_idx, 'allocated_capacity'] = current_allocation + allocation_amount
                    enhanced_manning.loc[row_idx, 'shortage_flag'] = 'Multi-Employee Allocation'
                    enhanced_manning.loc[row_idx, 'reallocation_level'] = 'final_optimization_addition'
                    # Store additional employee info in a new column
                    # additional_emp_info = f"+ {best_emp['employee_name']} ({allocation_amount})"
                    additional_emp_info = f"+ {best_emp['employee_name']} (ID: {best_emp['employee_id']}, Capacity: {allocation_amount})"
                    if 'additional_employees' not in enhanced_manning.columns:
                        enhanced_manning['additional_employees'] = None
                    enhanced_manning.loc[row_idx, 'additional_employees'] = additional_emp_info

                # Update targets
                new_total_capacity = enhanced_manning.loc[row_idx, 'allocated_capacity']
                enhanced_manning.loc[row_idx, 'target_100'] = new_total_capacity
                enhanced_manning.loc[row_idx, 'target_90'] = new_total_capacity * 0.9

                # Update emp_fact_df remaining capacity
                emp_fact_df.loc[emp_fact_df['employee_id'] == emp_id, 'remaining_capacity'] -= allocation_amount

                additional_allocations += 1
                total_additional_capacity += allocation_amount

                print(f"Additional allocation: {best_emp['employee_name']} -> Row {row_idx}, Capacity: {allocation_amount}")

    print(f"Final allocation pass completed:")
    print(f"- Additional allocations: {additional_allocations}")
    print(f"- Total additional capacity allocated: {total_additional_capacity}")

    return enhanced_manning


def calculate_priority_score(row):
    """
    Calculate priority score for work allocation
    Higher score = higher priority
    """
    score = 0

    # Priority 1: Operations with critical timing (early op_seq)
    if 'op_seq' in row and pd.notna(row['op_seq']):
        # Lower OP_SEQ gets higher priority
        score += (20 - min(row['op_seq'], 20)) * 10

    # Priority 2: Larger planned quantities (more impact)
    planned_qty = row.get('planned_qty', 0)
    score += min(planned_qty / 100, 50)  # Cap contribution at 50 points

    # Priority 3: Premium lines or critical buyers
    line = str(row.get('line', ''))
    if 'A' in line or '1' in line:  # Assuming A lines or Line 1 are premium
        score += 30

    # Priority 4: Operations that are partially allocated (shows demand exists)
    current_allocation = row.get('allocated_capacity', 0)
    if current_allocation > 0:
        score += 20  # Boost for partially allocated operations

    return score