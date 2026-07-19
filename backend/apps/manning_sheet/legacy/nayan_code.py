import logging

logger = logging.getLogger(__name__)

import os
from datetime import datetime

# # Setup Django before importing models
# os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
# django.setup()
import pandas as pd


def run_manning_allocation(
    manning_dataframes_dict, emp_fact_df, output_dir="csv_files/"
):
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
    logger.info(f"[{timestamp}] Starting manning allocation process...")

    # Dictionary to store all results
    results = {}

    # List of manning dataframes to process with metadata
    manning_dataframes = [
        {"suffix": "60", "period": 60, "df": manning_dataframes_dict.get("60")}
    ]

    # Filter only Primary and Secondary types from employee data
    emp_fact_df_original = emp_fact_df.copy()
    emp_fact_df_original = emp_fact_df_original[
        emp_fact_df_original["type"].isin(["Primary", "Secondary"])
    ]

    # Process each manning dataframe
    all_processed_dfs = []  # To store all processed dataframes for consolidation
    unallocated_collection = {}  # To store unallocated employee data

    for df_info in manning_dataframes:
        suffix = df_info["suffix"]
        period = df_info["period"]
        manning_df = manning_dataframes_dict.get(suffix)

        try:
            # Check if the dataframe exists
            if manning_df is not None:
                logger.info(f"Processing manning data for period {period}...")

                # Store the df_name for compatibility with original code
                df_name = f"manning_{suffix}_df"

                # Process the manning dataframe
                updated_manning_df, unallocated_employees = process_manning_dataframe(
                    manning_df, emp_fact_df_original.copy(), period
                )

                updated_manning_df.drop_duplicates(inplace=True, ignore_index=True)
                # Save the updated manning dataframe
                output_path = os.path.join(
                    output_dir, f"manning_sheet_{suffix}_with_daily_capacity.csv"
                )
                updated_manning_df.to_csv(output_path, index=False)

                # Store results
                results[f"updated_manning_{suffix}_df"] = updated_manning_df

                # Store unallocated employees in collection using the original df_name format
                unallocated_collection[df_name] = unallocated_employees

                # Add to our collection for consolidation
                all_processed_dfs.append(updated_manning_df)

                logger.info(f"Successfully processed period {period}:")
                logger.info(
                    f"  - Created manning sheet with {len(updated_manning_df)} rows"
                )
                logger.info(f"  - Output saved to {output_path}")
                logger.info()
            else:
                logger.info(
                    f"Warning: Dataframe for period {period} not found, skipping."
                )

        except Exception as e:
            logger.info(f"Error processing period {period}: {e}")

    # Process unallocated employee data
    unallocated_results = process_unallocated_data(
        unallocated_collection, manning_dataframes, output_dir
    )
    results.update(unallocated_results)

    # Create consolidated dataframe from all processed dataframes
    try:
        if all_processed_dfs:
            # Consolidate all dataframes
            consolidated_df = pd.concat(all_processed_dfs, ignore_index=True)

            # Standardize some columns to uppercase
            for col in ["OC NO", "BUYER", "STYLE", "COLOR"]:
                if col in consolidated_df.columns:
                    consolidated_df[col] = consolidated_df[col].str.upper()

            consolidated_df.drop_duplicates(inplace=True, ignore_index=True)
            # Save consolidated dataframe
            consolidated_path = os.path.join(output_dir, "ALL_manning_consolidated.csv")
            consolidated_df.to_csv(consolidated_path, index=False)

            # Store in results
            results["consolidated_manning_df"] = consolidated_df

            # Analyze skill gaps if possible
            if "all_unallocated_employees" in results:
                skill_gap_results = analyze_skill_gaps(
                    consolidated_df, results["all_unallocated_employees"], output_dir
                )
                results.update(skill_gap_results)

            logger.info(
                f"Successfully created consolidated manning dataframe with {len(consolidated_df)} total rows"
            )
            logger.info(f"Saved to: {consolidated_path}")
        else:
            logger.info("No dataframes were processed successfully for consolidation")
    except Exception as e:
        logger.info(f"Error creating consolidated dataframe: {e}")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"[{timestamp}] Manning allocation process completed.")

    return results


