import logging

logger = logging.getLogger(__name__)

import ast
import os
from datetime import datetime, timedelta

import pandas as pd
import pytz
from django.utils import timezone

from .models import DDayData, ManningSheetData

DEFAULT_WORK_START_TIME = "08:50:00"
DEFAULT_WORK_END_TIME = "17:30:00"
END_OF_DAY_THRESHOLD = "17:30:00"


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
    if code:  # Ensure employee only works on assigned code
        query &= emp_df["code"] == code

    if emp_type:
        query &= (
            emp_df["type"] == emp_type
        )  # This ensures Primary and Secondary are handled separately

    return emp_df[query].sort_values(
        by=["type", "remaining_capacity"], ascending=[True, False]
    )


# ===================version 2=======================


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
                    f"{row['employee_name']}- {row['employee_id']} [Line: {row['line']}, Capacity: {row['remaining_capacity']}]"
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
                    f"{row['employee_name']}- {row['employee_id']} [Line: {row['line']}, Capacity: {row['remaining_capacity']}]"
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
                    f"{row['employee_name']}- {row['employee_id']} [Line: {row['line']}, Capacity: {row['remaining_capacity']}]"
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
                f"{row['employee_name']}- {row['employee_id']} [Line: {row['line']}, Capacity: {row['remaining_capacity']}]"
                for _, row in anywhere_employees.iterrows()
            ]

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


