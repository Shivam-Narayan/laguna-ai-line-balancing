import logging

logger = logging.getLogger(__name__)

import ast
import math
import os
from datetime import datetime

import pandas as pd
import pytz
from django.utils import timezone

from apps.absenteeism.utils import is_allowed_working_day

from .models import DDayData, ManningSheetData

MORNING_TIME = "08:50"
NOON_TIME = "12:45"
EVENING_TIME = "17:30"


def get_ist_time(override_time: str = None):
    """
    Get current time in IST timezone.
    :param override_time: Optional string in "HH:MM" format (24-hour) to simulate time, e.g., "12:45"
    """
    ist = pytz.timezone("Asia/Kolkata")

    if override_time:
        try:
            hours, minutes = map(int, override_time.split(":"))
            today = timezone.now().astimezone(ist).date()
            simulated_time = datetime(
                today.year, today.month, today.day, hours, minutes
            )
            return ist.localize(simulated_time)
        except Exception as e:
            raise ValueError(
                "Invalid override_time format. Use 'HH:MM'. Error: " + str(e)
            )

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
            logger.info(f"Using fake time: {fake_time_str}")
            current_time = fake_time
        except ValueError:
            logger.info(
                f"Invalid time format: {fake_time_str}. Using real time instead."
            )
            current_time = datetime.now().time()
    else:
        # Use the real current time
        current_time = datetime.now().time()
        logger.info(f"Using real time: {current_time.strftime('%H:%M')}")

    # Determine run type based on the time
    if current_time >= evening_time:
        return "evening"
    elif current_time >= noon_time:
        return "noon"
    else:
        return "morning"


class EmployeeCapacityTracker:
    """Tracks employee capacity across multiple skill types with vectorized operations"""

    def __init__(self, emp_fact_df):
        """Initialize capacity tracker from employee fact table"""
        self.emp_fact_df = emp_fact_df.copy()
        self.total_used_capacity = {}  # Track total capacity used per employee
        self.skill_capacities = {}  # Cache skill capacities
        self.initialize_capacity()

    def initialize_capacity(self):
        """Initialize capacity tracking dictionaries"""
        # Create employee capacity map once
        for _, row in self.emp_fact_df.iterrows():
            emp_id = row["employee_id"]
            skill_code = row["code"]
            capacity = row["average_capacity"]

            if emp_id not in self.total_used_capacity:
                self.total_used_capacity[emp_id] = 0

            # Cache skill capacities for fast lookup
            key = (emp_id, skill_code)
            self.skill_capacities[key] = capacity

    def get_effective_remaining_capacity(self, emp_id, skill_code):
        """Get effective remaining capacity for a specific employee and skill"""
        # Fast lookup from cache
        skill_capacity = self.skill_capacities.get((emp_id, skill_code), 0)
        if skill_capacity == 0:
            return 0

        # Get total used capacity for this employee
        used_capacity = self.total_used_capacity.get(emp_id, 0)

        # Effective remaining capacity
        effective_remaining = max(0, skill_capacity - used_capacity)
        return effective_remaining

    def calculate_effective_remaining_capacity_vectorized(self, emp_df):
        """
        Calculate effective remaining capacity for all employees at once

        Parameters:
        -----------
        emp_df : pandas.DataFrame
            Employee dataframe

        Returns:
        --------
        pandas.DataFrame
            DataFrame with added effective_remaining_capacity column
        """
        # Create a copy to avoid modifying the original
        result_df = emp_df.copy()

        # Create a vectorized calculation
        def calculate_row(row):
            emp_id = row["employee_id"]
            code = row["code"]
            skill_capacity = self.skill_capacities.get((emp_id, code), 0)
            used_capacity = self.total_used_capacity.get(emp_id, 0)
            return max(0, skill_capacity - used_capacity)

        # Apply calculation to all rows at once
        result_df["effective_remaining_capacity"] = result_df.apply(
            calculate_row, axis=1
        )

        return result_df

    def allocate_capacity(self, emp_id, allocation):
        """Allocate capacity to an employee, updating all skill capacities"""
        # Update total used capacity
        current_used = self.total_used_capacity.get(emp_id, 0)
        self.total_used_capacity[emp_id] = current_used + allocation

        # Update remaining capacity in the emp_fact_df
        mask = self.emp_fact_df["employee_id"] == emp_id
        self.emp_fact_df.loc[mask, "remaining_capacity"] = self.emp_fact_df.loc[
            mask
        ].apply(
            lambda row: max(
                0, row["average_capacity"] - self.total_used_capacity[emp_id]
            ),
            axis=1,
        )

        return True

    def get_capacity_summary(self):
        """Generate a summary of capacity utilization"""
        summary = []
        for emp_id, used in self.total_used_capacity.items():
            if used > 0:
                # Find this employee in the dataframe
                emp_info = self.emp_fact_df[self.emp_fact_df["employee_id"] == emp_id]
                if not emp_info.empty:
                    name = emp_info.iloc[0]["employee_name"]
                    primary_capacity = emp_info.iloc[0]["average_capacity"]

                    summary.append(
                        {
                            "employee_id": emp_id,
                            "employee_name": name,
                            "PRIMARY CAPACITY": primary_capacity,
                            "USED CAPACITY": used,
                            "UTILIZATION PCT": min(100, (used / primary_capacity) * 100)
                            if primary_capacity > 0
                            else 0,
                        }
                    )

        return pd.DataFrame(summary)


################## Employee Prioritization Functions ############################
def get_prioritized_employees(
    emp_df, line=None, factory=None, floor=None, code=None, emp_type=None
):
    """
    Consistent prioritization logic from original D-day system
    """
    query = emp_df["remaining_capacity"] > 0

    if line:
        query &= emp_df["line"] == line
    if factory:
        query &= emp_df["factory"] == factory
    if floor:
        query &= emp_df["floor"] == floor
    if code:
        query &= emp_df["code"] == code

    if emp_type:
        query &= (
            emp_df["type"] == emp_type
        )  # This ensures Primary and Secondary are handled separately

    return emp_df[query].sort_values(
        by=["type", "remaining_capacity"], ascending=[True, False]
    )


def check_floaters_for_allocation(
    emp_fact_df, code, line=None, factory=None, floor=None
):
    """
    Check specifically for floaters with matching skills
    Simplified version to ensure compatibility
    """
    # Make a copy of the employee dataframe
    emp_df = emp_fact_df.copy()

    # Base query for employees with positive capacity and matching code
    query = (emp_df["remaining_capacity"] > 0) & (emp_df["code"] == code)

    # Check if FLOATER column exists
    if "FLOATER" in emp_df.columns:
        query &= emp_df["FLOATER"] == True
    elif "designation" in emp_df.columns:
        # Look for "Floater" in designation
        query &= emp_df["designation"].str.contains("Floaters", case=False, na=False)
    else:
        # Consider employees with empty line as potential floaters
        query &= emp_df["line"].isna() | (emp_df["line"] == "")

    # Apply location filters if specified
    if line:
        query &= emp_df["line"] == line
    if factory:
        query &= emp_df["factory"] == factory
    if floor:
        query &= emp_df["floor"] == floor

    # Return prioritized floaters
    return emp_df[query].sort_values(
        by=["type", "remaining_capacity"], ascending=[True, False]
    )


def find_preferred_employees(
    emp_fact_df, code=None, line=None, factory=None, floor=None, current_emp_id=None
):
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

    # First try same line
    if line:
        same_line_employees = get_prioritized_employees(
            emp_fact_df, line=line, code=code
        )
        if not same_line_employees.empty:
            # Exclude current employee
            if current_emp_id is not None and not pd.isna(current_emp_id):
                same_line_employees = same_line_employees[
                    same_line_employees["employee_id"] != current_emp_id
                ]

            if not same_line_employees.empty:
                # Create list with employee names and their line
                preferred_same_line = [
                    f"{row['employee_name']} - {row['employee_id']} [Line: {row['line']}, Capacity: {row['remaining_capacity']}]"
                    for _, row in same_line_employees.iterrows()
                ]

    # Try same factory
    if factory:
        same_factory_employees = get_prioritized_employees(
            emp_fact_df, factory=factory, code=code
        )
        if not same_factory_employees.empty:
            # Exclude current employee and those already in same line
            same_factory_employees = same_factory_employees[
                (same_factory_employees["employee_id"] != current_emp_id)
                & (same_factory_employees["line"] != line)
            ]

            if not same_factory_employees.empty:
                preferred_same_factory = [
                    f"{row['employee_name']} - {row['employee_id']}  [Line: {row['line']}, Capacity: {row['remaining_capacity']}]"
                    for _, row in same_factory_employees.iterrows()
                ]

    # Try same floor
    if floor:
        same_floor_employees = get_prioritized_employees(
            emp_fact_df, floor=floor, code=code
        )
        if not same_floor_employees.empty:
            # Exclude current employee and those from same line or factory
            if factory:
                same_floor_employees = same_floor_employees[
                    (same_floor_employees["employee_id"] != current_emp_id)
                    & (same_floor_employees["line"] != line)
                    & (same_floor_employees["factory"] != factory)
                ]
            else:
                same_floor_employees = same_floor_employees[
                    (same_floor_employees["employee_id"] != current_emp_id)
                    & (same_floor_employees["line"] != line)
                ]

            if not same_floor_employees.empty:
                preferred_same_floor = [
                    f"{row['employee_name']} - {row['employee_id']}  [Line: {row['line']}, Capacity: {row['remaining_capacity']}]"
                    for _, row in same_floor_employees.iterrows()
                ]

    # Try any location
    anywhere_employees = get_prioritized_employees(emp_fact_df, code=code)
    if not anywhere_employees.empty:
        # Exclude current employee and those already included in other categories
        if floor and factory:
            anywhere_employees = anywhere_employees[
                (anywhere_employees["employee_id"] != current_emp_id)
                & (anywhere_employees["line"] != line)
                & (anywhere_employees["factory"] != factory)
                & (anywhere_employees["floor"] != floor)
            ]
        elif factory:
            anywhere_employees = anywhere_employees[
                (anywhere_employees["employee_id"] != current_emp_id)
                & (anywhere_employees["line"] != line)
                & (anywhere_employees["factory"] != factory)
            ]
        elif floor:
            anywhere_employees = anywhere_employees[
                (anywhere_employees["employee_id"] != current_emp_id)
                & (anywhere_employees["line"] != line)
                & (anywhere_employees["floor"] != floor)
            ]
        else:
            anywhere_employees = anywhere_employees[
                (anywhere_employees["employee_id"] != current_emp_id)
                & (anywhere_employees["line"] != line)
            ]

        if not anywhere_employees.empty:
            preferred_anywhere = [
                f"{row['employee_name']} - {row['employee_id']} [Line: {row['line']}, Capacity: {row['remaining_capacity']}]"
                for _, row in anywhere_employees.iterrows()
            ]

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
    if "backlog_flag" not in updated_manning.columns:
        updated_manning["backlog_flag"] = None

    # Add original planned qty column to track the initial values
    if "original_planned_qty" not in updated_manning.columns:
        updated_manning["original_planned_qty"] = updated_manning["planned_qty"]

    # Define the columns to join on - these identify a unique operation
    join_columns = [
        "oc_no",
        "order_no",
        "buyer",
        "sytle",
        "line",
        "color",
        "section",
        "operation",
        "code",
    ]

    # Make sure all join columns exist in both dataframes
    join_columns = [
        col
        for col in join_columns
        if col in updated_manning.columns and col in wip_df.columns
    ]

    # If there are no common columns to join on, return the original dataframe
    if not join_columns:
        logger.info(
            "Warning: No common columns found between manning and WIP dataframes"
        )
        return updated_manning

    # Convert join columns to a consistent type (string in this case)
    for col in join_columns:
        wip_df[col] = wip_df[col].astype(str)
        planned_manning_df[col] = planned_manning_df[col].astype(str)

    # Perform the merge to identify matching rows
    merged_df = pd.merge(
        updated_manning, wip_df[join_columns + ["wip_qty"]], on=join_columns, how="left"
    )

    # Fill NaN WIP quantities with 0
    merged_df["wip_qty"] = merged_df["wip_qty"].fillna(0)

    # Update planned quantities and set backlog flag
    for idx, row in merged_df.iterrows():
        if row["wip_qty"] > 0:
            # Add WIP quantity to the planned quantity
            updated_manning.loc[idx, "planned_qty"] = (
                row["original_planned_qty"] + row["wip_qty"]
            )
            updated_manning.loc[idx, "backlog_flag"] = "Backlog Included"

            # Also update allocated capacity and target capacities based on new planned quantities
            if "target_100" in updated_manning.columns:
                # If this row has been allocated, update the capacity and targets proportionally
                if pd.notna(updated_manning.loc[idx, "allocated_capacity"]):
                    # Calculate the ratio of allocation to original planned quantity
                    ratio = (
                        updated_manning.loc[idx, "allocated_capacity"]
                        / row["original_planned_qty"]
                    )

                    # Calculate new total quantity (original + WIP)
                    new_total_qty = row["original_planned_qty"] + row["wip_qty"]

                    # Update the allocated capacity proportionally
                    new_allocated_capacity = new_total_qty * ratio
                    updated_manning.loc[idx, "allocated_capacity"] = (
                        new_allocated_capacity
                    )

                    # Update targets based on new allocated capacity
                    updated_manning.loc[idx, "target_100"] = new_allocated_capacity
                    updated_manning.loc[idx, "target_90"] = new_allocated_capacity * 0.9

                    # Log the change for debugging
                    logger.info(
                        f"Updated allocated capacity for idx {idx}: {row['original_planned_qty']} -> {new_total_qty}, "
                        f"Allocated: {updated_manning.loc[idx, 'allocated_capacity']} -> {new_allocated_capacity}"
                    )

    logger.info(
        f"Added backlog to {merged_df[merged_df['wip_qty'] > 0].shape[0]} operations"
    )
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
    manning_0_df = ManningSheetData.objects.filter(
        planned_dates=allocation_date
    ).values()
    manning_0_df = pd.DataFrame(list(manning_0_df))
    if manning_0_df.empty:
        raise ValueError(
            f"No manning sheet data found for allocation date: {allocation_date}"
        )
    manning_0_df["planned_dates"] = pd.to_datetime(manning_0_df["planned_dates"])
    manning_0_df["allocated_emp_name"] = (
        "Allocated_Employee_Name"  # Assigning dummy value to 'allocated_emp_name' as fetching from emp_fact while inserting
    )
    # Filter for the specific date
    plan_0 = manning_0_df[manning_0_df["planned_dates"] == allocation_date]

    if not plan_0.empty:
        # Add WIP backlog if WIP dataframe is provided and add_backlog is True
        if wip_df is not None and add_backlog:
            plan_0 = add_wip_backlog(plan_0, wip_df)
            return plan_0, "D-day with Backlog"
        return plan_0, "D-day"
    else:
        raise ValueError(
            f"No D-day planned allocation found for date: {allocation_date}"
        )