def get_prioritized_employees(
    emp_df, employee_used_capacity, line=None, code=None, section=None, emp_type=None
):
    """
    Fetch prioritized employees based on constraints

    Parameters:
    -----------
    emp_df : pandas.DataFrame
        Employee dataframe
    employee_used_capacity : dict
        Dictionary tracking used capacity per employee
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
    emp_df_copy = emp_df.copy()

    for idx, row in emp_df_copy.iterrows():
        emp_id = row["employee_id"]
        skill_capacity = row["average_capacity"]
        already_used = employee_used_capacity.get(emp_id, 0)
        remaining = max(0, skill_capacity - already_used)
        emp_df_copy.at[idx, "effective_remaining_capacity"] = remaining

    # Apply filters
    query = emp_df_copy["effective_remaining_capacity"] > 0

    if line:
        query &= emp_df_copy["line"] == line
    if code:  # Ensure employee only works on assigned CODE
        query &= emp_df_copy["code"] == code
    if section:
        query &= emp_df_copy["section"] == section
    if emp_type:
        query &= emp_df_copy["type"] == emp_type

    # Filter and sort
    filtered_df = emp_df_copy[query].copy()

    # Sort by TYPE (Primary first) and effective remaining capacity
    filtered_df = filtered_df.sort_values(
        by=["type", "effective_remaining_capacity"], ascending=[True, False]
    )

    return filtered_df


###################------ Change 03-05-2025----------------##################


def process_manning_dataframe(manning_df, emp_fact_df, period):
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
    manning_df["PLANNED_DATES"] = pd.to_datetime(manning_df["PLANNED_DATES"])

    updated_manning_df = pd.DataFrame(columns=manning_df.columns)

    # Add allocation columns
    allocation_columns = [
        "ALLOCATED EMP ID",
        "ALLOCATED EMP NAME",
        "ALLOCATED CAPACITY",
        "ALLOCATED_FRM_LINE",
        "ALLOCATED_FRM_FACTORY",
        "ALLOCATED_FRM_FLOOR",
        "SKILL_TYPE",
        "MACHINE_EMP_FACT",
        "SHORTAGE_FLAG",
        "SHORTAGE_REASON",
        "DESIGNATION",
        "TARGET@100%",
        "TARGET@90%",
        "SPLIT_ORDER_ID",
        "PERIOD",
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

    for date in sorted(unique_dates):
        logger.info(f"Processing date: {date}")

        # CRITICAL CHANGE: Track capacity used per employee (not per skill type)
        employee_used_capacity = {}

        # Reset remaining capacity to skill-specific values
        for idx, emp_row in emp_fact_df.iterrows():
            emp_id = emp_row["employee_id"]
            skill_capacity = emp_row["average_capacity"]

            # Initialize used capacity tracking
            if emp_id not in employee_used_capacity:
                employee_used_capacity[emp_id] = 0

            # Set remaining capacity based on skill-specific capacity minus what's already used
            emp_fact_df.at[idx, "remaining_capacity"] = skill_capacity

        # Process orders for this date
        daily_orders = manning_df[manning_df["PLANNED_DATES"] == date].copy()
        grouped_orders = daily_orders.groupby(["LINE", "SECTION", "CODE"])

        new_rows = []

        for (line, section, code), group_orders in grouped_orders:
            logger.info(f"Processing line={line}, section={section}, code={code}")
            group_rows = process_order_group(
                line,
                section,
                code,
                group_orders,
                emp_fact_df,
                employee_used_capacity,
                date,
                period,
            )
            new_rows.extend(group_rows)

        # Track unallocated employees
        unallocated_employees = get_unallocated_employees(
            emp_fact_df, daily_orders, date, period
        )
        if unallocated_employees:
            unallocated_df = pd.DataFrame(unallocated_employees)
            unallocated_employees_list.append(unallocated_df)

        if new_rows:
            date_df = pd.DataFrame(new_rows)
            updated_manning_df = pd.concat(
                [updated_manning_df, date_df], ignore_index=True
            )

    return updated_manning_df, unallocated_employees_list


#########------------------Change 03-05-2025-------------------############


def process_order_group(
    line, section, code, group_orders, emp_fact_df, employee_used_capacity, date, period
):  # added employee_used_capacity on 03-05-2025
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
    total_planned_qty = group_orders["PLANNED_QTY"].sum()
    logger.info(f"Total quantity for this group: {total_planned_qty}")

    # New rows to return
    new_rows = []

    # Get available employees for this skill combination
    available_employees = get_prioritized_employees(
        emp_df=emp_fact_df,
        employee_used_capacity=employee_used_capacity,
        line=line,
        code=code,
        section=section,
    )

    if available_employees.empty:
        # No matching employees - mark all as shortages
        for _, row in group_orders.iterrows():
            shortage_row = row.copy()
            shortage_row["SHORTAGE_FLAG"] = "Shortage Unresolved"

            # Add shortage reason based on availability checks
            any_matching_code = emp_fact_df[emp_fact_df["code"] == code].shape[0] > 0

            if not any_matching_code:
                shortage_row["SHORTAGE_REASON"] = (
                    f"No employees with CODE={code} found in any line"
                )
            else:
                # Check for employees with matching code in different lines
                other_lines = set(
                    emp_fact_df[
                        (emp_fact_df["code"] == code) & (emp_fact_df["line"] != line)
                    ]["line"].unique()
                )

                if other_lines:
                    shortage_row["SHORTAGE_REASON"] = (
                        f"CODE={code} found only in lines: {', '.join(other_lines)}"
                    )
                else:
                    # Check if there are employees in this line but with zero capacity
                    zero_capacity = (
                        emp_fact_df[
                            (emp_fact_df["code"] == code)
                            & (emp_fact_df["line"] == line)
                            & (emp_fact_df["remaining_capacity"] == 0)
                        ].shape[0]
                        > 0
                    )

                    if zero_capacity:
                        shortage_row["SHORTAGE_REASON"] = (
                            f"Employees with CODE={code} in LINE={line} have no remaining capacity"
                        )
                    else:
                        shortage_row["SHORTAGE_REASON"] = (
                            f"No matching employees for LINE={line} and CODE={code}"
                        )

            shortage_row["SPLIT_ORDER_ID"] = ""
            new_rows.append(shortage_row)
        return new_rows

    # Pre-allocate employees to minimize count - this is the key improvement
    employee_allocations = []  # List to track which employees to use and how much
    remaining_total_qty = total_planned_qty

    for _, emp in available_employees.iterrows():
        emp_id = emp["employee_id"]
        skill_capacity = emp[
            "average_capacity"
        ]  # Skill-specific capacity (e.g., 100 for Primary, 80 for Secondary)
        already_used = employee_used_capacity.get(emp_id, 0)
        available_capacity = skill_capacity - already_used

        if available_capacity > 0 and remaining_total_qty > 0:
            allocation = min(remaining_total_qty, available_capacity)
            allocation = round(allocation, 2)

            # The if statement causing error was improperly nested, and is now fixed
            if allocation > 0:
                # Save this allocation plan
                employee_allocations.append(
                    {
                        "EMPLOYEE ID": emp["employee_id"],
                        "EMPLOYEE NAME": emp["employee_name"],
                        "ALLOCATION": allocation,
                        "LINE": emp["line"],
                        "FACTORY": emp["factory"],
                        "FLOOR": emp["floor"],
                        "TYPE": emp["type"],
                        "MACHINE": emp["machine"],
                        "DESIGNATION": emp["designation"],
                        "SKILL_CAPACITY": skill_capacity,  # Store for reference
                    }
                )

                # Update remaining quantity
                remaining_total_qty -= allocation
                remaining_total_qty = round(remaining_total_qty, 2)
                employee_used_capacity[emp_id] = already_used + allocation

                emp_fact_df.loc[
                    (emp_fact_df["employee_id"] == emp["employee_id"])
                    & (emp_fact_df["code"] == emp["code"])
                    & (emp_fact_df["type"] == emp["type"]),
                    "remaining_capacity",
                ] = available_capacity - allocation

                # Update remaining capacity for all skill types of this employee
                # Their remaining capacity = their skill capacity - total used
                emp_fact_df.loc[
                    emp_fact_df["employee_id"] == emp_id, "remaining_capacity"
                ] = emp_fact_df.apply(
                    lambda row: (
                        max(0, row["average_capacity"] - employee_used_capacity[emp_id])
                        if row["employee_id"] == emp_id
                        else row["remaining_capacity"]
                    ),
                    axis=1,
                )

    # Check if we have a shortage after allocation planning
    if remaining_total_qty > 0:
        shortage_qty = remaining_total_qty
        logger.info(
            f"WARNING: Group shortage of {shortage_qty} units for {line}/{section}/{code}"
        )

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
            shortage_row["SHORTAGE_REASON"] = (
                f"No employees available for {line}/{section}/{code}"
            )
            new_rows.append(shortage_row)
            continue

        # first_allocation = True
        split_count = 0
        split_order_id = (
            f"{row['ORDER_NO']}_{row['STYLE']}_{line}_{code}_{date.strftime('%Y%m%d')}"
        )

        # Allocate this order using pre-determined employees
        while remaining_qty > 0 and current_emp_index < len(employee_allocations):
            current_emp = employee_allocations[current_emp_index]

            # How much can this employee take from the current order?
            order_allocation = min(remaining_qty, current_emp["ALLOCATION"])

            if order_allocation > 0:
                # Create a row for this allocation
                # if first_allocation:
                #     current_row = original_row.copy()
                #     first_allocation = False
                #     current_row["SPLIT_ORDER_ID"] = f"{split_order_id}_part1"
                #     split_count = 1
                # else:
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
            shortage_row["SHORTAGE_REASON"] = (
                f"Insufficient capacity: Needed {remaining_qty} more units"
            )
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
                "PERIOD": period,  # Include the period information
            }

            unallocated_employees.append(unallocated_record)

    return unallocated_employees


def process_unallocated_data(unallocated_collection, manning_dataframes, output_dir):
    """
    Process unallocated employee data across all manning periods

    Parameters:
    -----------
    unallocated_collection : dict
        Dictionary with keys as df_names and values as lists of dataframes
    manning_dataframes : list
        List of dictionaries with dataframe metadata
    output_dir : str
        Directory to save output files

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

        # Save to CSV
        period_suffix = df_name.split("_")[1] if "_" in df_name else ""
        output_path = os.path.join(
            output_dir, f"unallocated_employees_{period_suffix}.csv"
        )
        combined_unallocated.to_csv(output_path, index=False)

        logger.info(f"Saved unallocated employees for {df_name} to {output_path}")

        # Store in results
        results[f"unallocated_{df_name}"] = combined_unallocated

        # Add to overall collection
        unallocated_all_periods.append(combined_unallocated)

    # Create consolidated view of all unallocated employees across all periods
    if unallocated_all_periods:
        all_unallocated = pd.concat(unallocated_all_periods, ignore_index=True)

        # Save consolidated unallocated employees
        consolidated_path = os.path.join(output_dir, "ALL_unallocated_employees.csv")
        all_unallocated.to_csv(consolidated_path, index=False)

        # Store in results
        results["all_unallocated_employees"] = all_unallocated

        logger.info(
            f"\nCreated consolidated unallocated employees dataframe with {len(all_unallocated)} total entries"
        )
        logger.info(f"Saved to: {consolidated_path}")

        # Generate training opportunity report
        training_opportunities = all_unallocated.copy()

        # Focus on employees with skillset not required
        skillset_not_required = training_opportunities[
            training_opportunities["CATEGORY"] == "Skillset not required"
        ]

        # Group by employee to see which employees need cross-training
        employee_cross_training = (
            skillset_not_required.groupby(
                ["EMPLOYEE ID", "EMPLOYEE NAME", "LINE", "CODE"]
            )["DATE"]
            .count()
            .reset_index()
        )

        # Rename columns for clarity
        employee_cross_training.rename(
            columns={"DATE": "DAYS_UNALLOCATED"}, inplace=True
        )

        # Sort by days unallocated (descending)
        employee_cross_training = employee_cross_training.sort_values(
            by=["DAYS_UNALLOCATED", "LINE"], ascending=[False, True]
        )

        # Store in results
        results["training_opportunities"] = employee_cross_training

        # Save training opportunities report
        training_path = os.path.join(output_dir, "training_opportunities.csv")
        employee_cross_training.to_csv(training_path, index=False)

        logger.info(
            f"Created training opportunities report with {len(employee_cross_training)} entries"
        )
        logger.info(f"Saved to: {training_path}")

    return results