def add_wip_backlog(planned_manning_df, wip_df):
    """
    Add WIP quantities to planned quantities if they match on key combination fields

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
        updated_manning[col] = updated_manning[col].astype(str)

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


def load_planned_allocation(allocation_date, wip_df=None):
    """
    Load the planned allocation from the 0-day plan only,
    optionally adding WIP backlog quantities

    Parameters:
    allocation_date (datetime): The date for which to load allocation
    wip_df (DataFrame, optional): WIP dataframe containing backlog quantities

    Returns:
    tuple: (Manning dataframe, source description)
    """
    today = datetime.today().date()
    # Load D-day plan
    manning_0_df = ManningSheetData.objects.filter(planned_dates=today).values()
    manning_0_df = pd.DataFrame(list(manning_0_df))
    if manning_0_df.empty:
        raise ValueError(
            f"No manning sheet data found for allocation date: {allocation_date}"
        )

    manning_0_df.drop(columns=["raw_oc_no", "raw_style", "raw_color"], inplace=True)
    manning_0_df["planned_dates"] = pd.to_datetime(manning_0_df["planned_dates"])

    # Filter for the specific date
    plan_0 = manning_0_df[manning_0_df["planned_dates"] == allocation_date]

    if not plan_0.empty:
        # Add WIP backlog if WIP dataframe is provided
        if wip_df is not None:
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
            "emp_name": row["allocated_emp_name"],
            "line": row["allocated_frm_line"],
            "capacity": row["allocated_capacity"],
            "shortage_flag": row["shortage_flag"] if "shortage_flag" in row else None,
        },
        axis=1,
    ).astype(str)

    return affected_allocations


def reallocate_work(affected_allocations, emp_fact_df, allocation_date, emp_type=None):
    """
    Reallocate work following original prioritization logic with strict capacity checks
    """
    reallocation_tracking = []
    affected_allocations["reallocation_level"] = None
    affected_allocations["preferred_employees"] = None
    affected_allocations["re_allocated_employee"] = None

    # Keep track of processed employees to avoid over-allocation
    processed_employee_ids = set()

    for index, row in affected_allocations.iterrows():
        line = row["line"]
        section = row["section"]
        code = row["code"]
        planned_qty = row["planned_qty"]
        factory = row["factory"]
        floor = row["floor"]

        # Follow prioritization steps
        available_employee = get_prioritized_employees(
            emp_fact_df, line=line, code=code, emp_type=emp_type
        )
        allocation_level = "same_line"

        if available_employee.empty:
            available_employee = get_prioritized_employees(
                emp_fact_df, line=line, code=code, emp_type="Secondary"
            )

        if available_employee.empty:
            available_employee = get_prioritized_employees(
                emp_fact_df, factory=factory, code=code, emp_type=emp_type
            )
            allocation_level = "same_factory"

        if available_employee.empty:
            available_employee = get_prioritized_employees(
                emp_fact_df, floor=floor, code=code, emp_type=emp_type
            )
            allocation_level = "same_floor"

        if available_employee.empty:
            available_employee = get_prioritized_employees(
                emp_fact_df, code=code, emp_type=emp_type
            )
            allocation_level = "other_location"

        # Find and store preferred employees for manual assignment using the updated function
        current_emp_id = row["allocated_emp_id"]  # The currently allocated employee
        preferred_employees = find_preferred_employees(
            emp_fact_df,
            code=code,
            line=line,
            factory=factory,
            floor=floor,
            current_emp_id=current_emp_id,
        )
        affected_allocations.at[index, "preferred_employees"] = preferred_employees

        if not available_employee.empty:
            # Find the first employee with sufficient capacity
            employee_allocated = False

            for i in range(len(available_employee)):
                emp = available_employee.iloc[i]
                emp_id = emp["employee_id"]

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
                affected_allocations.at[index, "shortage_flag"] = "Reallocated"
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


def perform_dday_allocation(allocation_date, attendance_df, emp_fact_df, wip_df=None):
    """
    Main function to perform D-day allocation as a single manual run
    Handles:
    1. Absent employees
    2. Early departures
    3. Partial shortages
    4. Unresolved shortages
    5. WIP backlog inclusion (if wip_df is provided)

    Parameters:
    allocation_date (datetime): The date for which to perform allocation
    attendance_df (DataFrame): Attendance data
    emp_fact_df (DataFrame): Employee fact table with capacity information
    wip_df (DataFrame, optional): WIP data containing backlog quantities

    Returns:
    tuple: (Final manning DataFrame, statistics dict, reallocation tracking list)
    """
    # Reset daily capacity for this run
    emp_fact_df["remaining_capacity"] = emp_fact_df["average_capacity"]
    run_timestamp = pd.Timestamp.now()

    # Load D-day plan and include WIP backlog if provided
    planned_manning, plan_source = load_planned_allocation(allocation_date, wip_df)
    working_manning = planned_manning.copy()

    # Ensure all tracking columns exist
    tracking_columns = [
        "run_history",
        "current_run",
        "original_emp",
        "original_emp_name",  # New column for original employee name
        "new_emp",
        "reallocation_level",
        "re_allocated_employee",
        "preferred_employees",
        "reallocation_reason",
        "average_capacity_per_hour",  # New column for hourly capacity
        "attendance_status",  # New column for attendance status
    ]
    for col in tracking_columns:
        if col not in working_manning.columns:
            working_manning[col] = None

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
                daily_attendance["last_updated"], errors="coerce"
            )
            latest_attendance = (
                daily_attendance.sort_values("last_updated")
                .groupby("employee_id")
                .last()
            )
        else:
            latest_attendance = daily_attendance.groupby("employee_id").first()

        # Identify employees who are absent OR have early departure (even if marked Present)
        # Consider both cases as unavailable for allocation
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

    # Handle capacity for absent and early departure employees
    emp_fact_df.loc[
        emp_fact_df["employee_id"].isin(current_absent), "remaining_capacity"
    ] = 0

    # Find allocations affected by new absences AND shortage flags
    affected_allocations = identify_affected_allocations(
        working_manning, current_absent, handle_shortages=True
    )

    # Perform reallocation
    reallocated_manning, reallocation_tracking = reallocate_work(
        affected_allocations, emp_fact_df, allocation_date
    )

    # Update manning sheet with full details
    final_manning = working_manning.copy()

    # First, initialize all preferred_employees to None/empty
    final_manning["preferred_employees"] = None

    # Add preferred employees column ONLY for rows with shortages, absences, or reallocations
    for idx in final_manning.index:
        # For rows that were already reallocated, keep the preferred employees that were assigned
        if idx in reallocated_manning.index:
            # This preferred employees data is already set during reallocation
            continue

        # For non-reallocated rows, only populate if there's a shortage or absence
        has_shortage = final_manning.loc[idx, "shortage_flag"] in [
            "Partially Shortage",
            "Shortage Unresolved",
        ]
        is_absent = final_manning.loc[idx, "allocated_emp_id"] in current_absent

        if has_shortage or is_absent:
            line = final_manning.loc[idx, "line"]
            code = final_manning.loc[idx, "code"]
            factory = final_manning.loc[idx, "factory"]
            floor = final_manning.loc[idx, "floor"]
            current_emp_id = final_manning.loc[idx, "allocated_emp_id"]

            preferred_employees = find_preferred_employees(
                emp_fact_df,
                code=code,
                line=line,
                factory=factory,
                floor=floor,
                current_emp_id=current_emp_id,
            )
            final_manning.loc[idx, "preferred_employees"] = preferred_employees

    # Update with reallocated data, preserving all columns
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

    # Handle capacity for absent employees (set to zero)
    emp_fact_df.loc[
        emp_fact_df["employee_id"].isin(current_absent), "remaining_capacity"
    ] = 0

    emp_fact_df["average_capacity/HR"] = emp_fact_df["average_capacity"] / 9
    # Add average_capacity_per_hour from emp_fact_df
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
        ):  # If original_emp is empty or NaN, use allocated_emp_id
            emp_id = final_manning.loc[idx, "allocated_emp_id"]

        # Add original employee name
        if emp_id in emp_name_map:
            final_manning.loc[idx, "original_emp_name"] = emp_name_map[emp_id]
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
        "status": "completed",
    }

    # Update run history
    for idx in final_manning.index:
        history = safe_eval_history(final_manning.at[idx, "run_history"])

        if idx in reallocated_manning.index:
            reason = final_manning.at[idx, "reallocation_reason"]
            history.append(
                {
                    "run_timestamp": run_timestamp,
                    "previous_emp": working_manning.at[idx, "allocated_emp_id"],
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
        "successful_reallocations": len(
            reallocated_manning[reallocated_manning["shortage_flag"] == "Reallocated"]
        ),
        "failed_reallocations": len(
            reallocated_manning[reallocated_manning["shortage_flag"] != "Reallocated"]
        ),  # Changed to catch all failure types
        "reallocation_by_level": pd.Series(reallocated_manning["reallocation_level"])
        .value_counts()
        .to_dict(),
        "reallocation_by_reason": pd.Series(
            final_manning.loc[reallocated_manning.index, "reallocation_reason"]
        )
        .value_counts()
        .to_dict(),
    }

    # Check for any over-utilization
    over_allocated = emp_fact_df[emp_fact_df["remaining_capacity"] < 0]
    if not over_allocated.empty:
        logger.info(
            f"WARNING: {len(over_allocated)} employees have been over-allocated!"
        )
        # print(over_allocated[["employee_id", "employee_name", "remaining_capacity"]])
        stats["over_allocated_employees"] = len(over_allocated)
    else:
        stats["over_allocated_employees"] = 0

    return final_manning, stats, reallocation_tracking


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


def run_intraday_allocation(allocation_date, attendance_df, emp_fact_df, run_times):
    """
    Perform multiple allocation runs throughout the day

    Parameters:
    run_times: List of timestamps for each run
    """
    daily_results = []
    previous_manning = None

    for run_time in sorted(run_times):
        logger.info(f"\nPerforming allocation run at {run_time}")

        # Perform allocation for this run
        manning, stats, tracking = perform_dday_allocation(
            allocation_date, attendance_df, emp_fact_df, run_time, previous_manning
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

    return daily_results


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


def adjust_planned_quantities_with_wip(manning_df, wip_df):
    """
    Adjust planned quantities based on WIP quantities for intraday
    For intraday before 5:30 PM, WIP quantities are SUBTRACTED from planned quantities
    Handles multiple matching operations by proportionally distributing WIP quantities.

    Parameters:
    manning_df (DataFrame): Manning dataframe to adjust
    wip_df (DataFrame): WIP dataframe containing progress quantities

    Returns:
    DataFrame: Manning dataframe with updated quantities
    """
    # Create a copy to avoid modifying the original
    updated_manning = manning_df.copy()

    # Define the key columns that identify a unique operation
    key_columns = [
        "OC NO",
        "ORDER NO",
        "BUYER",
        "STYLE",
        "LINE",
        "COLOR",
        "SECTION",
        "OPERATION",
        "CODE",
    ]

    # Make sure all necessary columns exist in both dataframes
    existing_key_columns = [
        col
        for col in key_columns
        if col in updated_manning.columns and col in wip_df.columns
    ]

    # If there are no common columns to join on, return the original dataframe
    if not existing_key_columns:
        logger.info(
            "Warning: No common columns found between manning and WIP dataframes"
        )
        return updated_manning

    # Track original planned quantities if not already tracked
    if "ORIGINAL_PLANNED_QTY" not in updated_manning.columns:
        updated_manning["ORIGINAL_PLANNED_QTY"] = updated_manning["PLANNED QTY"]

    # Convert key columns to a consistent type (string in this case)
    for col in existing_key_columns:
        wip_df[col] = wip_df[col].astype(str)
        updated_manning[col] = updated_manning[col].astype(str)

    # Group WIP data by key columns to identify cases where multiple operations may match
    wip_grouped = wip_df.groupby(existing_key_columns)["WIP  QTY"].sum().reset_index()

    # For each WIP group, find matching operations in the manning dataframe
    adjusted_count = 0
    multi_match_count = 0

    for _, wip_row in wip_grouped.iterrows():
        query_conditions = []
        for col in existing_key_columns:
            # Use backticks for column names with spaces/special characters
            escaped_col = f"`{col}`"  # Escape column names with backticks
            query_conditions.append(f"{escaped_col} == '{wip_row[col]}'")

        query_str = " & ".join(query_conditions)
        matching_operations = updated_manning.query(query_str)

        if matching_operations.empty:
            continue

        wip_qty = wip_row["WIP  QTY"]
        if wip_qty <= 0:
            continue

        # If multiple operations match, distribute WIP proportionally based on planned quantities
        if len(matching_operations) > 1:
            multi_match_count += 1
            logger.info(
                f"Found {len(matching_operations)} matching operations for: {wip_row[existing_key_columns].to_dict()}"
            )

            # Calculate total planned quantity across all matching operations
            total_planned_qty = matching_operations["PLANNED QTY"].sum()

            if total_planned_qty > 0:
                # Distribute WIP proportionally
                for idx in matching_operations.index:
                    operation_planned_qty = updated_manning.loc[idx, "PLANNED QTY"]
                    proportion = operation_planned_qty / total_planned_qty
                    operation_wip_share = wip_qty * proportion

                    # Calculate new planned quantity (subtract WIP from planned)
                    new_planned_qty = max(
                        0, operation_planned_qty - operation_wip_share
                    )

                    # Update the planned quantity
                    updated_manning.loc[idx, "PLANNED QTY"] = new_planned_qty

                    # Also update allocated capacity and target capacities based on new planned quantities
                    if "TARGET@100%" in updated_manning.columns and pd.notna(
                        updated_manning.loc[idx, "ALLOCATED CAPACITY"]
                    ):
                        # Update the targets based on the new planned quantity
                        updated_manning.loc[idx, "TARGET@100%"] = new_planned_qty
                        updated_manning.loc[idx, "TARGET@90%"] = new_planned_qty * 0.9

                    adjusted_count += 1
                    logger.info(
                        f"  - Operation {idx}: Planned {operation_planned_qty} -> {new_planned_qty}, WIP share: {operation_wip_share:.2f} ({proportion * 100:.1f}%)"
                    )
            else:
                logger.info(
                    "  - Warning: Total planned quantity is zero for these operations, cannot distribute WIP"
                )
        else:
            # Single match case - simply subtract WIP from planned
            idx = matching_operations.index[0]
            operation_planned_qty = updated_manning.loc[idx, "PLANNED QTY"]

            # Calculate new planned quantity (subtract WIP from planned)
            new_planned_qty = max(0, operation_planned_qty - wip_qty)

            # Update the planned quantity
            updated_manning.loc[idx, "PLANNED QTY"] = new_planned_qty

            # Also update allocated capacity and target capacities based on new planned quantities
            if "TARGET@100%" in updated_manning.columns and pd.notna(
                updated_manning.loc[idx, "ALLOCATED CAPACITY"]
            ):
                # Update the targets based on the new planned quantity
                updated_manning.loc[idx, "TARGET@100%"] = new_planned_qty
                updated_manning.loc[idx, "TARGET@90%"] = new_planned_qty * 0.9

            adjusted_count += 1

    logger.info(
        f"Adjusted {adjusted_count} operations by subtracting WIP quantities from planned quantities"
    )
    if multi_match_count > 0:
        logger.info(
            f"Found {multi_match_count} cases where WIP quantities were distributed across multiple matching operations"
        )

    return updated_manning


def perform_end_of_day_allocation(allocation_date, wip_df=None):
    logger.info("Inside perform end of day allocation")
    """
    Special end-of-day allocation (after 5:30 PM)
    Loads the daily capacity manning sheet and adds WIP quantities for next day

    Parameters:
    allocation_date (datetime): The current allocation date
    wip_df (DataFrame, optional): WIP dataframe containing backlog quantities

    Returns:
    tuple: (Final manning DataFrame, statistics dict, empty reallocation tracking list)
    """
    # Load the daily capacity manning sheet
    try:
        previous_manning_db = DDayData.objects.all().values()
        daily_manning = pd.DataFrame(list(previous_manning_db))
        logger.info(
            f"Loaded daily capacity manning sheet with {len(daily_manning)} records"
        )
    except Exception as e:
        logger.info(f"Error loading daily capacity manning sheet: {e}")
        raise ValueError(
            "Cannot perform end-of-day allocation without daily capacity manning sheet"
        )

    # If no WIP data, return the sheet as-is
    if wip_df is None:
        logger.info("No WIP data provided for end-of-day allocation")
        stats = {
            "run_timestamp": get_ist_time(),
            "allocation_date": allocation_date,
            "run_type": "end_of_day",
            "wip_data_available": False,
            "message": "No WIP data available for end-of-day processing",
        }
        return daily_manning, stats, []

    # Add WIP quantities (using the add_wip_backlog function which ADDS WIP to planned)
    updated_manning = add_wip_backlog(daily_manning, wip_df)

    # Generate statistics
    stats = {
        "run_timestamp": get_ist_time(),
        "allocation_date": allocation_date,
        "run_type": "end_of_day",
        "wip_data_available": True,
        "total_operations": len(updated_manning),
        "operations_with_backlog": len(
            updated_manning[updated_manning["backlog_flag"] == "Backlog Included"]
        ),
    }

    logger.info("End-of-day manning sheet generated!")

    return updated_manning, stats, []


def perform_intraday_allocation(
    allocation_date,
    attendance_df,
    emp_fact_df,
    previous_manning,
    wip_df=None,
    current_time=None,
):
    """
    Perform intraday allocation that accounts for:
    1. Previous allocations and elapsed time
    2. WIP quantities to adjust planned quantities
    3. Different logic for before/after 5:30 PM

    Parameters:
    allocation_date (datetime): The date for which to perform allocation
    attendance_df (DataFrame): Updated attendance data
    emp_fact_df (DataFrame): Employee fact table with capacity information
    previous_manning (DataFrame): Manning dataframe from the previous run (usually morning D-day run)
    wip_df (DataFrame, optional): WIP data for adjusting quantities
    current_time (datetime, optional): Current time when this intraday allocation is being performed

    Returns:
    tuple: (Final manning DataFrame, statistics dict, reallocation tracking list)
    """
    if current_time is None:
        current_time = get_ist_time()

    run_timestamp = get_ist_time()

    # Determine if this is an end-of-day run (after 5:30 PM)
    end_of_day_time = pd.Timestamp.combine(
        allocation_date.date(), pd.Timestamp(END_OF_DAY_THRESHOLD).time()
    ).tz_localize(pytz.timezone("Asia/Kolkata"))
    is_end_of_day = current_time >= end_of_day_time

    # If this is an end-of-day run, use special logic
    if is_end_of_day:
        return perform_end_of_day_allocation(allocation_date, wip_df)

    # Regular intraday allocation (before 5:30 PM)
    # Create a working copy of previous manning
    working_manning = previous_manning.copy()

    # Calculate time-adjusted capacity
    initial_run_time = pd.Timestamp.combine(
        allocation_date.date(), pd.Timestamp(DEFAULT_WORK_START_TIME).time()
    ).tz_localize(pytz.timezone("Asia/Kolkata"))
    work_day_end_time = pd.Timestamp.combine(
        allocation_date.date(), pd.Timestamp(DEFAULT_WORK_END_TIME).time()
    ).tz_localize(pytz.timezone("Asia/Kolkata"))

    total_work_day_seconds = (work_day_end_time - initial_run_time).total_seconds()
    elapsed_seconds = (current_time - initial_run_time).total_seconds()
    remaining_seconds = max(0, total_work_day_seconds - elapsed_seconds)

    # Fraction of day completed and remaining
    fraction_elapsed = min(elapsed_seconds / total_work_day_seconds, 1.0)
    fraction_remaining = max(0, 1.0 - fraction_elapsed)

    # Prepare employee fact dataframe with adjusted capacities
    updated_emp_fact = emp_fact_df.copy()

    # Create mapping of employee IDs to their allocations from previous run
    employee_allocations = {}
    for _, row in previous_manning.iterrows():
        emp_id = row["allocated_emp_id"]
        if pd.notna(emp_id) and emp_id != "":
            if emp_id not in employee_allocations:
                employee_allocations[emp_id] = 0
            # Add allocated capacity for this employee
            if pd.notna(row["allocated_capacity"]):
                employee_allocations[emp_id] += row["allocated_capacity"]

    # Adjust capacity based on time elapsed and previous allocations
    for emp_id, allocated in employee_allocations.items():
        # Get the original average capacity for this employee
        emp_rows = updated_emp_fact[updated_emp_fact["employee_id"] == emp_id]
        if not emp_rows.empty:
            avg_capacity = emp_rows.iloc[0]["average_capacity"]

            # For intraday, we only use the remaining capacity for the day
            # This is original capacity * fraction of day remaining
            remaining_capacity = avg_capacity * fraction_remaining

            # Update the capacity
            updated_emp_fact.loc[
                updated_emp_fact["employee_id"] == emp_id, "remaining_capacity"
            ] = remaining_capacity

    # Process WIP adjustment to planned quantities
    if wip_df is not None:
        working_manning = adjust_planned_quantities_with_wip(working_manning, wip_df)

    # Filter attendance for the allocation date
    daily_attendance = attendance_df[
        attendance_df["attendance_date"] == allocation_date
    ]

    # Get latest status for each employee
    if not daily_attendance.empty:
        if "last_updated" in daily_attendance.columns:
            daily_attendance["last_updated"] = pd.to_datetime(
                daily_attendance["last_updated"], errors="coerce"
            )
            # Filter for updates since the initial run time
            daily_attendance = daily_attendance[
                daily_attendance["last_updated"] >= initial_run_time
            ]
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
        logger.info("Warning: No updated attendance data found since morning run!")

    # Handle capacity for newly absent and early departure employees
    updated_emp_fact.loc[
        updated_emp_fact["employee_id"].isin(current_absent), "remaining_capacity"
    ] = 0

    previously_absent = []
    if "attendance_status" in previous_manning.columns:
        # First, fill NaN values with empty string
        attendance_status = previous_manning["attendance_status"].fillna("")
        # Then convert to string to ensure .str methods work
        attendance_status = attendance_status.astype(str)
        # Now check which rows contain 'A'
        previously_absent = previous_manning[
            attendance_status.str.contains("A", regex=True)
        ]["allocated_emp_id"].tolist()

    newly_absent = [
        emp_id for emp_id in current_absent if emp_id not in previously_absent
    ]

    affected_allocations = identify_affected_allocations(
        working_manning, newly_absent, handle_shortages=True
    )

    # Perform reallocation - use the exact same logic as D-day for workforce reallocation
    reallocated_manning, reallocation_tracking = reallocate_work(
        affected_allocations, updated_emp_fact, allocation_date
    )

    # Update manning sheet with full details
    final_manning = working_manning.copy()

    # First, initialize all preferred_employees to None/empty if not already present
    if "preferred_employees" not in final_manning.columns:
        final_manning["preferred_employees"] = None

    # Update with reallocated data
    for idx in reallocated_manning.index:
        # Determine reallocation reason
        if working_manning.loc[idx, "allocated_emp_id"] in newly_absent:
            reallocation_reason = "intraday_attendance_change"
        elif working_manning.loc[idx, "shortage_flag"] in [
            "Partially Shortage",
            "Shortage Unresolved",
        ]:
            reallocation_reason = "shortage_resolution"
        else:
            reallocation_reason = "other"

        # Update preferred employees
        final_manning.loc[idx, "preferred_employees"] = reallocated_manning.loc[
            idx, "preferred_employees"
        ]

        # Preserve original employee information
        if "original_emp" not in final_manning.columns or pd.isna(
            final_manning.loc[idx, "original_emp"]
        ):
            # This is the first reallocation for this row
            final_manning.loc[idx, "original_emp"] = working_manning.loc[
                idx, "allocated_emp_id"
            ]
            if "original_emp_name" in final_manning.columns:
                final_manning.loc[idx, "original_emp_name"] = working_manning.loc[
                    idx, "ALLOCATED EMP NAME"
                ]

        if "new_emp" in final_manning.columns:
            final_manning.loc[idx, "new_emp"] = reallocated_manning.loc[
                idx, "allocated_emp_id"
            ]
        if "reallocation_level" in final_manning.columns:
            final_manning.loc[idx, "reallocation_level"] = reallocated_manning.loc[
                idx, "reallocation_level"
            ]
        if "re_allocated_employee" in final_manning.columns:
            final_manning.loc[idx, "re_allocated_employee"] = reallocated_manning.loc[
                idx, "re_allocated_employee"
            ]
        if "reallocation_reason" in final_manning.columns:
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

    # Update attendance status for all employees (including those not reallocated)
    if "attendance_status" in final_manning.columns:
        final_manning["attendance_status"] = final_manning["attendance_status"].astype(
            str
        )
        for idx in final_manning.index:
            emp_id = final_manning.loc[idx, "allocated_emp_id"]
            if emp_id in attendance_status_map:
                final_manning.loc[idx, "attendance_status"] = attendance_status_map[
                    emp_id
                ]

    # Record this run's changes
    run_record = {
        "timestamp": run_timestamp,
        "intraday_time": current_time,
        "time_fraction_elapsed": fraction_elapsed,
        "time_fraction_remaining": fraction_remaining,
        "newly_absent_count": len(newly_absent),
        "reallocations": len(reallocation_tracking),
        "status": "completed",
    }

    # Update run history
    if (
        "run_history" in final_manning.columns
        and "current_run" in final_manning.columns
    ):
        for idx in final_manning.index:
            history = safe_eval_history(final_manning.at[idx, "run_history"])

            if idx in reallocated_manning.index:
                reason = (
                    final_manning.at[idx, "reallocation_reason"]
                    if "reallocation_reason" in final_manning.columns
                    else "unknown"
                )
                history.append(
                    {
                        "run_timestamp": run_timestamp,
                        "run_type": "intraday",
                        "previous_emp": working_manning.at[idx, "allocated_emp_id"],
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
        "intraday_time": current_time,
        "time_fraction_elapsed": f"{fraction_elapsed:.2f}",
        "time_fraction_remaining": f"{fraction_remaining:.2f}",
        "total_allocations": len(final_manning),
        "newly_absent": len(newly_absent),
        "allocations_affected": len(affected_allocations),
        "successful_reallocations": len(
            reallocated_manning[reallocated_manning["shortage_flag"] == "Reallocated"]
        ),
        "failed_reallocations": len(
            reallocated_manning[reallocated_manning["shortage_flag"] != "Reallocated"]
        ),
        "reallocation_by_level": pd.Series(reallocated_manning["reallocation_level"])
        .value_counts()
        .to_dict()
        if "reallocation_level" in reallocated_manning.columns
        else {},
        "reallocation_by_reason": pd.Series(
            final_manning.loc[reallocated_manning.index, "reallocation_reason"]
        )
        .value_counts()
        .to_dict()
        if "reallocation_reason" in final_manning.columns
        else {},
        "plan_source": "Intraday",
        "total_absent": len(newly_absent),
        "total_shortages": len(shortage_rows),
    }

    # Check for any over-utilization
    over_allocated = updated_emp_fact[updated_emp_fact["remaining_capacity"] < 0]
    if not over_allocated.empty:
        logger.info(
            f"WARNING: {len(over_allocated)} employees have been over-allocated!"
        )
        # print(over_allocated[["employee_id", "employee_name", "remaining_capacity"]])
        stats["over_allocated_employees"] = len(over_allocated)
    else:
        stats["over_allocated_employees"] = 0

    return final_manning, stats, reallocation_tracking


def run_intraday_allocation(
    base_path="csv_files", date_str=None, specify_time=None, mode=None
):
    """
    Run an intraday allocation for a specific date

    Parameters:
    base_path (str): Base path for file operations
    date_str (str, optional): Date string in format YYYYMMDD or YYYY-MM-DD, defaults to today
    specify_time (str, optional): Time string in format HH:MM:SS, defaults to current time
    mode (str, optional): Force a specific mode ('intraday' or 'endofday'), defaults to time-based

    Returns:
    tuple: (Final manning DataFrame, statistics dict, reallocation tracking list)
    """
    # Parse date or use today
    if date_str:
        if "-" in date_str:
            allocation_date = pd.Timestamp(date_str)
        else:
            # Format like 20250401
            allocation_date = pd.Timestamp(
                int(date_str[0:4]),  # Year
                int(date_str[4:6]),  # Month
                int(date_str[6:8]),  # Day
            )
    else:
        allocation_date = pd.Timestamp.now().floor("D")  # Today at midnight

    # Use specified time or current time
    if specify_time:
        current_time = pd.Timestamp.combine(
            allocation_date.date(), pd.Timestamp(specify_time).time()
        )
    else:
        current_time = get_ist_time()

    logger.info(
        f"Running intraday allocation for date: {allocation_date.date()} at time: {current_time.time()}"
    )

    # Load data
    try:
        logger.info(f"Loading data from base path: {base_path}")
        attendance_df = pd.read_csv(f"{base_path}/Attendance_master.csv")
        Act_Employees = pd.read_csv(f"{base_path}/Active Employees.csv")
        emp_fact_df = pd.read_csv(f"{base_path}/Emp_Fact.csv")

        # Convert attendance date
        # attendance_df['Attendance Date'] = pd.to_datetime(attendance_df['Attendance Date'])
        attendance_df["Attendance Date"] = pd.to_datetime(
            attendance_df["Attendance Date"], format="%d-%m-%Y", errors="coerce"
        )

        # Read WIP data if it exists (optional)
        try:
            wip_df = pd.read_csv(f"{base_path}/WIP.csv")
            logger.info(f"Loaded WIP data with {len(wip_df)} records")
            has_wip_data = True
        except Exception as e:
            logger.info(f"No WIP data found or error loading WIP data: {e}")
            wip_df = None
            has_wip_data = False

        # Filter employees
        emp_fact_df = emp_fact_df[
            emp_fact_df["EMPLOYEE ID"].isin(Act_Employees["Emp No"])
        ]
        emp_fact_df = emp_fact_df[emp_fact_df["TYPE"].isin(["Primary", "Secondary"])]

        # Force specific mode if requested
        if mode:
            if mode.lower() == "endofday":
                logger.info("Forcing end-of-day mode")
                return perform_end_of_day_allocation(
                    allocation_date, wip_df if has_wip_data else None
                )
            # For intraday mode, we continue with the normal flow

        # Determine if this is an end-of-day run based on time
        end_of_day_time = pd.Timestamp.combine(
            allocation_date.date(), pd.Timestamp(END_OF_DAY_THRESHOLD).time()
        ).tz_localize(pytz.timezone("Asia/Kolkata"))

        is_end_of_day = current_time >= end_of_day_time

        if is_end_of_day and not mode:
            logger.info(
                f"Time {current_time.time()} is after {END_OF_DAY_THRESHOLD}, running end-of-day allocation"
            )
            return perform_end_of_day_allocation(
                allocation_date, wip_df if has_wip_data else None
            )

        # Load the morning D-day file for this date
        date_fmt = allocation_date.strftime("%Y%m%d")
        previous_manning_path = f"{base_path}/dday0_manning_{date_fmt}.csv"

        if not os.path.exists(previous_manning_path):
            raise FileNotFoundError(
                f"Cannot find morning D-day file: {previous_manning_path}"
            )

        previous_manning = pd.read_csv(previous_manning_path)
        logger.info(f"Loaded previous manning from: {previous_manning_path}")

        # Run intraday allocation
        manning, stats, tracking = perform_intraday_allocation(
            allocation_date,
            attendance_df,
            emp_fact_df,
            previous_manning,
            wip_df if has_wip_data else None,
            current_time,
        )

        # Generate report
        report = generate_reallocation_report(stats, tracking)
        logger.info(report)

        # Save the manning sheet with timestamp
        time_str = current_time.strftime("%Y%m%d_%H%M")
        output_path = f"{base_path}/intraday_manning_{time_str}.csv"
        manning.to_csv(output_path, index=False)
        logger.info(f"Intraday manning sheet saved to: {output_path}")

        return manning, stats, tracking

    except Exception as e:
        logger.info(f"Error performing intraday allocation: {e}")
        import traceback

        traceback.print_exc()
        return None, None, None


def perform_end_of_day_allocation_new(
    allocation_date,
    attendance_df,
    emp_fact_df,
    previous_manning,
    wip_df=None,
    current_time=None,
):
    """
    Perform end-of-day allocation that plans for the next day's workforce allocation.

    This function is called after 5:30 PM and prepares allocations for the following day.
    It accounts for:
    1. Next day's planned attendance
    2. Current WIP status that needs to be carried forward
    3. Work priorities for the next day

    Parameters:
    allocation_date (datetime): Tomorrow's date for which to perform allocation
    attendance_df (DataFrame): Planned attendance data for tomorrow
    emp_fact_df (DataFrame): Employee fact table with capacity information
    previous_manning (DataFrame): Manning dataframe from the current day's allocation
    wip_df (DataFrame, optional): WIP data for adjusting quantities for tomorrow
    current_time (datetime, optional): Current time when this end-of-day allocation is being performed

    Returns:
    tuple: (Final manning DataFrame for tomorrow, statistics dict, reallocation tracking list)
    """
    if current_time is None:
        current_time = get_ist_time()

    run_timestamp = get_ist_time()

    # Create fresh manning dataframe for tomorrow
    tomorrow_manning = previous_manning.copy()

    # Reset certain columns for the new allocation
    reset_columns = [
        "original_emp",
        "original_emp_name",
        "new_emp",
        "reallocation_level",
        "re_allocated_employee",
        "reallocation_reason",
    ]

    for col in reset_columns:
        if col in tomorrow_manning.columns:
            tomorrow_manning[col] = None

    # Filter attendance for tomorrow's planned attendance
    tomorrow_attendance = attendance_df[
        attendance_df["attendance_date"] == allocation_date
    ]

    # Create attendance status mapping
    if not tomorrow_attendance.empty:
        # Get latest status for each employee (in case there are multiple records)
        if "last_updated" in tomorrow_attendance.columns:
            tomorrow_attendance["last_updated"] = pd.to_datetime(
                tomorrow_attendance["last_updated"], errors="coerce"
            )
            latest_attendance = (
                tomorrow_attendance.sort_values("last_updated")
                .groupby("employee_id")
                .last()
            )
        else:
            latest_attendance = tomorrow_attendance.groupby("employee_id").first()

        # Identify employees who are planned to be absent tomorrow
        planned_absent = latest_attendance[
            latest_attendance["status"] == "A"
        ].index.tolist()

        # Identify employees who are planned to be present tomorrow
        planned_present = latest_attendance[
            latest_attendance["status"] == "P"
        ].index.tolist()

        # Create a Series mapping employee IDs to their attendance status
        attendance_status_map = latest_attendance["status"].copy()
        # Mark planned early departures
        if "early_departure" in latest_attendance.columns:
            early_departure_mask = latest_attendance["early_departure"] == True
            attendance_status_map[early_departure_mask] = (
                attendance_status_map[early_departure_mask] + " (Early Departure)"
            )
    else:
        planned_absent = []
        planned_present = []
        attendance_status_map = pd.Series(dtype="object")
        logger.info("Warning: No planned attendance data found for tomorrow!")

    # Prepare employee fact dataframe with full capacities for tomorrow
    updated_emp_fact = emp_fact_df.copy()

    # Reset capacities to full for tomorrow
    updated_emp_fact["remaining_capacity"] = updated_emp_fact["average_capacity"]

    # Set capacity to zero for employees planned to be absent tomorrow
    updated_emp_fact.loc[
        updated_emp_fact["employee_id"].isin(planned_absent), "remaining_capacity"
    ] = 0

    # Process WIP adjustment to adjust planned quantities for tomorrow
    if wip_df is not None:
        tomorrow_manning = adjust_planned_quantities_with_wip(tomorrow_manning, wip_df)

    # Identify allocations that will be affected due to planned absences
    affected_allocations = identify_affected_allocations(
        tomorrow_manning, planned_absent, handle_shortages=True
    )

    # Perform reallocation for tomorrow
    reallocated_manning, reallocation_tracking = reallocate_work(
        affected_allocations, updated_emp_fact, allocation_date
    )

    # Update manning sheet with full details
    final_manning = tomorrow_manning.copy()

    # Initialize preferred_employees column if not present
    if "preferred_employees" not in final_manning.columns:
        final_manning["preferred_employees"] = None

    # Update with reallocated data
    for idx in reallocated_manning.index:
        # Determine reallocation reason
        if tomorrow_manning.loc[idx, "allocated_emp_id"] in planned_absent:
            reallocation_reason = "planned_absence"
        elif tomorrow_manning.loc[idx, "shortage_flag"] in [
            "Partially Shortage",
            "Shortage Unresolved",
        ]:
            reallocation_reason = "shortage_resolution"
        else:
            reallocation_reason = "other"

        # Update preferred employees
        final_manning.loc[idx, "preferred_employees"] = reallocated_manning.loc[
            idx, "preferred_employees"
        ]

        # Set original employee information
        final_manning.loc[idx, "original_emp"] = tomorrow_manning.loc[
            idx, "allocated_emp_id"
        ]
        if "original_emp_name" in final_manning.columns:
            final_manning.loc[idx, "original_emp_name"] = tomorrow_manning.loc[
                idx, "ALLOCATED EMP NAME"
            ]

        # Update reallocation fields
        if "new_emp" in final_manning.columns:
            final_manning.loc[idx, "new_emp"] = reallocated_manning.loc[
                idx, "allocated_emp_id"
            ]
        if "reallocation_level" in final_manning.columns:
            final_manning.loc[idx, "reallocation_level"] = reallocated_manning.loc[
                idx, "reallocation_level"
            ]
        if "re_allocated_employee" in final_manning.columns:
            final_manning.loc[idx, "re_allocated_employee"] = reallocated_manning.loc[
                idx, "re_allocated_employee"
            ]
        if "reallocation_reason" in final_manning.columns:
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

    # Update attendance status for all employees
    if "attendance_status" in final_manning.columns:
        final_manning["attendance_status"] = final_manning["attendance_status"].astype(
            str
        )
        for idx in final_manning.index:
            emp_id = final_manning.loc[idx, "allocated_emp_id"]
            if emp_id in attendance_status_map:
                final_manning.loc[idx, "attendance_status"] = attendance_status_map[
                    emp_id
                ]

    # Record this run's information
    run_record = {
        "timestamp": run_timestamp,
        "plan_date": allocation_date,
        "plan_type": "next_day",
        "planned_absent_count": len(planned_absent),
        "reallocations": len(reallocation_tracking),
        "status": "completed",
    }

    # Update run history
    if (
        "run_history" in final_manning.columns
        and "current_run" in final_manning.columns
    ):
        for idx in final_manning.index:
            history = safe_eval_history(final_manning.at[idx, "run_history"])

            if idx in reallocated_manning.index:
                reason = (
                    final_manning.at[idx, "reallocation_reason"]
                    if "reallocation_reason" in final_manning.columns
                    else "unknown"
                )
                history.append(
                    {
                        "run_timestamp": run_timestamp,
                        "run_type": "end_of_day",
                        "previous_emp": tomorrow_manning.at[idx, "allocated_emp_id"],
                        "new_emp": final_manning.at[idx, "allocated_emp_id"],
                        "reason": reason,
                    }
                )

            final_manning.at[idx, "run_history"] = str(history)
            final_manning.at[idx, "current_run"] = str(run_record)

    # Calculate statistics
    shortage_rows = tomorrow_manning[
        tomorrow_manning["shortage_flag"].isin(
            ["Partially Shortage", "Shortage Unresolved"]
        )
    ]

    stats = {
        "run_timestamp": run_timestamp,
        "allocation_date": allocation_date,
        "plan_type": "next_day",
        "total_allocations": len(final_manning),
        "planned_absent": len(planned_absent),
        "allocations_affected": len(affected_allocations),
        "successful_reallocations": len(
            reallocated_manning[reallocated_manning["shortage_flag"] == "Reallocated"]
        ),
        "failed_reallocations": len(
            reallocated_manning[reallocated_manning["shortage_flag"] != "Reallocated"]
        ),
        "reallocation_by_level": pd.Series(reallocated_manning["reallocation_level"])
        .value_counts()
        .to_dict()
        if "reallocation_level" in reallocated_manning.columns
        else {},
        "reallocation_by_reason": pd.Series(
            final_manning.loc[reallocated_manning.index, "reallocation_reason"]
        )
        .value_counts()
        .to_dict()
        if "reallocation_reason" in final_manning.columns
        else {},
        "plan_source": "End_of_Day",
        "total_absent": len(planned_absent),
        "total_shortages": len(shortage_rows),
    }

    # Check for any over-utilization
    over_allocated = updated_emp_fact[updated_emp_fact["remaining_capacity"] < 0]
    if not over_allocated.empty:
        logger.info(
            f"WARNING: {len(over_allocated)} employees have been over-allocated for tomorrow!"
        )
        stats["over_allocated_employees"] = len(over_allocated)
    else:
        stats["over_allocated_employees"] = 0

    return final_manning, stats, reallocation_tracking


def fetch_and_transform_planned_leaves(today, nextDay, attendance_df):
    planned_attendance_df = pd.read_excel("csv_files/LEAVE_APPLICATIONS_PENDING.xlsx")

    employees_on_leave = get_employees_on_leave_tomorrow(
        today, nextDay, planned_attendance_df
    )

    allocation_date_today = pd.Timestamp(today)

    allocation_date_tomorrow = pd.Timestamp(nextDay)

    attendance_df["attendance_date"] = pd.to_datetime(attendance_df["attendance_date"])

    daily_attendance = attendance_df[
        attendance_df["attendance_date"] == allocation_date_today
    ]

    daily_attendance = daily_attendance.copy()  # <- avoid the warning
    daily_attendance.loc[:, "status"] = "P"
    daily_attendance["attendance_date"] = allocation_date_tomorrow

    daily_attendance["employee_id"] = daily_attendance["employee_id"].astype(int)
    employees_on_leave["Empployee ID"] = employees_on_leave["Empployee ID"].astype(int)

    mask = daily_attendance.set_index(["employee_id", "employee_name"]).index.isin(
        employees_on_leave.set_index(["Empployee ID", "Empployee Name"]).index
    )

    daily_attendance.loc[mask, "status"] = "A"

    return daily_attendance


def get_employees_on_leave_tomorrow(today, nextDay, planned_attendance_df):
    # Ensure 'From' and 'To' columns are datetime.date
    planned_attendance_df["From"] = pd.to_datetime(
        planned_attendance_df["From"], dayfirst=True
    ).dt.date
    planned_attendance_df["To"] = pd.to_datetime(
        planned_attendance_df["To"], dayfirst=True
    ).dt.date

    # Expand rows for each day of leave
    expanded_rows = []
    for _, row in planned_attendance_df.iterrows():
        from_date = row["From"]
        to_date = row["To"]

        if from_date <= to_date:
            leave_dates = pd.date_range(start=from_date, end=to_date)
            for date in leave_dates:
                expanded_rows.append(
                    {
                        "Empployee Name": row["Empployee Name"],
                        "Empployee ID": row["Empployee ID"],
                        "Department": row["Department"],
                        "Line": row["Line"],
                        "Role": row["Role"],
                        "LeaveDate": date.date(),
                        "From": from_date,
                        "To": to_date,
                    }
                )

    expanded_df = pd.DataFrame(expanded_rows)

    # Filter for exact match with nextDay and exclude Sundays
    result = expanded_df[
        (expanded_df["LeaveDate"] == nextDay)
        & (pd.to_datetime(expanded_df["LeaveDate"]).dt.dayofweek != 6)  # 6 = Sunday
    ]

    return result


# DDay function for 08:50 AM
def handle_startofday(
    allocation_date, attendance_df, emp_fact_df, wip_df, has_wip_data, **kwargs
):
    manning, stats, tracking = perform_dday_allocation(
        allocation_date, attendance_df, emp_fact_df, wip_df if has_wip_data else None
    )
    generate_reallocation_report(stats, tracking)

    over_allocated = emp_fact_df[emp_fact_df["remaining_capacity"] < 0]
    if not over_allocated.empty:
        logger.info(
            f"WARNING: {len(over_allocated)} employees have been over-allocated!"
        )
        logger.info(
            over_allocated[["employee_id", "employee_name", "remaining_capacity"]]
        )
    return manning, stats, tracking


# DDay function for 12:45 PM
def handle_intraday(
    allocation_date,
    attendance_df,
    emp_fact_df,
    wip_df,
    has_wip_data,
    current_time,
    **kwargs,
):
    previous_manning = pd.DataFrame(list(DDayData.objects.all().values()))
    manning, stats, tracking = perform_intraday_allocation(
        allocation_date,
        attendance_df,
        emp_fact_df,
        previous_manning,
        wip_df if has_wip_data else None,
        current_time,
    )
    generate_reallocation_report(stats, tracking)
    return manning, stats, tracking


# DDay function for 17:30 PM
def handle_endofday(
    allocation_date,
    attendance_df,
    emp_fact_df,
    wip_df,
    has_wip_data,
    current_time,
    current_date,
    **kwargs,
):
    next_day = current_date + timedelta(days=1)
    attendance_df_updated = fetch_and_transform_planned_leaves(
        current_date, next_day, attendance_df
    )

    logger.info(
        f"Time {current_time.time()} is after {END_OF_DAY_THRESHOLD}, running end-of-day allocation"
    )

    previous_manning = pd.DataFrame(list(DDayData.objects.all().values()))
    manning, stats, tracking = perform_end_of_day_allocation_new(
        allocation_date,
        attendance_df_updated,
        emp_fact_df,
        previous_manning,
        wip_df if has_wip_data else None,
        current_time,
    )
    generate_reallocation_report(stats, tracking)
    return manning, stats, tracking