def identify_affected_allocations(
    planned_manning_df, absent_employees, handle_shortages=True
):
    """
    Identify allocations that need to be modified due to:
    1. Attendance issues (absences, early departures)
    2. Partial shortages or unresolved shortages (if handle_shortages=True)
    """
    # First identify allocations affected by attendance
    affected_allocations = planned_manning_df[
        planned_manning_df["allocated_emp_id"].isin(absent_employees)
    ].copy()

    # If requested, also identify allocations with shortage flags
    if handle_shortages:
        shortage_allocations = planned_manning_df[
            planned_manning_df["shortage_flag"].isin(
                ["Partially Shortage", "Shortage Unresolved"]
            )
        ].copy()

        # Combine with attendance-affected allocations (without duplicates)
        affected_allocations = pd.concat(
            [affected_allocations, shortage_allocations]
        ).drop_duplicates()

    # Mark the original allocation details for tracking
    affected_allocations["original_allocation"] = affected_allocations.apply(
        lambda row: {
            "emp_id": row["allocated_emp_id"],
            # 'emp_name': row['allocated_emp_name'], # Commented 'allocated_emp_name' as fetching from emp_fact while inserting
            "line": row["allocated_frm_line"],
            "capacity": row["allocated_capacity"],
            "shortage_flag": row["shortage_flag"] if "shortage_flag" in row else None,
        },
        axis=1,
    ).astype(str)

    return affected_allocations


def balance_by_operation_sequence_enhanced(
    planned_manning_df, emp_fact_df, wip_df=None
):
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

    # Ensure op_seq column exists
    if "op_seq" not in balanced_manning.columns:
        logger.info("Warning: op_seq column not found. Creating dummy sequence.")
        # Create a temporary sequence based on operation order
        balanced_manning["op_seq"] = (
            balanced_manning.groupby(["line", "section"]).cumcount() + 1
        )

    # Sort by LINE and op_seq for sequential processing
    balanced_manning = balanced_manning.sort_values(by=["line", "op_seq"])

    # Add columns for WIP analysis
    balanced_manning["wip_quantity"] = 0
    balanced_manning["wip_ratio"] = 0
    balanced_manning["optimal_wip_buffer"] = 0
    balanced_manning["excess_capacity"] = 0
    balanced_manning["resource_status"] = None

    # Join WIP data if available
    if wip_df is not None:
        # Define columns to join on
        join_columns = [
            col
            for col in ["line", "section", "operation", "code"]
            if col in balanced_manning.columns and col in wip_df.columns
        ]

        if join_columns:
            # Find WIP quantity column
            # wip_qty_col = next((col for col in wip_df.columns
            #                    if 'WIP' in col.upper() and 'QTY' in col.upper()), None).
            wip_qty_col = (
                "wip_qty"  # Assuming the WIP quantity column is named 'wip_qty'
            )

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
                    how="left",
                )

                # Update WIP quantities
                merged_df[wip_qty_col] = merged_df[wip_qty_col].fillna(0)
                balanced_manning["wip_quantity"] = merged_df[wip_qty_col]

    # 1. Calculate capacity metrics for each operation
    for idx, row in balanced_manning.iterrows():
        if pd.notna(row["allocated_capacity"]) and row["allocated_capacity"] > 0:
            # Calculate hours needed based on planned quantity and allocated capacity
            planned_qty = row["planned_qty"]
            allocated_capacity = row["allocated_capacity"]

            # Calculate estimated hours to complete
            hours_needed = (
                planned_qty / allocated_capacity
                if allocated_capacity > 0
                else float("inf")
            )
            balanced_manning.at[idx, "estimated_completion_time"] = min(hours_needed, 8)

            # Calculate standard expected hourly output
            hourly_output = allocated_capacity / 8  # Assuming 8-hour workday

            # Calculate optimal WIP buffer (2 hours of work for next operation)
            balanced_manning.at[idx, "optimal_wip_buffer"] = hourly_output * 2

            # Determine if operation has excess capacity
            if hours_needed < 6 and row["wip_quantity"] > hourly_output * 1:
                # Operation will finish early and has at least 1 hour of WIP buffer
                excess_hours = 6 - hours_needed
                balanced_manning.at[idx, "excess_capacity"] = excess_hours * (
                    allocated_capacity / 8
                )
                balanced_manning.at[idx, "resource_status"] = "EXCESS"
            elif hours_needed > 8:
                # Operation is understaffed
                balanced_manning.at[idx, "resource_status"] = "SHORTAGE"
            else:
                # Operation is balanced
                balanced_manning.at[idx, "resource_status"] = "BALANCED"

    # 2. Calculate WIP ratios between sequential operations
    for line, group in balanced_manning.groupby("line"):
        # Sort by operation sequence
        line_ops = group.sort_values("op_seq")

        # Calculate WIP ratios between consecutive operations
        for i in range(len(line_ops) - 1):
            current_op_idx = line_ops.iloc[i].name
            next_op_idx = line_ops.iloc[i + 1].name

            current_wip = balanced_manning.at[current_op_idx, "wip_quantity"]
            optimal_buffer = balanced_manning.at[next_op_idx, "optimal_wip_buffer"]

            if optimal_buffer > 0:
                # Calculate ratio of current WIP to optimal buffer
                wip_ratio = current_wip / optimal_buffer
                balanced_manning.at[next_op_idx, "wip_ratio"] = wip_ratio

                # Categorize WIP status
                if wip_ratio > 1.5:
                    # More than enough WIP for next operation
                    balanced_manning.at[current_op_idx, "wip_status"] = "EXCESS"
                elif wip_ratio < 0.5:
                    # Not enough WIP for next operation
                    balanced_manning.at[current_op_idx, "wip_status"] = "SHORTAGE"
                else:
                    # Just right
                    balanced_manning.at[current_op_idx, "wip_status"] = "OPTIMAL"

    # 3. Find operations that have excess capacity and could donate resources
    potential_donors = balanced_manning[
        (balanced_manning["resource_status"] == "EXCESS")
        & (balanced_manning["excess_capacity"] > 0)
    ]

    # 4. Find operations that need more resources to prevent halts
    critical_recipients = balanced_manning[
        (balanced_manning["resource_status"] == "SHORTAGE")
        & (balanced_manning["wip_ratio"] < 0.5)  # Low incoming WIP ratio
    ]

    # 5. Track reallocation actions
    reallocation_actions = []

    # 6. First handle critical shortages that could halt production
    for idx, recipient in critical_recipients.iterrows():
        recipient_line = recipient["line"]
        recipient_code = recipient["code"]
        recipient_op = recipient["op_seq"]

        # Look for donors in the same line first
        same_line_donors = potential_donors[
            (potential_donors["line"] == recipient_line)
            & (potential_donors["op_seq"] < recipient_op)  # Earlier operations first
        ]

        if not same_line_donors.empty:
            # Found potential donor in same line
            donor = same_line_donors.iloc[0]
            donor_idx = donor.name

            # Check if employees can be transferred
            donor_emp_id = donor["allocated_emp_id"]
            if pd.isna(donor_emp_id):
                continue

            # Verify employee has the required skill
            emp_has_skill = False
            matching_skills = emp_fact_df[
                (emp_fact_df["employee_id"] == donor_emp_id)
                & (emp_fact_df["code"] == recipient_code)
            ]

            if not matching_skills.empty:
                emp_has_skill = True

            if emp_has_skill:
                # Calculate capacity to transfer (up to 50% of excess)
                transfer_capacity = min(
                    donor["excess_capacity"] * 0.5,
                    recipient["planned_qty"] / 4,  # At most enough for 2 hours of work
                )

                if transfer_capacity > 0:
                    # Record reallocation action
                    reallocation_actions.append(
                        {
                            "from_line": donor["line"],
                            "from_op": donor["op_seq"],
                            "to_line": recipient_line,
                            "to_op": recipient_op,
                            "emp_id": donor_emp_id,
                            "capacity": transfer_capacity,
                            "reason": "critical_shortage_prevention",
                        }
                    )

                    # Update donor's excess capacity
                    balanced_manning.at[donor_idx, "excess_capacity"] -= (
                        transfer_capacity
                    )

                    # If donor no longer has excess, remove from potential donors
                    if balanced_manning.at[donor_idx, "excess_capacity"] <= 0:
                        balanced_manning.at[donor_idx, "resource_status"] = "BALANCED"
                        potential_donors = potential_donors[
                            potential_donors.index != donor_idx
                        ]

                    # Update recipient's allocation
                    balanced_manning.at[idx, "allocated_emp_id"] = donor_emp_id
                    balanced_manning.at[idx, "allocated_capacity"] = transfer_capacity
                    balanced_manning.at[idx, "resource_status"] = "BALANCED"
                    balanced_manning.at[idx, "reallocation_reason"] = "WIP_optimization"
                    balanced_manning.at[idx, "reallocation_level"] = (
                        "critical_shortage_prevention"
                    )

        else:
            # Look for donors in other lines (cross-line balancing)
            other_line_donors = potential_donors[
                potential_donors["line"] != recipient_line
            ]

            if not other_line_donors.empty:
                # Similar logic for cross-line balancing...
                # This would be a more extensive version of the same allocation logic
                # with additional checks for movement between lines
                pass

    # 7. Next, balance WIP across operations to optimize flow
    # After handling critical shortages, optimize WIP buffers
    for line, group in balanced_manning.groupby("line"):
        # Process each line separately
        line_ops = group.sort_values("op_seq")

        for i in range(len(line_ops) - 1):
            current_op_idx = line_ops.iloc[i].name
            next_op_idx = line_ops.iloc[i + 1].name

            current_status = balanced_manning.at[current_op_idx, "resource_status"]
            next_status = balanced_manning.at[next_op_idx, "resource_status"]

            # If current operation has excess and next has shortage, balance them
            if (
                current_status == "EXCESS"
                and next_status == "SHORTAGE"
                and balanced_manning.at[current_op_idx, "excess_capacity"] > 0
            ):
                # Similar allocation logic as above, but for WIP optimization
                # between consecutive operations
                pass

    return balanced_manning


