import pandas as pd

from .excel_utils import convert_to_excel_data


def generate_prediction_data(data):
    sections = [
        {
            "Section": op["section"].upper(),
            "Total Active Operators": op["count"],
            "Total Operators Present": supply["count"],
            "Total Operatos Gap": gap["count"],
        }
        for op, supply, gap in zip(
            data["total_operators"],
            data["total_operators_supply"],
            data["total_operators_gap"],
        )
    ]

    # Add the "Total" row
    sections.append(
        {
            "Section": "Total",
            "Total Active Operators": data["total_employees"],
            "Total Operators Present": data["projected_attendance"],
            "Total Operatos Gap": data["total_predicted_absenteeism"],
        }
    )

    # Add the "Absenteeism percentage" row
    sections.append(
        {
            "Section": "Predicted Absenteeism (%)",
            "Total Active Operators": data["absenteeism_percentage"],
            "Total Operators Present": "",
            "Total Operatos Gap": "",
        }
    )

    line = f"{data['line']} lines" if data["line"].lower() == "all" else data["line"]
    forecast_period = data["forecast_period"]

    excel_data = convert_to_excel_data(
        sections,
        "Absenteeism Prediction Report",
        data["Target data"],
        prediction=[line, forecast_period],
        machinists_info=[data["required_machinists"], data["actual_machinists"]],
    )

    return excel_data


def calculate_absenteeism_percentage(df_active_emp, df_absentism):
    """
    Calculates absenteeism percentage per line per section grouped by year and month,
    including outlier removal.

    Args:
        df_active_emp (pd.DataFrame): DataFrame containing active employee data.
        df_absentism (pd.DataFrame): DataFrame containing absenteeism data.

    Returns:
        pd.DataFrame: DataFrame with absenteeism percentage.
    """

    emp_count_per_line_section = (
        df_active_emp.groupby(["Line", "Section"])["Emp No"].nunique().reset_index()
    )
    emp_count_per_line_section.rename(
        columns={"Emp No": "Total_Employees"}, inplace=True
    )

    absentism_count_per_month = (
        df_absentism[df_absentism["Status"] == "A"]
        .groupby(["Year", "Month", "Line", "Section"])["Status"]
        .count()
        .reset_index()
    )
    absentism_count_per_month.rename(columns={"Status": "Absent_Count"}, inplace=True)

    Q1 = absentism_count_per_month["Absent_Count"].quantile(0.25)
    Q3 = absentism_count_per_month["Absent_Count"].quantile(0.75)
    IQR = Q3 - Q1
    lower_bound = Q1 - 1.5 * IQR
    upper_bound = Q3 + 1.5 * IQR
    absentism_count_no_outliers = absentism_count_per_month[
        (absentism_count_per_month["Absent_Count"] >= lower_bound)
        & (absentism_count_per_month["Absent_Count"] <= upper_bound)
    ]

    final_data = pd.merge(
        absentism_count_no_outliers,
        emp_count_per_line_section,
        on=["Line", "Section"],
        how="left",
    )
    final_data["Absenteeism_Percentage"] = (
        final_data["Absent_Count"] / (final_data["Total_Employees"] * 26)
    ) * 100
    final_data["Absenteeism_Percentage"] = round(
        final_data["Absenteeism_Percentage"], 1
    )

    return final_data
