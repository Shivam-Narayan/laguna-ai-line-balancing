import io
import json
import pandas as pd
from io import BytesIO
from apps.data_engine.models import LocalHolidayCalendar

def generate_csv():
    """
    Generate CSV data from the LocalHolidayCalendar model and return it in memory.
    """
    try:
        fields = [field.name for field in LocalHolidayCalendar._meta.get_fields()]
        queryset = LocalHolidayCalendar.objects.all()
        data = list(queryset.values(*fields))

        if not data:
            return None

        df = pd.DataFrame(data)
        csv_data = io.StringIO()
        df.to_csv(csv_data, index=False)
        csv_data.seek(0)  # Rewind the StringIO object to the beginning for reading

        return csv_data

    except Exception as e:
        return None



def write_absenteeism_data_to_csv(data, filename="summary.csv"):
    """
    Generates a summary CSV from absenteeism data and returns it as a BytesIO stream.
    
    Args:
        data: Dictionary containing absenteeism data for different production lines
        filename: Name to use for the CSV file (for email attachment)
    
    Returns:
        Tuple of (BytesIO object, filename)
    """
    if isinstance(data, str):
        data = json.loads(data)

    # Remove 'prediction_date' if it exists
    data.pop('prediction_date', None)
    # Remove 'generated_at' if it exists
    data.pop('generated_at', None)

    summary_data = []
    for line, line_data in data.items():
        total_employees = sum(line_data['total_employee_count'].values())
        total_predicted = sum([item['count'] for item in line_data['predicted_absent_count']])
        total_actual = sum([item['count'] for item in line_data['actual_absent_count']])
        predicted_avg = line_data.get('predicted_absenteeism_percentage', 0)
        actual_avg = line_data.get('actual_absenteeism_percentage', 0)

        summary_data.append({
            'Line': line.title(),
            'Total Employees': total_employees,
            'Predicted Absent': int(total_predicted),
            'Actual Absent': total_actual,
            'Predicted Absenteeism %': round(predicted_avg, 2),
            'Actual Absenteeism %': round(actual_avg, 2)
        })

    df_summary = pd.DataFrame(summary_data)

    # Write to in-memory buffer
    buffer = BytesIO()
    df_summary.to_csv(buffer, index=False)
    buffer.seek(0)
    
    return buffer, filename