################## Enhanced Reallocation Functions ############################
def reallocate_work_enhanced(
    affected_allocations, emp_fact_df, allocation_date, wip_df=None, emp_type=None
):
    """
    Enhanced reallocation logic that considers floaters first and OP_SEQ

    Parameters:
    affected_allocations (DataFrame): Allocations that need to be modified
    emp_fact_df (DataFrame): Employee fact table with capacity information
    allocation_date (datetime): The date for which to perform allocation
    wip_df (DataFrame, optional): WIP data containing quantities at each operation
    emp_type (str, optional): Employee type to consider first (Primary or Secondary)

    Returns:
    tuple: (Reallocated allocations DataFrame, reallocation tracking list)
    """
    reallocation_tracking = []
    affected_allocations["reallocation_level"] = None
    affected_allocations["preferred_employees"] = None
    affected_allocations["re_allocated_employee"] = None

    # Sort affected allocations by LINE (for priority) and OP_SEQ if available
    if "op_seq" in affected_allocations.columns:
        affected_allocations = affected_allocations.sort_values(by=["line", "op_seq"])
    else:
        affected_allocations = affected_allocations.sort_values(by=["line"])

    # Keep track of processed employees to avoid over-allocation
    processed_employee_ids = set()

    for index, row in affected_allocations.iterrows():
        line = row["line"]
        section = row["section"]
        code = row["code"]
        planned_qty = row["planned_qty"]
        factory = row["factory"]
        floor = row["floor"]

        # Store OP_SEQ if available
        op_sequence = row.get("op_seq", None)

        # 1. Check floaters first (new step)
        available_employee = check_floaters_for_allocation(emp_fact_df, code=code)
        allocation_level = "floater"

        # 2. If no floaters, follow the existing hierarchy with enhanced prioritization
        if available_employee.empty:
            # Try same line with primary skill
            available_employee = get_prioritized_employees(
                emp_fact_df, line=line, code=code, emp_type=emp_type
            )
            allocation_level = "same_line"

        if available_employee.empty:
            # Try same line with secondary skill
            available_employee = get_prioritized_employees(
                emp_fact_df,
                line=line,
                code=code,
                emp_type="Secondary" if emp_type == "Primary" else "Primary",
            )
            allocation_level = "same_line_secondary"

        if available_employee.empty:
            # Try same factory with primary skill
            available_employee = get_prioritized_employees(
                emp_fact_df, factory=factory, code=code, emp_type=emp_type
            )
            allocation_level = "same_factory"

        if available_employee.empty:
            # Try same factory with secondary skill
            available_employee = get_prioritized_employees(
                emp_fact_df,
                factory=factory,
                code=code,
                emp_type="Secondary" if emp_type == "Primary" else "Primary",
            )
            allocation_level = "same_factory_secondary"

        if available_employee.empty:
            # Try same floor with primary skill
            available_employee = get_prioritized_employees(
                emp_fact_df, floor=floor, code=code, emp_type=emp_type
            )
            allocation_level = "same_floor"

        if available_employee.empty:
            # Try same floor with secondary skill
            available_employee = get_prioritized_employees(
                emp_fact_df,
                floor=floor,
                code=code,
                emp_type="Secondary" if emp_type == "Primary" else "Primary",
            )
            allocation_level = "same_floor_secondary"

        if available_employee.empty:
            # Try anywhere with primary skill
            available_employee = get_prioritized_employees(
                emp_fact_df, code=code, emp_type=emp_type
            )
            allocation_level = "other_location"

        if available_employee.empty:
            # Try anywhere with secondary skill
            available_employee = get_prioritized_employees(
                emp_fact_df,
                code=code,
                emp_type="Secondary" if emp_type == "Primary" else "Primary",
            )
            allocation_level = "other_location_secondary"

        # 3. Check OP_SEQ and WIP (new step)
        # If we still don't have an employee AND we're working with a valid OP_SEQ
        if available_employee.empty and op_sequence and wip_df is not None:
            # Try to find an employee from the next operation in this line
            next_sequence = op_sequence + 1

            # Get the next operation's employees
            next_op_rows = affected_allocations[
                (affected_allocations["line"] == line)
                & (affected_allocations["op_seq"] == next_sequence)
            ]

            if not next_op_rows.empty:
                next_op_row = next_op_rows.iloc[0]
                next_op_emp_id = next_op_row.get("allocated_emp_id")

                if next_op_emp_id and next_op_emp_id not in processed_employee_ids:
                    # Check if there's no WIP for the next operation
                    has_wip_for_next = False

                    # Assuming wip_df has columns matching affected_allocations for identification
                    # and a 'WIP QTY' column for quantities
                    if wip_df is not None:
                        # Create a key to match with WIP
                        wip_key_cols = ["line", "section", "operation", "code"]
                        wip_key_cols = [
                            col
                            for col in wip_key_cols
                            if col in next_op_row.index and col in wip_df.columns
                        ]

                        # wip_filter = True
                        # for col in wip_key_cols:
                        #     wip_filter &= (wip_df[col] == next_op_row[col])

                        # matching_wip = wip_df[wip_filter]

                        # ---Updated section to ensure Series of boolean values---
                        wip_filter = pd.Series([True] * len(wip_df), index=wip_df.index)
                        for col in wip_key_cols:
                            wip_filter &= wip_df[col] == next_op_row[col]

                        matching_wip = wip_df[wip_filter]

                        if not matching_wip.empty:
                            # wip_qty_col = next((col for col in matching_wip.columns if 'WIP' in col.upper() and 'QTY' in col.upper()), None)
                            wip_qty_col = "wip_qty"
                            if wip_qty_col and matching_wip[wip_qty_col].sum() > 0:
                                has_wip_for_next = True

                    if not has_wip_for_next:
                        # We can use this employee from the next operation
                        emp_info = emp_fact_df[
                            emp_fact_df["employee_id"] == next_op_emp_id
                        ]
                        if not emp_info.empty:
                            available_employee = emp_info
                            allocation_level = "operation_sequence_based"

        # Find and store preferred employees for manual assignment
        current_emp_id = row["allocated_emp_id"]
        preferred_employees = find_preferred_employees(
            emp_fact_df,
            code=code,
            line=line,
            factory=factory,
            floor=floor,
            current_emp_id=current_emp_id,
        )
        affected_allocations.at[index, "preferred_employees"] = preferred_employees

        # Process employee allocation if we found someone
        if not available_employee.empty:
            # Find the first employee with sufficient capacity
            employee_allocated = False

            for i in range(len(available_employee)):
                emp = available_employee.iloc[i]
                emp_id = emp["employee_id"]

                # Skip if already processed to avoid over-allocation
                if emp_id in processed_employee_ids:
                    continue

                # Check if employee has positive remaining capacity
                if emp["remaining_capacity"] <= 0:
                    continue

                # Calculate safe allocation amount
                allocation = min(planned_qty, emp["remaining_capacity"])

                # Skip if allocation is too small to be useful
                if allocation <= 0:
                    continue

                # Update capacity - calculate new remaining capacity to double-check
                new_remaining = emp["remaining_capacity"] - allocation
                if new_remaining < 0:
                    # Don't allow negative capacity
                    allocation = emp["remaining_capacity"]  # Take only what's available
                    new_remaining = 0

                # Update employee capacity
                emp_fact_df.loc[
                    emp_fact_df["employee_id"] == emp_id, "remaining_capacity"
                ] = new_remaining

                # Track reallocation
                reallocation = {
                    "original_emp": row["allocated_emp_id"],
                    "new_emp": emp_id,
                    "line": line,
                    "section": section,
                    "allocation_level": allocation_level,
                    "planned_qty": planned_qty,
                    "allocated_qty": allocation,
                    "remaining_capacity": new_remaining,
                    "operation_sequence": op_sequence,
                }
                reallocation_tracking.append(reallocation)

                # Update allocation details
                affected_allocations.at[index, "allocated_emp_id"] = emp_id
                affected_allocations.at[index, "allocated_emp_name"] = emp[
                    "employee_name"
                ]
                affected_allocations.at[index, "allocated_capacity"] = allocation
                affected_allocations.at[index, "allocated_frm_line"] = emp["line"]
                affected_allocations.at[index, "allocated_frm_factory"] = emp["factory"]
                affected_allocations.at[index, "allocated_frm_floor"] = emp["floor"]
                affected_allocations.at[index, "skill_type"] = emp["type"]
                affected_allocations.at[index, "machine"] = emp["machine"]
                affected_allocations.at[index, "designation"] = emp["designation"]
                affected_allocations.at[index, "target_100"] = planned_qty
                affected_allocations.at[index, "target_90"] = planned_qty * 0.9
                affected_allocations.at[index, "shortage_flag"] = (
                    f"Reallocated ({allocation_level})"
                )
                affected_allocations.at[index, "reallocation_level"] = allocation_level
                affected_allocations.at[index, "re_allocated_employee"] = emp[
                    "employee_name"
                ]

                # Mark as allocated
                employee_allocated = True
                processed_employee_ids.add(emp_id)

                # Found a suitable employee, break the loop
                break

            # Mark as failed if no suitable employee was found
            if not employee_allocated:
                affected_allocations.at[index, "shortage_flag"] = (
                    "Reallocation Failed - No Capacity"
                )
        else:
            affected_allocations.at[index, "shortage_flag"] = (
                "Reallocation Failed - No Matching Employee"
            )

    # Verify no over-allocation occurred
    over_allocated = emp_fact_df[emp_fact_df["remaining_capacity"] < 0]
    if not over_allocated.empty:
        logger.info("WARNING: Over-allocation detected during reallocation process!")
        logger.info(
            over_allocated[["employee_id", "employee_name", "remaining_capacity"]]
        )
        # Fix any negative capacities by setting to zero
        emp_fact_df.loc[emp_fact_df["remaining_capacity"] < 0, "remaining_capacity"] = 0

    return affected_allocations, reallocation_tracking


def reallocate_work(affected_allocations, emp_fact_df, allocation_date, emp_type=None):
    """
    Original reallocation function preserved for backward compatibility
    Calls the enhanced version
    """
    return reallocate_work_enhanced(
        affected_allocations, emp_fact_df, allocation_date, None, emp_type
    )


################## op_seq Balancing Functions ############################
def balance_by_operation_sequence(planned_manning_df, emp_fact_df, wip_df=None):
    """
    Alias for the enhanced balance function for backward compatibility
    """
    # This is a wrapper function to fix the missing function error
    return balance_by_operation_sequence_enhanced(
        planned_manning_df, emp_fact_df, wip_df
    )


