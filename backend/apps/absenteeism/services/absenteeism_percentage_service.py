import logging
import os
import re
from datetime import timedelta

import pandas as pd

logger = logging.getLogger(__name__)


def load_active_employees():
    """Load and process the active employees CSV file"""
    try:
        # Update path to look in utils directory
        csv_path = os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            ),
            "csv_files",
            "Active_Employees.csv",
        )
        logger.info(f"Attempting to read Active Employees from: {csv_path}")

        if not os.path.exists(csv_path):
            # Try alternate location
            csv_path = os.path.join(
                os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                ),
                "csv_files",
                "Active_Employees.csv",
            )
            logger.info(f"Trying alternate path: {csv_path}")

            if not os.path.exists(csv_path):
                logger.error("Active_Employees.csv not found in any expected location")
                return pd.DataFrame(columns=["Line", "Total_Employees"])

        df = pd.read_csv(csv_path)

        # Process department to extract line and section
        df["Line"] = df["Department"].str.extract(r"(LINE \d+)")[0]
        df["Section"] = df["Department"].str.replace(r"LINE \d+ ", "", regex=True)

        # Count employees per line only
        emp_counts = df.groupby("Line").size().reset_index(name="Total_Employees")
        return emp_counts
    except Exception as e:
        logger.error(f"Error loading active employees: {str(e)}")
        return pd.DataFrame(columns=["Line", "Total_Employees"])


def get_working_days(start_date, period_days):
    """Generate working days (Mon-Fri) for the given period"""
    dates = []
    current_date = start_date
    while len(dates) < period_days:
        if current_date.weekday() < 5:  # Monday-Friday
            dates.append(current_date)
        current_date += timedelta(days=1)
    return dates


def calculate_line_percentages_older_version(data, date, selected_line="ALL"):
    date_data = data[data["date"] == date]
    if not date_data.empty:
        # Group by Line to calculate percentage for each line
        line_groups = date_data.groupby("Line")
        line_percentages = []

        for line_name, line_group in line_groups:
            # Skip lines that don't match selected line
            if selected_line != "ALL" and line_name != selected_line:
                continue

            line_absent_count = line_group["Absent"].sum()
            line_total_employees = (
                line_group["Total_Employees"].iloc[0]
                if "Total_Employees" in line_group.columns
                else len(line_group)
            )

            if pd.notna(line_total_employees) and line_total_employees > 0:
                line_percentage = (line_absent_count / line_total_employees) * 100
                line_percentages.append(line_percentage)

        # For single line, return its percentage directly
        if selected_line != "ALL":
            return round(line_percentages[0], 1) if line_percentages else 0.0
        # For all lines, calculate average
        return (
            round(sum(line_percentages) / len(line_percentages), 1)
            if line_percentages
            else 0.0
        )
    else:
        # Handle similar dates if exact date not found
        similar_data = data[
            (data["date"].apply(lambda d: d.month) == date.month)
            & (abs(data["date"].apply(lambda d: d.day) - date.day) <= 3)
        ]
        if not similar_data.empty:
            # Modified code for similar dates
            similar_data = data[
                (data["date"].apply(lambda d: d.month) == date.month)
                & (abs(data["date"].apply(lambda d: d.day) - date.day) <= 3)
            ]
            if not similar_data.empty:
                # Calculate percentage for each date separately
                date_percentages = []
                for single_date in similar_data["date"].unique():
                    day_data = similar_data[similar_data["date"] == single_date]
                    line_groups = day_data.groupby("Line")
                    day_percentages = []

                    for _, line_group in line_groups:
                        line_absent_count = line_group["Absent"].sum()
                        line_total_employees = (
                            line_group["Total_Employees"].iloc[0]
                            if "Total_Employees" in line_group.columns
                            else len(line_group)
                        )

                        if pd.notna(line_total_employees) and line_total_employees > 0:
                            line_percentage = (
                                line_absent_count / line_total_employees
                            ) * 100
                            day_percentages.append(line_percentage)

                    if day_percentages:
                        date_percentages.append(
                            sum(day_percentages) / len(day_percentages)
                        )

            # Take average of all similar dates
            return (
                round(sum(date_percentages) / len(date_percentages), 1)
                if date_percentages
                else 0.0
            )
        else:
            return 0.0


# Define a function to calculate absenteeism percentages
def calculate_line_percentages(data_for_date, emp_counts, target_line="ALL"):
    """
    Calculate absenteeism percentage for a specific date and line

    Args:
        data_for_date: QuerySet of Absenteeism objects for a specific date
        target_line: Line to calculate percentage for (or 'ALL' for all lines)

    Returns:
        float: Absenteeism percentage
    """
    if not data_for_date:
        return 0.0

    line_percentages = []

    # Use iterator for QuerySets to save memory
    if hasattr(data_for_date, "iterator"):
        data_for_date = data_for_date.iterator(chunk_size=2000)

    # Pre-compile regex for speed
    line_pattern = re.compile(r"(LINE\s*\d+)", re.IGNORECASE)

    # Group data by line
    line_groups = {}
    for record in data_for_date:
        # Extract line from department field
        dept = record.department or ""
        line_match = line_pattern.search(dept)
        line_name = line_match.group(1).upper() if line_match else "UNKNOWN"

        if line_name not in line_groups:
            line_groups[line_name] = {"records": [], "absent": 0}

        line_groups[line_name]["records"].append(record)
        if record.attendance == "A":
            line_groups[line_name]["absent"] += 1

    # Calculate percentage for each line
    for line_name, group_data in line_groups.items():
        # Skip if not the target line (when filtering for a specific line)
        if target_line != "ALL" and line_name != target_line:
            continue

        total_employees = emp_counts.get(line_name, 0)
        if total_employees > 0:
            line_percentage = (group_data["absent"] / total_employees) * 100
            line_percentages.append(line_percentage)

    # Calculate average percentage
    if line_percentages:
        # For specific line, return single value; for ALL, return average
        if target_line != "ALL" and len(line_percentages) == 1:
            return round(line_percentages[0], 1)
        return round(sum(line_percentages) / len(line_percentages), 1)

    return 0.0


# Function to get working days around a date
def get_working_days_around_date(target_date, total_days=5):
    """Generate working days around a target date (excluding weekends)"""
    dates = []
    current_date = target_date

    # If target date is weekend, find the nearest working day
    while current_date.weekday() >= 5:  # Saturday or Sunday
        current_date += timedelta(days=1)

    # Get 2 days before the target date
    dates_before = []
    temp_date = current_date - timedelta(days=1)
    while len(dates_before) < 2:
        if temp_date.weekday() < 5:  # Monday-Friday
            dates_before.append(temp_date)
        temp_date -= timedelta(days=1)

    # Get 2 days after the target date
    dates_after = []
    temp_date = current_date + timedelta(days=1)
    while len(dates_after) < 2:
        if temp_date.weekday() < 5:  # Monday-Friday
            dates_after.append(temp_date)
        temp_date += timedelta(days=1)

    # Combine all dates
    return sorted(dates_before + [current_date] + dates_after)