def analyze_skill_gaps(consolidated_manning_df, all_unallocated_employees, output_dir):
    """
    Analyze skill gaps by comparing shortages with unallocated employees

    Parameters:
    -----------
    consolidated_manning_df : pandas.DataFrame
        Consolidated manning dataframe with all allocations
    all_unallocated_employees : pandas.DataFrame
        Consolidated unallocated employees dataframe
    output_dir : str
        Directory to save output files

    Returns:
    --------
    dict
        Dictionary with skill gap analysis results
    """
    results = {}

    logger.info("\nAnalyzing skill gaps...")

    # Find all shortage rows
    shortages = consolidated_manning_df[
        consolidated_manning_df["SHORTAGE_FLAG"].str.contains("Shortage")
    ]

    if not shortages.empty:
        # Group shortages by code to see which skills have the highest need
        shortage_by_code = (
            shortages.groupby(["LINE", "CODE"])["PLANNED_QTY"].sum().reset_index()
        )

        # Sort by quantity (descending)
        shortage_by_code = shortage_by_code.sort_values(
            by="PLANNED_QTY", ascending=False
        )

        # Rename for clarity
        shortage_by_code.rename(columns={"PLANNED_QTY": "SHORTAGE_QTY"}, inplace=True)

        # Save shortage analysis
        shortage_path = os.path.join(output_dir, "skill_shortages.csv")
        shortage_by_code.to_csv(shortage_path, index=False)

        # Store in results
        results["skill_shortages"] = shortage_by_code

        logger.info(
            f"Created skill shortages report with {len(shortage_by_code)} entries"
        )
        logger.info(f"Saved to: {shortage_path}")

    return results