################## Core Allocation Functions ############################
def perform_dday_allocation_enhanced(
    allocation_date,
    attendance_df,
    emp_fact_df,
    wip_df=None,
    morning_manning=None,
    is_planning=False,
    planned_leaves=None,
):
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
    emp_fact_df["remaining_capacity"] = emp_fact_df["average_capacity"]
    run_timestamp = get_ist_time()

    # If we're planning for tomorrow and have planned leaves, mark those employees as unavailable
    if is_planning and planned_leaves:
        emp_fact_df.loc[
            emp_fact_df["employee_id"].isin(planned_leaves), "remaining_capacity"
        ] = 0

    # Load D-day plan
    if morning_manning is not None:
        # For noon run, use the morning allocation as a base
        planned_manning = morning_manning
        plan_source = "Morning Allocation"
    else:
        # For morning or evening run, load from base data
        planned_manning, plan_source = load_planned_allocation(allocation_date)

    # Ensure op_seq column exists for sorting purposes
    if "op_seq" not in planned_manning.columns:
        logger.info("Warning: op_seq column not found. Creating sequence numbers.")
        # Create a sequence number within each line and section
        planned_manning["op_seq"] = (
            planned_manning.groupby(["line", "section"]).cumcount() + 1
        )

    # Sort by line (for priority) and op_seq
    working_manning = planned_manning.copy().sort_values(by=["line", "op_seq"])

    # Ensure all tracking columns exist
    tracking_columns = [
        "run_history",
        "current_run",
        "original_emp",
        # 'original_emp_name', # Commented 'original_emp_name' as fetching from emp_fact while inserting
        "new_emp",
        "reallocation_level",
        "re_allocated_employee",
        "preferred_employees",
        "reallocation_reason",
        "average_capacity_per_hour",
        "attendance_status",
        "estimated_completed_time",
        "wip_quantity",
        "completed_qty",  # New column for tracking completion (for noon run)
    ]
    for col in tracking_columns:
        if col not in working_manning.columns:
            working_manning[col] = None

    # Add WIP information if available
    if wip_df is not None:
        # Join WIP information
        join_columns = [
            "oc_no",
            "order_no",
            "buyer",
            "sytle",
            "line",
            "color",
            "section",
            "operation",
            "code",
        ]

        # Make sure all join columns exist in both dataframes
        join_columns = [
            col
            for col in join_columns
            if col in working_manning.columns and col in wip_df.columns
        ]

        # Convert join columns to strings for consistent joining
        for col in join_columns:
            wip_df[col] = wip_df[col].astype(str)
            working_manning[col] = working_manning[col].astype(str)

        # Perform the merge to add WIP information
        # wip_qty_col = next((col for col in wip_df.columns if 'WIP' in col.upper() and 'QTY' in col.upper()), None)
        wip_qty_col = "wip_qty"
        if wip_qty_col and join_columns:
            merged_df = pd.merge(
                working_manning,
                wip_df[join_columns + [wip_qty_col]],
                on=join_columns,
                how="left",
            )

            # Fill NaN WIP quantities with 0
            merged_df[wip_qty_col] = merged_df[wip_qty_col].fillna(0)

            # Store WIP quantity in our tracking column
            working_manning["wip_quantity"] = merged_df[wip_qty_col]
        else:
            logger.info("Warning: Could not add WIP information - missing columns")
            working_manning["wip_quantity"] = 0

    # For noon run, update based on completion status
    if morning_manning is not None and "completed_qty" in morning_manning.columns:
        # Update the planned quantities based on what's already completed
        for idx in working_manning.index:
            if (
                pd.notna(working_manning.loc[idx, "completed_qty"])
                and working_manning.loc[idx, "completed_qty"] > 0
            ):
                # Reduce planned quantity by completed amount
                original_qty = working_manning.loc[idx, "planned_qty"]
                completed_qty = working_manning.loc[idx, "completed_qty"]
                remaining_qty = max(0, original_qty - completed_qty)

                # Update the planned quantity to what remains
                working_manning.loc[idx, "original_planned_qty"] = original_qty
                working_manning.loc[idx, "planned_qty"] = remaining_qty

                # If fully completed, mark for removal from allocation
                if remaining_qty == 0:
                    working_manning.loc[idx, "shortage_flag"] = "Completed"

    # Process attendance
    attendance_df["attendance_date"] = pd.to_datetime(attendance_df["attendance_date"])

    # Filter attendance for the allocation date
    daily_attendance = attendance_df[
        attendance_df["attendance_date"] == allocation_date
    ]

    # Get latest status for each employee
    if not daily_attendance.empty:
        if "last_updated" in daily_attendance.columns:
            daily_attendance["last_updated"] = pd.to_datetime(
                daily_attendance["last_updated"],
                format="%Y-%m-%d %H:%M:%S",
                errors="coerce",
            )
            latest_attendance = (
                daily_attendance.sort_values("last_updated")
                .groupby("employee_id")
                .last()
            )
        else:
            latest_attendance = daily_attendance.groupby("employee_id").first()

        # Identify employees who are absent OR have early departure
        current_absent = latest_attendance[
            (latest_attendance["status"] == "A")
            | (latest_attendance["early_departure"] == True)
        ].index.tolist()

        # Identify present employees
        current_present = latest_attendance[
            latest_attendance["status"] == "P"
        ].index.tolist()

        # Create a Series mapping employee IDs to their attendance status
        attendance_status_map = latest_attendance["status"].copy()
        # Mark early departures
        early_departure_mask = latest_attendance["early_departure"] == True
        attendance_status_map[early_departure_mask] = (
            attendance_status_map[early_departure_mask] + " (Early Departure)"
        )
    else:
        current_absent = []
        current_present = []
        attendance_status_map = pd.Series(dtype="object")
        logger.info("Warning: No attendance data found for this date!")

    # Add planned leaves to absent list for planning runs
    if is_planning and planned_leaves:
        current_absent.extend(planned_leaves)

    # Handle capacity for absent and early departure employees
    emp_fact_df.loc[
        emp_fact_df["employee_id"].isin(current_absent), "remaining_capacity"
    ] = 0

    # Find allocations affected by absences and shortage flags
    affected_allocations = identify_affected_allocations(
        working_manning, current_absent, handle_shortages=True
    )

    # Perform reallocation with enhanced logic
    reallocated_manning, reallocation_tracking = reallocate_work_enhanced(
        affected_allocations,
        emp_fact_df,
        allocation_date,
        wip_df,
        emp_type="Primary",  # Start with primary skills
    )

    # After initial reallocation, perform op_seq-based balancing
    balanced_manning = balance_by_operation_sequence_enhanced(
        working_manning, emp_fact_df, wip_df
    )

    # Merge the results from reallocated_manning and balanced_manning
    final_manning = working_manning.copy()

    # First, update with reallocated data (for absences and shortages)
    for idx in reallocated_manning.index:
        # Determine reallocation reason
        if working_manning.loc[idx, "allocated_emp_id"] in current_absent:
            reallocation_reason = "attendance_issue"
        elif working_manning.loc[idx, "shortage_flag"] in [
            "Partially Shortage",
            "Shortage Unresolved",
        ]:
            reallocation_reason = "shortage_resolution"
        else:
            reallocation_reason = "other"

        # Preserve original employee information
        final_manning.loc[idx, "original_emp"] = working_manning.loc[
            idx, "allocated_emp_id"
        ]
        final_manning.loc[idx, "new_emp"] = reallocated_manning.loc[
            idx, "allocated_emp_id"
        ]
        final_manning.loc[idx, "reallocation_level"] = reallocated_manning.loc[
            idx, "reallocation_level"
        ]
        final_manning.loc[idx, "re_allocated_employee"] = reallocated_manning.loc[
            idx, "re_allocated_employee"
        ]
        final_manning.loc[idx, "preferred_employees"] = reallocated_manning.loc[
            idx, "preferred_employees"
        ]
        final_manning.loc[idx, "reallocation_reason"] = reallocation_reason

        # Update key allocation columns
        columns_to_update = [
            "allocated_emp_id",
            "allocated_emp_name",
            "allocated_capacity",
            "allocated_frm_line",
            "allocated_frm_factory",
            "allocated_frm_floor",
            "skill_type",
            "machine",
            "designation",
            "target_100",
            "target_90",
            "shortage_flag",
        ]

        for col in columns_to_update:
            if col in reallocated_manning.columns and col in final_manning.columns:
                final_manning.loc[idx, col] = reallocated_manning.loc[idx, col]

    # Then, update with sequence-based balancing data (overrides any previous allocations)
    for idx in balanced_manning.index:
        # Only update rows that were affected by the sequence-based balancing
        if balanced_manning.loc[idx, "shortage_flag"] == "Reallocated via op_seq":
            # Record original allocation for tracking
            if pd.isna(final_manning.loc[idx, "original_emp"]):
                final_manning.loc[idx, "original_emp"] = final_manning.loc[
                    idx, "allocated_emp_id"
                ]

            # Commented 'original_emp_name' as fetching from emp_fact while inserting
            # if pd.isna(final_manning.loc[idx, 'original_emp_name']):
            #     final_manning.loc[idx, 'original_emp_name'] = final_manning.loc[idx, 'allocated_emp_name']

            # Update allocation details
            final_manning.loc[idx, "allocated_emp_id"] = balanced_manning.loc[
                idx, "allocated_emp_id"
            ]
            final_manning.loc[idx, "shortage_flag"] = balanced_manning.loc[
                idx, "shortage_flag"
            ]
            final_manning.loc[idx, "allocated_capacity"] = balanced_manning.loc[
                idx, "allocated_capacity"
            ]
            final_manning.loc[idx, "allocated_frm_line"] = balanced_manning.loc[
                idx, "allocated_frm_line"
            ]
            final_manning.loc[idx, "shortage_flag"] = balanced_manning.loc[
                idx, "shortage_flag"
            ]
            final_manning.loc[idx, "reallocation_level"] = balanced_manning.loc[
                idx, "reallocation_level"
            ]
            final_manning.loc[idx, "reallocation_reason"] = "operation_sequence_based"

            # Add to reallocation tracking
            reallocation = {
                "original_emp": final_manning.loc[idx, "original_emp"],
                "new_emp": balanced_manning.loc[idx, "allocated_emp_id"],
                "line": final_manning.loc[idx, "line"],
                "section": final_manning.loc[idx, "section"],
                "allocation_level": "operation_sequence_based",
                "planned_qty": final_manning.loc[idx, "planned_qty"],
                "allocated_qty": balanced_manning.loc[idx, "allocated_capacity"],
                "operation_sequence": final_manning.loc[idx, "op_seq"],
            }
            reallocation_tracking.append(reallocation)

    # Update completion time estimates for all rows
    for idx, row in final_manning.iterrows():
        if pd.notna(row["allocated_capacity"]) and row["allocated_capacity"] > 0:
            # Calculate hours needed based on planned quantity and allocated capacity
            planned_qty = row["planned_qty"]
            allocated_capacity = row["allocated_capacity"]

            # Calculate estimated hours to complete (assuming 8-hour workday)
            hours_needed = (
                planned_qty / allocated_capacity
                if allocated_capacity > 0
                else float("inf")
            )

            # Cap at realistic workday limits (8 hours)
            hours_needed = min(hours_needed, 8)

            # Store estimated completion time (in hours from start of shift)
            final_manning.at[idx, "estimated_completed_time"] = hours_needed
        else:
            # Mark operations with no allocation
            final_manning.at[idx, "estimated_completed_time"] = float("inf")

    emp_fact_df["average_capacity/HR"] = emp_fact_df["average_capacity"] / 9
    # Add employee metadata from emp_fact_df
    # Create a Series mapping employee IDs to their average capacity per hour
    avg_capacity_per_hr_map = emp_fact_df.groupby("employee_id")[
        "average_capacity/HR"
    ].first()

    # Create a Series mapping employee IDs to their names
    emp_name_map = emp_fact_df.groupby("employee_id")["employee_name"].first()

    # Add the average capacity per hour based on the original employee ID (before reallocation)
    for idx in final_manning.index:
        emp_id = final_manning.loc[idx, "original_emp"]

        if (
            pd.isna(emp_id) or emp_id == ""
        ):  # If original_emp is empty, use allocated_emp_id
            emp_id = final_manning.loc[idx, "allocated_emp_id"]

        # Add original employee name
        if emp_id in emp_name_map:
            # final_manning.loc[idx, 'original_emp_name'] = emp_name_map[emp_id] # Commented 'original_emp_name' as fetching from emp_fact while inserting
            final_manning.loc[idx, "original_emp"] = emp_id

        # Add average capacity per hour
        if emp_id in avg_capacity_per_hr_map:
            final_manning.loc[idx, "average_capacity_per_hour"] = (
                avg_capacity_per_hr_map[emp_id]
            )

        # Add attendance status for the original employee
        if emp_id in attendance_status_map:
            final_manning.loc[idx, "attendance_status"] = attendance_status_map[emp_id]

    # Record this run's changes
    run_record = {
        "timestamp": run_timestamp,
        "absent_count": len(current_absent),
        "shortage_count": len(affected_allocations)
        - len(
            affected_allocations[
                affected_allocations["allocated_emp_id"].isin(current_absent)
            ]
        ),
        "reallocations": len(reallocation_tracking),
        "is_planning": is_planning,
        "status": "completed",
    }

    # Update run history
    for idx in final_manning.index:
        history = safe_eval_history(final_manning.at[idx, "run_history"])

        # Check if this row was reallocated
        was_reallocated = (
            pd.notna(final_manning.at[idx, "original_emp"])
            and pd.notna(final_manning.at[idx, "allocated_emp_id"])
            and final_manning.at[idx, "original_emp"]
            != final_manning.at[idx, "allocated_emp_id"]
        )

        if was_reallocated:
            reason = final_manning.at[idx, "reallocation_reason"]
            history.append(
                {
                    "run_timestamp": run_timestamp,
                    "previous_emp": final_manning.at[idx, "original_emp"],
                    "new_emp": final_manning.at[idx, "allocated_emp_id"],
                    "reason": reason,
                }
            )

        final_manning.at[idx, "run_history"] = str(history)
        final_manning.at[idx, "current_run"] = str(run_record)

    # Calculate statistics
    shortage_rows = working_manning[
        working_manning["shortage_flag"].isin(
            ["Partially Shortage", "Shortage Unresolved"]
        )
    ]

    stats = {
        "run_timestamp": run_timestamp,
        "allocation_date": allocation_date,
        "plan_source": plan_source,
        "total_allocations": len(final_manning),
        "total_absent": len(current_absent),
        "total_shortages": len(shortage_rows),
        "allocations_affected": len(affected_allocations),
        "successful_reallocations": len(reallocation_tracking),
        # 'failed_reallocations': len(final_manning[final_manning['shortage_flag'].str.contains('Failed', na=False)].shape[0]),
        "failed_reallocations": final_manning[
            final_manning["shortage_flag"].str.contains("Failed", na=False)
        ].shape[0],
        "reallocation_by_level": pd.Series(final_manning["reallocation_level"].dropna())
        .value_counts()
        .to_dict(),
        "reallocation_by_reason": pd.Series(
            final_manning["reallocation_reason"].dropna()
        )
        .value_counts()
        .to_dict(),
        "is_planning": is_planning,
    }

    # Check for any over-utilization
    over_allocated = emp_fact_df[emp_fact_df["remaining_capacity"] < 0]
    if not over_allocated.empty:
        logger.info(
            f"WARNING: {len(over_allocated)} employees have been over-allocated!"
        )
        logger.info(
            over_allocated[["employee_id", "employee_name", "remaining_capacity"]]
        )
        stats["over_allocated_employees"] = len(over_allocated)
    else:
        stats["over_allocated_employees"] = 0

    return final_manning, stats, reallocation_tracking


