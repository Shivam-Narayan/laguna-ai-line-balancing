import logging

logger = logging.getLogger(__name__)

import ast

import pandas as pd

from .models import ManningSheetData


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


def get_prioritized_employees(emp_df, line=None, factory=None, floor=None, code=None):
    """
    Consistent prioritization logic from original 7-day system
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

    return emp_df[query].sort_values(
        by=["type", "remaining_capacity"], ascending=[True, False]
    )


def load_planned_allocation(allocation_date):
    """
    Load the planned allocation from the 7-day plan only
    """
    # Load 7-day plan
    manning_0_df = ManningSheetData.objects.filter(forecast_period=0).values()
    manning_0_df = pd.DataFrame(list(manning_0_df))
    manning_0_df["planned_dates"] = pd.to_datetime(manning_0_df["planned_dates"])

    # Filter for the specific date
    plan_0 = manning_0_df[manning_0_df["planned_dates"] == allocation_date]

    if not plan_0.empty:
        return plan_0, "D-day"
    else:
        raise ValueError(
            f"No D-day planned allocation found for date: {allocation_date}"
        )


def identify_affected_allocations(
    planned_manning_df, absent_employees, handle_shortages=True
):
    """
    Identify allocations that need to be modified due to attendance issues
    """
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


def find_preferred_employees(emp_fact_df, code=None, line=None, current_emp_id=None):
    """
    Find preferred employees with available capacity for a specific code/line
    Returns a comma-separated string of employee names
    """
    query = emp_fact_df["remaining_capacity"] > 0

    if code:
        query &= emp_fact_df["code"] == code
    if line:
        query &= emp_fact_df["line"] == line

    # Exclude the currently allocated employee (if any)
    if current_emp_id is not None and not pd.isna(current_emp_id):
        query &= emp_fact_df["employee_id"] != current_emp_id

    preferred_emps = emp_fact_df[query].sort_values(
        by=["type", "remaining_capacity"], ascending=[True, False]
    )

    if preferred_emps.empty:
        return ""

    # Create a string with employee names and their remaining_capacity
    preferred_list = [
        f"{row['employee_name']} ({row['remaining_capacity']})"
        for _, row in preferred_emps.iterrows()
    ]

    # Create a string with employee names, their line, and remaining capacity
    preferred_list = [
        f"{row['employee_name']} [line: {row['line']}]"  # ({row['REMAINING CAPACITY']})
        for _, row in preferred_emps.iterrows()
    ]

    return ", ".join(preferred_list)


def reallocate_work(affected_allocations, emp_fact_df, allocation_date):
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
            emp_fact_df, line=line, code=code
        )
        allocation_level = "same_line"

        if available_employee.empty:
            available_employee = get_prioritized_employees(
                emp_fact_df, factory=factory, code=code
            )
            allocation_level = "same_factory"

        if available_employee.empty:
            available_employee = get_prioritized_employees(
                emp_fact_df, floor=floor, code=code
            )
            allocation_level = "same_floor"

        if available_employee.empty:
            available_employee = get_prioritized_employees(emp_fact_df, code=code)
            allocation_level = "other_location"

        # Find and store preferred employees for manual assignment
        # preferred_employees = find_preferred_employees(emp_fact_df, code=code, line=line)
        # affected_allocations.at[index, 'preferred_employees'] = preferred_employees

        current_emp_id = row["allocated_emp_id"]  # The currently allocated employee
        preferred_employees = find_preferred_employees(
            emp_fact_df, code=code, line=line, current_emp_id=current_emp_id
        )
        affected_allocations.at[index, "PREFERRED_EMPLOYEES"] = preferred_employees

        if not available_employee.empty:
            # Find the first employee with sufficient capacity
            employee_allocated = False

            for i in range(len(available_employee)):
                emp = available_employee.iloc[i]
                emp_id = emp["employee_id"]

                # Check if employee has positive remaining_capacity
                if emp["remaining_capacity"] <= 0:
                    continue

                # Calculate safe allocation amount
                allocation = min(planned_qty, emp["remaining_capacity"])

                # Skip if allocation is too small to be useful
                if allocation <= 0:
                    continue

                # Update capacity - calculate new remaining_capacity to double-check
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
                affected_allocations.at[index, "target_100"] = allocation
                affected_allocations.at[index, "target_90"] = allocation * 0.9
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


def perform_dday_allocation(allocation_date, attendance_df, emp_fact_df):
    """
    Main function to perform D-day allocation as a single manual run
    Handles both absent employees and early departures
    """
    # Reset daily capacity for this run
    emp_fact_df["remaining_capacity"] = emp_fact_df["average_capacity"]
    run_timestamp = pd.Timestamp.now()

    # Load only from 7-day plan
    planned_manning, plan_source = load_planned_allocation(allocation_date)
    working_manning = planned_manning.copy()

    # Ensure all tracking columns exist
    tracking_columns = [
        "run_history",
        "current_run",
        "original_emp",
        "new_emp",
        "reallocation_level",
        "re_allocated_employee",
        "preferred_employees",
        "reallocation_reason",  # New column to track why reallocation occurred
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
    else:
        current_absent = []
        logger.info("Warning: No attendance data found for this date!")

    # Handle capacity for absent and early departure employees
    emp_fact_df.loc[
        emp_fact_df["employee_id"].isin(current_absent), "remaining_capacity"
    ] = 0

    # Reset daily capacity
    emp_fact_df["remaining_capacity"] = emp_fact_df["average_capacity"]

    # Handle capacity for absent and early departure employees
    emp_fact_df.loc[
        emp_fact_df["employee_id"].isin(current_absent), "remaining_capacity"
    ] = 0

    # Find allocations affected by new absences
    affected_allocations = identify_affected_allocations(
        working_manning, current_absent, handle_shortages=True
    )

    # Perform reallocation
    reallocated_manning, reallocation_tracking = reallocate_work(
        affected_allocations, emp_fact_df, allocation_date
    )

    # Update manning sheet with full details
    final_manning = working_manning.copy()

    # Add preferred employees column for all rows if not already reallocated
    for idx in final_manning.index:
        if idx not in reallocated_manning.index:
            line = final_manning.loc[idx, "line"]
            code = final_manning.loc[idx, "code"]
            preferred_employees = find_preferred_employees(
                emp_fact_df, code=code, line=line
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

    # Calculate statistics
    stats = {
        "run_timestamp": run_timestamp,
        "allocation_date": allocation_date,
        "plan_source": plan_source,
        "total_allocations": len(final_manning),
        "total_absent": len(current_absent),
        "allocations_affected": len(affected_allocations),
        "successful_reallocations": len(
            reallocated_manning[reallocated_manning["shortage_flag"] == "Reallocated"]
        ),
        "failed_reallocations": len(
            reallocated_manning[
                reallocated_manning["shortage_flag"] == "Reallocation Failed"
            ]
        ),
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
        logger.info(
            over_allocated[["employee_id", "employee_name", "remaining_capacity"]]
        )
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
Allocations Affected: {stats["allocations_affected"]}
Successful Reallocations: {stats["successful_reallocations"]}
Failed Reallocations: {stats["failed_reallocations"]}
Over-allocated Employees: {stats.get("over_allocated_employees", 0)}

Reallocation by Level:
{pd.DataFrame([stats["reallocation_by_level"]]).to_string()}

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