def perform_dday_allocation(allocation_date, attendance_df, emp_fact_df, wip_df=None):
    """
    Original allocation function preserved for backward compatibility
    Calls the enhanced version
    """
    return perform_dday_allocation_enhanced(
        allocation_date, attendance_df, emp_fact_df, wip_df
    )


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
        manning_df["shortage_flag"].str.contains("Failed", na=False)
    ]

    # Group shortages by code to see which skills are most needed
    skill_shortage_counts = shortage_ops.groupby("code").size()

    # Find which employees could potentially work OT to cover these shortages
    ot_recommendations = {}

    for code, count in skill_shortage_counts.items():
        # Find employees with this skill (both primary and secondary)
        primary_skilled = emp_fact_df[
            (emp_fact_df["code"] == code) & (emp_fact_df["type"] == "Primary")
        ]
        secondary_skilled = emp_fact_df[
            (emp_fact_df["code"] == code) & (emp_fact_df["type"] == "Secondary")
        ]

        # Combine and sort by capacity
        potential_ot = pd.concat([primary_skilled, secondary_skilled]).drop_duplicates(
            "employee_id"
        )
        potential_ot = potential_ot.sort_values(by="average_capacity", ascending=False)

        # Store top 5 employees who could work OT for this skill
        if not potential_ot.empty:
            ot_recommendations[code] = (
                potential_ot[["employee_id", "employee_name", "line"]]
                .head(5)
                .to_dict("records")
            )
        else:
            ot_recommendations[code] = []

    return {
        "shortage_count_by_skill": skill_shortage_counts.to_dict(),
        "ot_recommendations": ot_recommendations,
    }


################## Reporting Functions ############################
def generate_reallocation_report(stats, reallocation_tracking):
    """
    Generate a detailed report of reallocations
    """
    report = f"""
        D-Day Allocation Report for {stats["allocation_date"].strftime("%Y-%m-%d")}
        Based on {stats["plan_source"]} plan
        ------------------------------------------------
        Total Allocations: {stats["total_allocations"]}
        Total Absent Employees: {stats["total_absent"]}
        Total Shortage Issues: {stats["total_shortages"]}
        Allocations Affected: {stats["allocations_affected"]}
        Successful Reallocations: {stats["successful_reallocations"]}
        Failed Reallocations: {stats["failed_reallocations"]}
        Over-allocated Employees: {stats.get("over_allocated_employees", 0)}

        Reallocation by Level:
        {pd.DataFrame([stats["reallocation_by_level"]]).to_string()}

        Reallocation by Reason:
        {pd.DataFrame([stats["reallocation_by_reason"]]).to_string() if "reallocation_by_reason" in stats else "No reason data"}

        Detailed Reallocation Tracking:
        {pd.DataFrame(reallocation_tracking).to_string()}
    """
    return report


def generate_overtime_recommendations(manning_df, capacity_tracker, stats):
    """
    Generate overtime recommendations based on shortages and employee utilization

    Parameters:
    -----------
    manning_df : pandas.DataFrame
        Manning dataframe with allocations
    capacity_tracker : EmployeeCapacityTracker
        Tracker for employee capacity
    stats : dict
        Allocation statistics

    Returns:
    --------
    pandas.DataFrame
        Overtime recommendations
    """
    # Find all shortage operations
    shortages = manning_df[
        manning_df["shortage_flag"].str.contains("Shortage", na=False)
    ]

    if shortages.empty:
        return pd.DataFrame()  # No shortages, no overtime needed

    # Calculate shortage statistics by code and line
    shortage_by_code_line = (
        shortages.groupby(["line", "code", "section"])["planned_qty"]
        .sum()
        .reset_index()
    )
    shortage_by_code_line = shortage_by_code_line.sort_values(
        "planned_qty", ascending=False
    )

    # Get capacity utilization
    capacity_summary = capacity_tracker.get_capacity_summary()

    # Find employees with matching skills for shortage operations
    overtime_recommendations = []

    for _, shortage in shortage_by_code_line.iterrows():
        code = shortage["code"]
        line = shortage["line"]
        section = shortage["section"]
        qty = shortage["planned_qty"]

        # Find employees with this skill
        matching_employees = manning_df[
            (manning_df["code"] == code) & (manning_df["allocated_emp_id"].notna())
        ]["allocated_emp_id"].unique()

        for emp_id in matching_employees:
            # Get employee details
            emp_details = capacity_summary[capacity_summary["employee_id"] == emp_id]

            if not emp_details.empty:
                utilization = emp_details.iloc[0]["UTILIZATION PCT"]

                # Only recommend overtime for employees with high utilization (75%+)
                # as they are already skilled and productive
                if utilization >= 75:
                    overtime_recommendations.append(
                        {
                            "employee_id": emp_id,
                            "employee_name": emp_details.iloc[0]["employee_name"],
                            "line": line,
                            "code": code,
                            "section": section,
                            "SHORTAGE_QTY": qty,
                            "CURRENT_UTILIZATION": utilization,
                            "OVERTIME_HOURS_RECOMMENDED": min(
                                4,
                                math.ceil(
                                    qty / (emp_details.iloc[0]["PRIMARY CAPACITY"] / 8)
                                ),
                            ),
                            "REASON": "Critical shortage requiring skilled operator",
                        }
                    )

    # Convert to DataFrame and sort
    if overtime_recommendations:
        ot_df = pd.DataFrame(overtime_recommendations)
        ot_df = ot_df.sort_values(
            ["SHORTAGE_QTY", "CURRENT_UTILIZATION"], ascending=[False, False]
        )
        return ot_df

    return pd.DataFrame()


# Add this import at the top of the file


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
    daily_attendance = attendance_df[
        attendance_df["attendance_date"] == allocation_date
    ]

    # Skip if no attendance data
    if daily_attendance.empty:
        return {"mass_absenteeism_found": False}

    # Get latest status for each employee
    if "last_updated" in daily_attendance.columns:
        daily_attendance["last_updated"] = pd.to_datetime(
            daily_attendance["last_updated"], errors="coerce"
        )
        latest_attendance = (
            daily_attendance.sort_values("last_updated").groupby("employee_id").last()
        )
    else:
        latest_attendance = daily_attendance.groupby("employee_id").first()

    # emp_details.drop(columns=['line', 'section', 'factory', 'floor'], inplace=True)
    latest_attendance = latest_attendance.drop(
        columns=["line", "factory", "floor", "section"], errors="ignore"
    )

    # Count absences by different groupings
    # We'll need to merge with employee fact table to get these groupings
    try:
        # Add employee details for grouping
        merged_attendance = pd.merge(
            latest_attendance.reset_index(),
            emp_details[["employee_id", "line", "factory", "floor", "section"]],
            on="employee_id",
            how="left",
        )

        # Calculate absence percentages
        by_line = (
            merged_attendance.groupby("line")
            .apply(lambda x: (x["status"] == "A").mean() * 100)
            .sort_values(ascending=False)
        )

        by_section = (
            merged_attendance.groupby("section")
            .apply(lambda x: (x["status"] == "A").mean() * 100)
            .sort_values(ascending=False)
        )

        by_floor = (
            merged_attendance.groupby("floor")
            .apply(lambda x: (x["status"] == "A").mean() * 100)
            .sort_values(ascending=False)
        )

        # Identify areas with high absenteeism (over 15%)
        high_absence_lines = by_line[by_line > 15].to_dict()
        high_absence_sections = by_section[by_section > 15].to_dict()
        high_absence_floors = by_floor[by_floor > 15].to_dict()

        mass_absenteeism_found = bool(
            high_absence_lines or high_absence_sections or high_absence_floors
        )

        return {
            "mass_absenteeism_found": mass_absenteeism_found,
            "high_absence_lines": high_absence_lines,
            "high_absence_sections": high_absence_sections,
            "high_absence_floors": high_absence_floors,
        }

    except Exception as e:
        logger.info(f"Error analyzing mass absenteeism: {e}")
        return {"mass_absenteeism_found": False, "error": str(e)}


def analyze_and_save_mass_absenteeism(
    attendance_df, current_date, output_dir, emp_fact_df
):
    """
    Analyze mass absenteeism patterns and save results

    Parameters:
    -----------
    attendance_df : pandas.DataFrame
        Attendance data
    current_date : datetime
        Current date for analysis
    output_dir : str
        Directory to save output files

    Returns:
    --------
    dict
        Summary of absenteeism patterns
    """
    results = analyze_mass_absenteeism(attendance_df, current_date, emp_fact_df)

    try:
        # Convert results to DataFrames for saving
        absence_rates_df = pd.DataFrame(
            {
                "Date": list(results["daily_absence_rates"].keys()),
                "Absence_Rate": list(results["daily_absence_rates"].values()),
            }
        )

        # Save results
        absence_path = os.path.join(
            output_dir, f"absenteeism_analysis_{current_date.strftime('%Y%m%d')}.csv"
        )
        absence_rates_df.to_csv(absence_path, index=False)
        logger.info(f"Saved absenteeism analysis to {absence_path}")
    except Exception as e:
        logger.info(f"Warning: Could not save absenteeism analysis CSV: {e}")

    try:
        # Save summary to text file
        summary_path = os.path.join(
            output_dir, f"absenteeism_summary_{current_date.strftime('%Y%m%d')}.txt"
        )

        with open(summary_path, "w") as f:
            f.write(f"Absenteeism Analysis for {current_date.strftime('%Y-%m-%d')}\n")
            f.write(f"Latest absence rate: {results['latest_absence_rate']:.2f}%\n")
            f.write(f"Trend increasing: {results['trend_increasing']}\n")
            f.write(f"Trend decreasing: {results['trend_decreasing']}\n\n")

            f.write("Daily Absence Rates:\n")
            for date, rate in results["daily_absence_rates"].items():
                f.write(f"{date}: {rate:.2f}%\n")

            if results["mass_absenteeism_found"]:
                f.write("\nHigh Absence Areas:\n")

                if results["high_absence_lines"]:
                    f.write("\nBy Line:\n")
                    for line, rate in results["high_absence_lines"].items():
                        f.write(f"{line}: {rate:.2f}%\n")

                if results["high_absence_sections"]:
                    f.write("\nBy Section:\n")
                    for section, rate in results["high_absence_sections"].items():
                        f.write(f"{section}: {rate:.2f}%\n")

                if results["high_absence_floors"]:
                    f.write("\nBy Floor:\n")
                    for floor, rate in results["high_absence_floors"].items():
                        f.write(f"{floor}: {rate:.2f}%\n")
            else:
                f.write("\nNo significant mass absenteeism detected.\n")

        logger.info(f"Saved absenteeism summary to {summary_path}")
    except Exception as e:
        logger.info(f"Warning: Could not save absenteeism summary text: {e}")

    return results


################## Time-Based Allocation Functions ############################
def run_intraday_allocation_enhanced(
    allocation_date, attendance_df, emp_fact_df, wip_df=None, run_type="morning"
):
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
        logger.info("Running 8:50 AM allocation with op_seq prioritization")
        return perform_dday_allocation_enhanced(
            allocation_date=allocation_date,
            attendance_df=attendance_df,
            emp_fact_df=emp_fact_df,
            wip_df=wip_df,
        )

    elif run_type == "noon":
        # Noon run (12:45 PM): Re-evaluate based on morning progress
        logger.info("Running 12:45 PM allocation with morning output evaluation")

        try:
            morning_manning = pd.DataFrame(list(DDayData.objects.all().values()))
            logger.info("Loaded morning Dday allocation..........")
        except Exception as e:
            logger.info(f"Could not load morning allocation, starting fresh: {e}")
            # If we can't load morning results, just run a fresh allocation
            return perform_dday_allocation_enhanced(
                allocation_date=allocation_date,
                attendance_df=attendance_df,
                emp_fact_df=emp_fact_df,
                wip_df=wip_df,
            )

        # Run the allocation again with updated data
        # We'll use the morning_manning as a base to preserve the allocations that are working well
        # but react to new attendance issues and completion status
        return perform_dday_allocation_enhanced(
            allocation_date=allocation_date,
            attendance_df=attendance_df,
            emp_fact_df=emp_fact_df,
            wip_df=wip_df,
            morning_manning=morning_manning,  # Pass the morning results
        )

    elif run_type == "evening":
        # Evening run (5:30 PM): Plan for next day with backlog
        logger.info("Running 5:30 PM allocation for next day planning")

        # Calculate tomorrow's date
        next_day = allocation_date + pd.Timedelta(days=1)

        # Keep incrementing until a valid working day is found
        while True:
            isWorkingDay, reason = is_allowed_working_day(next_day.date())
            logger.info(isWorkingDay, reason)
            if isWorkingDay:
                break
            next_day += pd.Timedelta(days=1)

        # 1. Calculate cumulative sum for D-day + D+1 day planned targets
        # Get tomorrow's planned allocation
        try:
            tomorrow_manning, _ = load_planned_allocation(next_day, None)
            logger.info(f"Loaded planning data for {next_day.strftime('%Y-%m-%d')}")
        except Exception as e:
            logger.info(
                f"No planning data found for tomorrow, using empty DataFrame: {e}"
            )
            # Create an empty DataFrame with the same structure as today's
            today_manning, _ = load_planned_allocation(allocation_date, None)
            tomorrow_manning = today_manning.copy().iloc[
                0:0
            ]  # Empty DataFrame with same columns

        # 2. Check WIP at end of D-day and add to next day's plan
        # Load latest WIP data
        # Add today's backlog to tomorrow's plan - here we DO add WIP to the planned quantities
        if wip_df is not None:
            try:
                tomorrow_with_backlog = add_wip_backlog(tomorrow_manning, wip_df)
                logger.info("Loaded end-of-day WIP data")
            except Exception as e:
                logger.info(
                    f"No evening WIP update found, using existing WIP data: {e}"
                )
                tomorrow_with_backlog = tomorrow_manning

        # 3. Check for planned leaves tomorrow
        try:
            # # Load Excel
            # df = pd.read_excel("csv_files/LEAVE_APPLICATIONS_PENDING.xlsx")

            # employee_id_col = 'Empployee ID' if 'Empployee ID' in df.columns else 'Employee ID'

            # # Keep only the required columns and drop rows with any NaN in these
            # df_filtered = df[[employee_id_col, 'From', 'To']].dropna(subset=[employee_id_col, 'From', 'To'])

            # # Expand leave date ranges
            # def expand_date_ranges(row):
            #     start = pd.to_datetime(row['From'])
            #     end = pd.to_datetime(row['To'])
            #     date_range = pd.date_range(start, end)
            #     return [{employee_id_col: row[employee_id_col], 'Date': date} for date in date_range]

            # # Apply the expansion
            # expanded_rows = []
            # for _, row in df_filtered.iterrows():
            #     expanded_rows.extend(expand_date_ranges(row))

            # # Create final DataFrame
            # leaves_df = pd.DataFrame(expanded_rows)

            leaves_df = pd.read_csv("csv_files/Planned_Leaves.csv")
            employee_id_col = (
                "Empployee ID" if "Empployee ID" in leaves_df.columns else "Employee ID"
            )
            logger.info("Loaded planned leaves data")

            # Filter for tomorrow's leaves
            leaves_df["Date"] = pd.to_datetime(leaves_df["Date"])
            tomorrow_leaves = leaves_df[leaves_df["Date"] == next_day][
                employee_id_col
            ].tolist()

            # Mark these employees as unavailable
            emp_fact_df.loc[
                emp_fact_df["employee_id"].isin(tomorrow_leaves), "PLANNED_LEAVE"
            ] = True
        except Exception as e:
            logger.info(f"No planned leaves data found: {e}")
            tomorrow_leaves = []

        # 4. Plan next day's allocation considering planned leaves
        tomorrow_allocation, stats, tracking = perform_dday_allocation_enhanced(
            next_day,
            attendance_df,  # We'll still use today's attendance as a base
            emp_fact_df,
            wip_df,
            morning_manning=tomorrow_with_backlog,
            is_planning=True,  # Flag to indicate this is planning mode, not execution
            planned_leaves=tomorrow_leaves,
        )

        # 5. Identify skill shortages for potential OT
        skill_shortages = analyze_skill_shortages(tomorrow_allocation, emp_fact_df)

        # 6. Identify mass absenteeism
        mass_absenteeism = analyze_mass_absenteeism(
            attendance_df, allocation_date, emp_fact_df
        )

        # Add evening-specific reporting
        stats["skill_shortages_summary"] = skill_shortages
        stats["mass_absenteeism_summary"] = mass_absenteeism

        return tomorrow_allocation, stats, tracking

    else:
        # Invalid run type
        raise ValueError(
            f"Invalid run_type: {run_type}. Must be 'morning', 'noon', or 'evening'."
        )


def run_intraday_allocation(allocation_date, attendance_df, emp_fact_df, run_times):
    """
    Original intraday function preserved for backward compatibility
    """
    logger.info(
        "Warning: Using legacy intraday allocation function. Consider using run_intraday_allocation_enhanced instead."
    )

    daily_results = []
    previous_manning = None

    for run_time in sorted(run_times):
        logger.info(f"\nPerforming allocation run at {run_time}")

        # Perform allocation for this run
        manning, stats, tracking = perform_dday_allocation_enhanced(
            allocation_date,
            attendance_df,
            emp_fact_df,
            None,  # No WIP handling in original function
            previous_manning,
        )

        # Store results
        daily_results.append(
            {
                "run_time": run_time,
                "manning": manning,
                "stats": stats,
                "tracking": tracking,
            }
        )

        # Update previous manning for next run
        previous_manning = manning

        # Generate report for this run
        report = generate_reallocation_report(stats, tracking)
        logger.info(report)

        # Save this run's manning sheet
        run_time_str = run_time.strftime("%Y%m%d_%H%M")

        manning.to_csv(f"dday_manning_{run_time_str}.csv", index=False)

    return daily_results


# # # # # # # # # Discarded Functions # # # # # # # # #


def get_prioritized_employees_old(
    emp_df,
    capacity_tracker,
    line=None,
    factory=None,
    floor=None,
    code=None,
    section=None,
    emp_type=None,
    designation=None,
):
    """
    Fixed version that fetches prioritized employees based on effective remaining capacity
    """
    # Create a copy to avoid modifying the original dataframe
    emp_df_copy = emp_df.copy()

    # Calculate effective remaining capacity for each employee and skill
    # This adds the effective_remaining_capacity column
    emp_df_copy["effective_remaining_capacity"] = 0  # Initialize the column first

    for idx, row in emp_df_copy.iterrows():
        emp_id = row["employee_id"]
        code_value = row["code"]
        effective_remaining = capacity_tracker.get_effective_remaining_capacity(
            emp_id, code_value
        )
        emp_df_copy.at[idx, "effective_remaining_capacity"] = effective_remaining

    # Apply filters - make sure effective_remaining_capacity exists first
    query = emp_df_copy["effective_remaining_capacity"] > 0

    if line:
        query &= emp_df_copy["line"] == line
    if factory:
        query &= emp_df_copy["factory"] == factory
    if floor:
        query &= emp_df_copy["floor"] == floor
    if code:
        query &= emp_df_copy["code"] == code
    if section:
        query &= emp_df_copy["section"] == section
    if emp_type:
        query &= emp_df_copy["type"] == emp_type
    if designation:
        query &= emp_df_copy["designation"] == designation

    # Filter the dataframe
    filtered_df = emp_df_copy[query].copy()

    # Sort by type (Primary first) and effective remaining capacity
    filtered_df = filtered_df.sort_values(
        by=["type", "effective_remaining_capacity"], ascending=[True, False]
    )

    return filtered_df


def find_preferred_employees_old(
    emp_fact_df,
    capacity_tracker,
    code=None,
    line=None,
    factory=None,
    floor=None,
    current_emp_id=None,
):
    """
    Find preferred employees using the same prioritization logic as get_prioritized_employees
    Returns a comma-separated string of employee names with their line
    Now also includes unassigned employees with matching skills

    Parameters:
    emp_fact_df (DataFrame): The employee fact table
    capacity_tracker (EmployeeCapacityTracker): Tracker for employee capacity
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

    # Helper function to get capacity display string
    def get_capacity_string(df, row_idx):
        if "effective_remaining_capacity" in df.columns:
            return str(df.iloc[row_idx]["effective_remaining_capacity"])
        elif "remaining_capacity" in df.columns:
            return str(df.iloc[row_idx]["remaining_capacity"])
        else:
            return "Unknown"

    # First try same line
    if line:
        same_line_employees = get_prioritized_employees(
            emp_fact_df, capacity_tracker, line=line, code=code
        )
        if not same_line_employees.empty:
            # Exclude current employee
            if current_emp_id is not None and not pd.isna(current_emp_id):
                same_line_employees = same_line_employees[
                    same_line_employees["employee_id"] != current_emp_id
                ]

            if not same_line_employees.empty:
                # Create list with employee names and their line
                for i in range(len(same_line_employees)):
                    row = same_line_employees.iloc[i]
                    capacity = get_capacity_string(same_line_employees, i)
                    preferred_same_line.append(
                        f"{row['employee_name']} - {row['employee_id']} [Line: {row['line']}, Capacity: {capacity}]"
                    )

    # Try same factory
    if factory:
        same_factory_employees = get_prioritized_employees(
            emp_fact_df, capacity_tracker, factory=factory, code=code
        )
        if not same_factory_employees.empty:
            # Exclude current employee and those already in same line
            same_factory_employees = same_factory_employees[
                (same_factory_employees["employee_id"] != current_emp_id)
                & (same_factory_employees["line"] != line)
            ]

            if not same_factory_employees.empty:
                for i in range(len(same_factory_employees)):
                    row = same_factory_employees.iloc[i]
                    capacity = get_capacity_string(same_factory_employees, i)
                    preferred_same_factory.append(
                        f"{row['employee_name']} - {row['employee_id']} [Line: {row['line']}, Capacity: {capacity}]"
                    )

    # Try same floor
    if floor:
        same_floor_employees = get_prioritized_employees(
            emp_fact_df, capacity_tracker, floor=floor, code=code
        )
        if not same_floor_employees.empty:
            # Exclude current employee and those from same line or factory
            if factory:
                same_floor_employees = same_floor_employees[
                    (same_floor_employees["employee_id"] != current_emp_id)
                    & (same_floor_employees["line"] != line)
                    & (same_floor_employees["factory"] != factory)
                ]
            else:
                same_floor_employees = same_floor_employees[
                    (same_floor_employees["employee_id"] != current_emp_id)
                    & (same_floor_employees["line"] != line)
                ]

            if not same_floor_employees.empty:
                for i in range(len(same_floor_employees)):
                    row = same_floor_employees.iloc[i]
                    capacity = get_capacity_string(same_floor_employees, i)
                    preferred_same_floor.append(
                        f"{row['employee_name']} - {row['employee_id']} [Line: {row['line']}, Capacity: {capacity}]"
                    )

    # Try any location
    anywhere_employees = get_prioritized_employees(
        emp_fact_df, capacity_tracker, code=code
    )
    if not anywhere_employees.empty:
        # Exclude current employee and those already included in other categories
        if floor and factory:
            anywhere_employees = anywhere_employees[
                (anywhere_employees["employee_id"] != current_emp_id)
                & (anywhere_employees["line"] != line)
                & (anywhere_employees["factory"] != factory)
                & (anywhere_employees["floor"] != floor)
            ]
        elif factory:
            anywhere_employees = anywhere_employees[
                (anywhere_employees["employee_id"] != current_emp_id)
                & (anywhere_employees["line"] != line)
                & (anywhere_employees["factory"] != factory)
            ]
        elif floor:
            anywhere_employees = anywhere_employees[
                (anywhere_employees["employee_id"] != current_emp_id)
                & (anywhere_employees["line"] != line)
                & (anywhere_employees["floor"] != floor)
            ]
        else:
            anywhere_employees = anywhere_employees[
                (anywhere_employees["employee_id"] != current_emp_id)
                & (anywhere_employees["line"] != line)
            ]

        if not anywhere_employees.empty:
            for i in range(len(anywhere_employees)):
                row = anywhere_employees.iloc[i]
                capacity = get_capacity_string(anywhere_employees, i)
                preferred_anywhere.append(
                    f"{row['employee_name']} - {row['employee_id']} [Line: {row['line']}, Capacity: {capacity}]"
                )

    # Combine all lists with clear section headers
    all_preferred = []

    if preferred_same_line:
        all_preferred.append("SAME line: " + ", ".join(preferred_same_line))

    if preferred_same_factory:
        all_preferred.append("SAME factory: " + ", ".join(preferred_same_factory))

    if preferred_same_floor:
        all_preferred.append("SAME floor: " + ", ".join(preferred_same_floor))

    if preferred_anywhere:
        all_preferred.append("OTHER LOCATIONS: " + ", ".join(preferred_anywhere))

    return " | ".join(all_preferred)


def reallocate_work_enhanced_old(
    affected_allocations, emp_fact_df, allocation_date, wip_df=None, emp_type=None
):
    """
    Optimized version of the enhanced reallocation logic
    """
    import time

    start_time = time.time()

    # Initialize capacity tracker
    capacity_tracker = EmployeeCapacityTracker(emp_fact_df)
    logger.info(
        f"Capacity tracker initialization: {time.time() - start_time:.2f} seconds"
    )

    # Initialize output variables
    reallocation_tracking = []
    affected_allocations = affected_allocations.copy()
    affected_allocations["reallocation_level"] = None
    affected_allocations["preferred_employees"] = None
    affected_allocations["re_allocated_employee"] = None

    # Sort affected allocations
    if "op_seq" in affected_allocations.columns:
        affected_allocations = affected_allocations.sort_values(by=["line", "op_seq"])
    else:
        affected_allocations = affected_allocations.sort_values(by=["line"])

    # Pre-compute some common values to avoid recalculation
    processed_employee_ids = set()
    code_employee_cache = {}  # Cache employee queries by code

    # Precompute all floaters once
    floater_cache = {}

    # Process each allocation that needs modification
    for index, row in affected_allocations.iterrows():
        step_start = time.time()

        line = row["line"]
        section = row["section"]
        code = row["code"]
        planned_qty = row["planned_qty"]
        factory = row["factory"]
        floor = row["floor"]
        op_sequence = row.get("op_seq", None)

        # Cache key for prioritization lookups
        cache_key = (code, line, factory, floor, emp_type)

        # 1. Check floaters first using cache
        if code not in floater_cache:
            available_employee = check_floaters_for_allocation(emp_fact_df, code=code)
            floater_cache[code] = available_employee
        else:
            available_employee = floater_cache[code]

        allocation_level = "floater"

        # 2. Use the optimized hierarchical search
        hierarchical_searches = [
            # (func_args, level_name)
            ({"line": line, "code": code, "emp_type": emp_type}, "same_line"),
            (
                {
                    "line": line,
                    "code": code,
                    "emp_type": "Secondary" if emp_type == "Primary" else "Primary",
                },
                "same_line_secondary",
            ),
            ({"factory": factory, "code": code, "emp_type": emp_type}, "same_factory"),
            (
                {
                    "factory": factory,
                    "code": code,
                    "emp_type": "Secondary" if emp_type == "Primary" else "Primary",
                },
                "same_factory_secondary",
            ),
            ({"floor": floor, "code": code, "emp_type": emp_type}, "same_floor"),
            (
                {
                    "floor": floor,
                    "code": code,
                    "emp_type": "Secondary" if emp_type == "Primary" else "Primary",
                },
                "same_floor_secondary",
            ),
            ({"code": code, "emp_type": emp_type}, "other_location"),
            (
                {
                    "code": code,
                    "emp_type": "Secondary" if emp_type == "Primary" else "Primary",
                },
                "other_location_secondary",
            ),
        ]

        # Try each search criteria until we find an employee
        for search_args, level in hierarchical_searches:
            if available_employee.empty:
                search_key = (code, tuple(sorted(search_args.items())))
                if search_key in code_employee_cache:
                    available_employee = code_employee_cache[search_key]
                else:
                    available_employee = get_prioritized_employees(
                        emp_fact_df, capacity_tracker, **search_args
                    )
                    code_employee_cache[search_key] = available_employee
                allocation_level = level

        # 3. Check op_seq and WIP (only if still no employee and we have WIP data)
        if available_employee.empty and op_sequence and wip_df is not None:
            # [WIP checking logic - left as is for now as it's complex and data-dependent]
            # This section has complex logic for finding an employee from the next operation
            # I'll leave it as is for now, as optimization would require more context
            pass

        # Find preferred employees for manual assignment (optimize this calculation)
        current_emp_id = row["allocated_emp_id"]
        preferred_employees = find_preferred_employees(
            emp_fact_df,
            capacity_tracker,
            code=code,
            line=line,
            factory=factory,
            floor=floor,
            current_emp_id=current_emp_id,
        )
        affected_allocations.at[index, "preferred_employees"] = preferred_employees

        # Process employee allocation if we found someone
        if not available_employee.empty:
            # Filter out already processed employees
            available_employee = available_employee[
                ~available_employee["employee_id"].isin(processed_employee_ids)
            ]

            if not available_employee.empty:
                # Get the first valid employee
                emp = available_employee.iloc[0]
                emp_id = emp["employee_id"]

                # Calculate safe allocation amount - use the correct column
                if "effective_remaining_capacity" in available_employee.columns:
                    effective_capacity = emp["effective_remaining_capacity"]
                else:
                    effective_capacity = (
                        capacity_tracker.get_effective_remaining_capacity(emp_id, code)
                    )

                allocation = min(planned_qty, effective_capacity)

                if allocation > 0:
                    # Update capacity tracker
                    capacity_tracker.allocate_capacity(emp_id, allocation)

                    # Add to processed list
                    processed_employee_ids.add(emp_id)

                    # Track reallocation
                    reallocation = {
                        "original_emp": row["allocated_emp_id"],
                        "new_emp": emp_id,
                        "line": line,
                        "section": section,
                        "allocation_level": allocation_level,
                        "planned_qty": planned_qty,
                        "allocated_qty": allocation,
                        "remaining_capacity": effective_capacity - allocation,
                        "operation_sequence": op_sequence,
                    }
                    reallocation_tracking.append(reallocation)

                    # Update allocation details (all at once using .loc)
                    affected_allocations.loc[index, "allocated_emp_id"] = emp_id
                    # affected_allocations.loc[index, 'allocated_emp_name'] = emp['employee_name'] # Commented 'allocated_emp_name' as fetching from emp_fact while inserting
                    affected_allocations.loc[index, "allocated_capacity"] = allocation
                    affected_allocations.loc[index, "allocated_frm_line"] = emp["line"]
                    affected_allocations.loc[index, "allocated_frm_factory"] = emp[
                        "factory"
                    ]
                    affected_allocations.loc[index, "allocated_frm_floor"] = emp[
                        "floor"
                    ]
                    affected_allocations.loc[index, "skill_type"] = emp["type"]
                    affected_allocations.loc[index, "machine"] = emp["machine"]
                    affected_allocations.loc[index, "designation"] = emp["designation"]
                    affected_allocations.loc[index, "target_100"] = planned_qty
                    affected_allocations.loc[index, "target_90"] = planned_qty * 0.9
                    affected_allocations.loc[index, "shortage_flag"] = (
                        f"Reallocated ({allocation_level})"
                    )
                    affected_allocations.loc[index, "reallocation_level"] = (
                        allocation_level
                    )
                    affected_allocations.loc[index, "re_allocated_employee"] = emp[
                        "employee_name"
                    ]
                else:
                    affected_allocations.loc[index, "shortage_flag"] = (
                        "Reallocation Failed - Insufficient Capacity"
                    )
            else:
                affected_allocations.loc[index, "shortage_flag"] = (
                    "Reallocation Failed - Already Allocated"
                )
        else:
            affected_allocations.loc[index, "shortage_flag"] = (
                "Reallocation Failed - No Matching Employee"
            )

        # Print timing info for each allocation
        if index % 10 == 0:  # Print every 10 allocations
            logger.info(
                f"Processed allocation {index} in {time.time() - step_start:.2f} seconds"
            )

    # Verify no over-allocation occurred
    over_allocated = emp_fact_df[emp_fact_df["remaining_capacity"] < 0]
    if not over_allocated.empty:
        logger.info("WARNING: Over-allocation detected during reallocation process!")
        logger.info(
            over_allocated[["employee_id", "employee_name", "remaining_capacity"]]
        )
        # Fix any negative capacities by setting to zero
        emp_fact_df.loc[emp_fact_df["remaining_capacity"] < 0, "remaining_capacity"] = 0

    logger.info(f"Total reallocation time: {time.time() - start_time:.2f} seconds")
    return affected_allocations, reallocation_tracking


def balance_by_operation_sequence_enhanced_old(
    planned_manning_df, emp_fact_df, wip_df=None
):
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

    # Ensure op_seq column exists
    if "op_seq" not in balanced_manning.columns:
        logger.info("Warning: op_seq column not found. Creating dummy sequence.")
        # Create a temporary sequence based on operation order
        balanced_manning["op_seq"] = (
            balanced_manning.groupby(["line", "section"]).cumcount() + 1
        )

    # Sort by line and op_seq for sequential processing
    balanced_manning = balanced_manning.sort_values(by=["line", "op_seq"])

    # Add columns for WIP analysis
    balanced_manning["wip_quantity"] = 0
    balanced_manning["wip_ratio"] = 0
    balanced_manning["optimal_wip_buffer"] = 0
    balanced_manning["excess_capacity"] = 0
    balanced_manning["resource_status"] = None

    # Join WIP data if available
    if wip_df is not None:
        # Define columns to join on
        join_columns = [
            col
            for col in ["line", "section", "operation", "code"]
            if col in balanced_manning.columns and col in wip_df.columns
        ]

        if join_columns:
            # Find WIP quantity column
            # wip_qty_col = next((col for col in wip_df.columns if 'WIP' in col.upper() and 'QTY' in col.upper()), None)
            wip_qty_col = "wip_qty"

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
                    how="left",
                )

                # Update WIP quantities
                merged_df[wip_qty_col] = merged_df[wip_qty_col].fillna(0)
                balanced_manning["wip_quantity"] = merged_df[wip_qty_col]

    # 1. Calculate capacity metrics for each operation
    for idx, row in balanced_manning.iterrows():
        if pd.notna(row["allocated_capacity"]) and row["allocated_capacity"] > 0:
            # Calculate hours needed based on planned quantity and allocated capacity
            planned_qty = row["planned_qty"]
            allocated_capacity = row["allocated_capacity"]

            # Calculate estimated hours to complete
            hours_needed = (
                planned_qty / allocated_capacity
                if allocated_capacity > 0
                else float("inf")
            )
            balanced_manning.at[idx, "estimated_completed_time"] = min(hours_needed, 8)

            # Calculate standard expected hourly output
            hourly_output = allocated_capacity / 8  # Assuming 8-hour workday

            # Calculate optimal WIP buffer (2 hours of work for next operation)
            balanced_manning.at[idx, "optimal_wip_buffer"] = hourly_output * 2

            # Determine if operation has excess capacity
            if hours_needed < 6 and row["wip_quantity"] > hourly_output * 1:
                # Operation will finish early and has at least 1 hour of WIP buffer
                excess_hours = 6 - hours_needed
                balanced_manning.at[idx, "excess_capacity"] = excess_hours * (
                    allocated_capacity / 8
                )
                balanced_manning.at[idx, "resource_status"] = "EXCESS"
            elif hours_needed > 8:
                # Operation is understaffed
                balanced_manning.at[idx, "resource_status"] = "SHORTAGE"
            else:
                # Operation is balanced
                balanced_manning.at[idx, "resource_status"] = "BALANCED"

    # 2. Calculate WIP ratios between sequential operations
    for line, group in balanced_manning.groupby("line"):
        # Sort by operation sequence
        line_ops = group.sort_values("op_seq")

        # Calculate WIP ratios between consecutive operations
        for i in range(len(line_ops) - 1):
            current_op_idx = line_ops.iloc[i].name
            next_op_idx = line_ops.iloc[i + 1].name

            current_wip = balanced_manning.at[current_op_idx, "wip_quantity"]
            optimal_buffer = balanced_manning.at[next_op_idx, "optimal_wip_buffer"]

            if optimal_buffer > 0:
                # Calculate ratio of current WIP to optimal buffer
                wip_ratio = current_wip / optimal_buffer
                balanced_manning.at[next_op_idx, "wip_ratio"] = wip_ratio

                # Categorize WIP status
                if wip_ratio > 1.5:
                    # More than enough WIP for next operation
                    balanced_manning.at[current_op_idx, "wip_status"] = "EXCESS"
                elif wip_ratio < 0.5:
                    # Not enough WIP for next operation
                    balanced_manning.at[current_op_idx, "wip_status"] = "SHORTAGE"
                else:
                    # Just right
                    balanced_manning.at[current_op_idx, "wip_status"] = "OPTIMAL"

    # 3. Find operations that have excess capacity and could donate resources
    potential_donors = balanced_manning[
        (balanced_manning["resource_status"] == "EXCESS")
        & (balanced_manning["excess_capacity"] > 0)
    ]

    # 4. Find operations that need more resources to prevent halts
    critical_recipients = balanced_manning[
        (balanced_manning["resource_status"] == "SHORTAGE")
        & (balanced_manning["wip_ratio"] < 0.5)  # Low incoming WIP ratio
    ]

    # 5. Track reallocation actions
    reallocation_actions = []

    # 6. First handle critical shortages that could halt production
    for idx, recipient in critical_recipients.iterrows():
        recipient_line = recipient["line"]
        recipient_code = recipient["code"]
        recipient_op = recipient["op_seq"]

        # Look for donors in the same line first
        same_line_donors = potential_donors[
            (potential_donors["line"] == recipient_line)
            & (potential_donors["op_seq"] < recipient_op)  # Earlier operations first
        ]

        if not same_line_donors.empty:
            # Found potential donor in same line
            donor = same_line_donors.iloc[0]
            donor_idx = donor.name

            # Check if employees can be transferred
            donor_emp_id = donor["allocated_emp_id"]
            if pd.isna(donor_emp_id):
                continue

            # Verify employee has the required skill
            emp_has_skill = False
            matching_skills = emp_fact_df[
                (emp_fact_df["employee_id"] == donor_emp_id)
                & (emp_fact_df["code"] == recipient_code)
            ]

            if not matching_skills.empty:
                emp_has_skill = True

            if emp_has_skill:
                # Calculate capacity to transfer (up to 50% of excess)
                transfer_capacity = min(
                    donor["excess_capacity"] * 0.5,
                    recipient["planned_qty"] / 4,  # At most enough for 2 hours of work
                )

                if transfer_capacity > 0:
                    # Record reallocation action
                    reallocation_actions.append(
                        {
                            "from_line": donor["line"],
                            "from_op": donor["op_seq"],
                            "to_line": recipient_line,
                            "to_op": recipient_op,
                            "emp_id": donor_emp_id,
                            "capacity": transfer_capacity,
                            "reason": "critical_shortage_prevention",
                        }
                    )

                    # Update donor's excess capacity
                    balanced_manning.at[donor_idx, "excess_capacity"] -= (
                        transfer_capacity
                    )

                    # If donor no longer has excess, remove from potential donors
                    if balanced_manning.at[donor_idx, "excess_capacity"] <= 0:
                        balanced_manning.at[donor_idx, "resource_status"] = "BALANCED"
                        potential_donors = potential_donors[
                            potential_donors.index != donor_idx
                        ]

                    # Update recipient's allocation
                    balanced_manning.at[idx, "allocated_emp_id"] = donor_emp_id
                    balanced_manning.at[idx, "allocated_capacity"] = transfer_capacity
                    balanced_manning.at[idx, "resource_status"] = "BALANCED"
                    balanced_manning.at[idx, "reallocation_reason"] = "WIP_optimization"
                    balanced_manning.at[idx, "reallocation_level"] = (
                        "critical_shortage_prevention"
                    )

        else:
            # Look for donors in other lines (cross-line balancing)
            other_line_donors = potential_donors[
                potential_donors["line"] != recipient_line
            ]

            if not other_line_donors.empty:
                # Similar logic for cross-line balancing...
                # This would be a more extensive version of the same allocation logic
                # with additional checks for movement between lines
                pass

    # 7. Next, balance WIP across operations to optimize flow
    # After handling critical shortages, optimize WIP buffers
    for line, group in balanced_manning.groupby("line"):
        # Process each line separately
        line_ops = group.sort_values("op_seq")

        for i in range(len(line_ops) - 1):
            current_op_idx = line_ops.iloc[i].name
            next_op_idx = line_ops.iloc[i + 1].name

            current_status = balanced_manning.at[current_op_idx, "resource_status"]
            next_status = balanced_manning.at[next_op_idx, "resource_status"]

            # If current operation has excess and next has shortage, balance them
            if (
                current_status == "EXCESS"
                and next_status == "SHORTAGE"
                and balanced_manning.at[current_op_idx, "excess_capacity"] > 0
            ):
                # Similar allocation logic as above, but for WIP optimization
                # between consecutive operations
                pass

    # 8. Apply all reallocations to the final manning sheet
    # (This would update the balanced_manning dataframe based on reallocation_actions)

    # Return the balanced manning sheet
    return balanced_manning


def analyze_mass_absenteeism_old(attendance_df, allocation_date, emp_details):
    """
    Optimized version to identify patterns of mass absenteeism
    """
    # Filter attendance for the allocation date - use vectorized operations
    mask = attendance_df["attendance_date"] == allocation_date
    daily_attendance = attendance_df[mask]

    # Skip if no attendance data
    if daily_attendance.empty:
        return {
            "mass_absenteeism_found": False,
            "latest_absence_rate": 0.0,
            "trend_increasing": False,
            "trend_decreasing": False,
            "daily_absence_rates": {},
        }

    # Process latest status using pandas groupby operation
    if "last_updated" in daily_attendance.columns:
        daily_attendance["last_updated"] = pd.to_datetime(
            daily_attendance["last_updated"],
            format="%Y-%m-%d %H:%M:%S",
            errors="coerce",
        )
        # Optimize groupby with sorting instead of using sort_values + groupby
        daily_attendance = daily_attendance.sort_values("last_updated")
        latest_attendance = daily_attendance.groupby(
            "employee_id", as_index=False
        ).last()
    else:
        latest_attendance = daily_attendance.groupby(
            "employee_id", as_index=False
        ).first()

    # Vectorized calculations for absence rates
    status_column = "status" if "status" in latest_attendance.columns else "status"
    latest_absence_rate = (latest_attendance[status_column] == "A").mean() * 100

    # Calculate historical absence rates
    end_date = allocation_date
    start_date = end_date - pd.Timedelta(days=7)

    # Create date range once
    date_range = pd.date_range(start=start_date, end=end_date, freq="D")
    daily_absence_rates = {}

    # Vectorized trend analysis
    trend_data = []

    # Filter all attendance data for the date range at once
    date_range_mask = (attendance_df["attendance_date"] >= start_date) & (
        attendance_df["attendance_date"] <= end_date
    )
    date_range_attendance = attendance_df[date_range_mask]

    # Pre-sort by 'last_updated' if it exists
    if "last_updated" in date_range_attendance.columns:
        date_range_attendance["last_updated"] = pd.to_datetime(
            date_range_attendance["last_updated"], errors="coerce"
        )
        date_range_attendance = date_range_attendance.sort_values("last_updated")

    for date in date_range:
        # Use the pre-filtered data
        date_mask = date_range_attendance["attendance_date"] == date
        date_attendance = date_range_attendance[date_mask]

        if not date_attendance.empty:
            # Get latest status using groupby
            date_latest = date_attendance.groupby("employee_id", as_index=False).last()

            # Calculate absence rate
            stat_col = "Status" if "Status" in date_latest.columns else "status"
            absence_rate = (date_latest[stat_col] == "A").mean() * 100

            daily_absence_rates[date.strftime("%Y-%m-%d")] = absence_rate
            trend_data.append(absence_rate)

    # Simple trend analysis
    trend_increasing = False
    trend_decreasing = False

    if len(trend_data) >= 3:
        recent_avg = sum(trend_data[-2:]) / 2 if trend_data else 0
        earlier_avg = sum(trend_data[:2]) / 2 if trend_data else 0
        trend_increasing = recent_avg > earlier_avg * 1.1  # 10% increase
        trend_decreasing = recent_avg < earlier_avg * 0.9  # 10% decrease

    latest_attendance = latest_attendance.drop(
        columns=["line", "factory", "floor", "section"], errors="ignore"
    )

    # Try to load employee details and calculate departmental absence rates
    try:
        # Merge with latest attendance - use efficient merge
        merged_attendance = pd.merge(
            latest_attendance,
            emp_details[["employee_id", "line", "factory", "floor", "section"]],
            left_on="employee_id",
            right_on="employee_id",
            how="left",
        )

        # Vectorized calculation of absence percentages by group
        status_col = "status" if "status" in merged_attendance.columns else "status"

        by_line = (
            merged_attendance.groupby("line")[status_col]
            .apply(lambda x: (x == "A").mean() * 100)
            .sort_values(ascending=False)
        )

        by_section = (
            merged_attendance.groupby("section")[status_col]
            .apply(lambda x: (x == "A").mean() * 100)
            .sort_values(ascending=False)
        )

        by_floor = (
            merged_attendance.groupby("floor")[status_col]
            .apply(lambda x: (x == "A").mean() * 100)
            .sort_values(ascending=False)
        )

        # Vectorized filtering for high absence areas
        high_absence_lines = by_line[by_line > 15].to_dict()
        high_absence_sections = by_section[by_section > 15].to_dict()
        high_absence_floors = by_floor[by_floor > 15].to_dict()

        mass_absenteeism_found = bool(
            high_absence_lines or high_absence_sections or high_absence_floors
        )

        return {
            "mass_absenteeism_found": mass_absenteeism_found,
            "high_absence_lines": high_absence_lines,
            "high_absence_sections": high_absence_sections,
            "high_absence_floors": high_absence_floors,
            "latest_absence_rate": latest_absence_rate,
            "trend_increasing": trend_increasing,
            "trend_decreasing": trend_decreasing,
            "daily_absence_rates": daily_absence_rates,
        }

    except Exception as e:
        logger.info(f"Error analyzing mass absenteeism: {e}")
        return {
            "mass_absenteeism_found": False,
            "error": str(e),
            "latest_absence_rate": latest_absence_rate,
            "trend_increasing": trend_increasing,
            "trend_decreasing": trend_decreasing,
            "daily_absence_rates": daily_absence_rates,
        }
