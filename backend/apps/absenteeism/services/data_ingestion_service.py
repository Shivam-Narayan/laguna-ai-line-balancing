import gzip
import json
import logging
import pandas as pd
import calendar, re, io, os

from rest_framework import status
from django.db import transaction
from collections import defaultdict
from django.http import HttpResponse
from rest_framework.response import Response
from django.utils.encoding import smart_bytes
from datetime import date, timedelta, datetime
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count, Q, Case, When, IntegerField
from rest_framework.decorators import api_view, permission_classes, authentication_classes

from apps.accounts.models import User
from .prediction_service import model_prediction
from config.utils import truncate_table
from apps.manning_sheet.views import NOTIFICATION_DISPLAY_TITLE
from apps.manning_sheet.models import ManningSheetData, LoadingPlan
from apps.accounts.api.authentication import CookieJWTAuthentication
from ..models import Absenteeism, PredictionData, AbsenteeismPrediction
from apps.manning_sheet.utils import create_bulk_push_notifications, custom_round
from apps.accounts.utils.response_handlers import error_response, success_response
from apps.data_engine.models import LocalHolidayCalendar, EmployeeMaster, AttendanceMaster
from .absenteeism_percentage_service import calculate_line_percentages, get_working_days_around_date
from ..utils import generate_csv, send_email, generate_prediction_data, convert_number, update_sections, merge_duplicates, is_allowed_working_day, sum_section_counts, normalize_sections, write_absenteeism_data_to_csv, export_absenteeism_predictions_excel

logger = logging.getLogger('general')
prediction_response = {}

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def upload_absenteesim_data(request):
    file = request.FILES.get('file')
    month = request.POST.get('month')
    year = request.POST.get('year')

    if not month or not year:
        return error_response(error= 'No month or year provided.', status=status.HTTP_400_BAD_REQUEST)

    if not file:
        return error_response(error= 'No file provided.', status=status.HTTP_400_BAD_REQUEST)

    month_list = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    if month not in month_list:
        return error_response(error=f'Month value required in this format {month_list}', status=status.HTTP_400_BAD_REQUEST)

    try:
        year = int(year)
        # Read the uploaded file
        if file.name.endswith('.csv'):
            try:
                data = pd.read_csv(file, header=1)
                # If the header doesn't contain expected columns, try header=0
                if 'Empcode' not in data.columns:
                    file.seek(0)
                    data = pd.read_csv(file, header=0)
            except Exception:
                # Fallback if the file has only 1 line
                file.seek(0)
                data = pd.read_csv(file, header=0)
        elif file.name.endswith('.xlsx'):
            try:
                data = pd.read_excel(file, header=1)
                if 'Empcode' not in data.columns:
                    file.seek(0)
                    data = pd.read_excel(file, header=0)
            except Exception:
                file.seek(0)
                data = pd.read_excel(file, header=0)
        else:
            return error_response(error= 'Unsupported file format.', status=status.HTTP_400_BAD_REQUEST)

        # Rename columns for dates
        month_number = list(calendar.month_abbr).index(month[:3])  # type: ignore
        _, endDate = calendar.monthrange(year, month_number)
        
        # Include both integer and string keys for robust renaming
        columns_to_rename = {i: f'{i:02d}-{month}-{year}' for i in range(1, endDate + 1)}
        columns_to_rename.update({str(i): f'{i:02d}-{month}-{year}' for i in range(1, endDate + 1)})
        # Also handle potential float parsing like '1.0'
        columns_to_rename.update({f'{i}.0': f'{i:02d}-{month}-{year}' for i in range(1, endDate + 1)})
        
        data = data.rename(columns=columns_to_rename)

        # Melt the data
        date_columns = [f'{day:02d}-{month}-{year}' for day in range(1, endDate + 1)]
        melted_data = pd.melt(
            data,
            id_vars=['Empcode', 'Name', 'Department', 'DOJ', 'P', 'WO', 'H', 'L', 'Ab', 'DP', 'OT1'],
            value_vars=date_columns,
            var_name='Date',
            value_name='Attendance'
        )

        # Convert 'DOJ' to YYYY-MM-DD format
        melted_data['DOJ'] = pd.to_datetime(melted_data['DOJ'], format='%d-%b-%y', errors='coerce')
        melted_data['DOJ'] = melted_data['DOJ'].where(melted_data['DOJ'].notnull(), None)

        # Convert 'Date' to YYYY-MM-DD format
        melted_data['Date'] = pd.to_datetime(melted_data['Date'], format='%d-%b-%Y', errors='coerce')
        if melted_data['Date'].isnull().any():  # type: ignore
            return error_response(error='Invalid date values found in the data.', status=status.HTTP_400_BAD_REQUEST)
        
        melted_data[['P', 'WO', 'H', 'L', 'Ab', 'DP', 'OT1']] = melted_data[['P', 'WO', 'H', 'L', 'Ab', 'DP', 'OT1']].fillna(0)


        # Validate data before creating objects
        absenteeism_objects = []
        for row in melted_data.itertuples(index=False):
            if pd.isnull(row.Empcode) or str(row.Empcode).strip() == '':
                # Skip rows where 'Empcode' is empty or NaN
                continue

            try:
                absenteeism_objects.append(Absenteeism(
                    empcode=row.Empcode,
                    name=row.Name,
                    department=row.Department,
                    doj=row.DOJ if pd.notnull(row.DOJ) else None,
                    date=row.Date,
                    attendance=row.Attendance,
                    present_days=row.P,
                    weekly_offs=row.WO,
                    holidays=row.H,
                    leaves=row.L,
                    absent_days=row.Ab,
                    double_present=row.DP,
                    overtime_hours=row.OT1
                ))
            except Exception as e:
                logger.info(f"Error creating object for row: {row.Empcode}, Error: {str(e)}")

        # Save to database
        if absenteeism_objects:
            try:
                # Delete existing records for the same month and year to prevent duplicate key constraint violations
                Absenteeism.objects.filter(date__year=year, date__month=month_number).delete()
                
                Absenteeism.objects.bulk_create(absenteeism_objects)
                
                # Automatically preprocess the data so it's ready for forecasts
                try:
                    process_absenteeism_data()
                except Exception as e:
                    logger.info(f"Error during preprocessing after upload: {str(e)}")
                    
                return success_response(data= f'Data successfully uploaded {month} {year} and saved.', status=status.HTTP_201_CREATED)
            except Exception as e:
                logger.info(f"Error during bulk_create: {str(e)}")
                return error_response(error=f"Error saving data to the database: {str(e)}", status=status.HTTP_400_BAD_REQUEST)
        else:
            if melted_data.empty:
                return error_response(error='No valid data to save. The uploaded file contains no data rows.', status=status.HTTP_400_BAD_REQUEST)
            return error_response(error='No valid data to save. All rows had missing Empcode.', status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        return error_response(error=f'Error processing the data: {str(e)}', status=status.HTTP_400_BAD_REQUEST)


def process_absenteeism_data():
    try:
        # Use iterator to prevent loading the entire table into memory at once
        absenteeism_records = Absenteeism.objects.filter(department__icontains="LINE").iterator(chunk_size=5000)
        prediction_data_objects = []
        batch_size = 1000

        truncate_table(PredictionData)
        
        # Pre-compile regex for massive speedup in the loop
        dept_pattern = re.compile(r"(LINE\s*\d+)\s+(.*)")

        for record in absenteeism_records:
            try:
                match = dept_pattern.match(record.department)
                if match:
                    department = match.group(1).replace(" ", "")
                    department = re.sub(r"LINE(\d+)", r"LINE \1", department)
                    section = match.group(2).replace(" ", "")
                else:
                    continue

                if record.attendance == 'A':
                    prediction_data_objects.append(
                        PredictionData(
                            date=record.date,
                            empcode=record.empcode,
                            name=record.name,
                            department=department,
                            section=section,
                            attendance=record.attendance
                        )
                    )

                if len(prediction_data_objects) >= batch_size:
                    PredictionData.objects.bulk_create(prediction_data_objects, batch_size=batch_size)
                    prediction_data_objects.clear()

            except Exception:
                continue

        if prediction_data_objects:
            PredictionData.objects.bulk_create(prediction_data_objects, batch_size=batch_size)

        return True, "Records processed and saved successfully."
    except Exception as e:
        return False, f"An unexpected error occurred: {str(e)}"

@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def absenteeism_data_preprocessing(request):
    success, msg = process_absenteeism_data()
    if success:
        return success_response(data=msg)
    else:
        return error_response(error=msg, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def upload_prediction_data(request):
    try:
        # Check if a file is uploaded
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return error_response(error= 'No file provided', status=status.HTTP_400_BAD_REQUEST)

        # Determine file type and read the data into a DataFrame
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(io.StringIO(uploaded_file.read().decode('utf-8')))
        elif uploaded_file.name.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(uploaded_file)
        else:
            return error_response(error= 'Unsupported file format. Please upload a CSV or Excel file.', status=status.HTTP_400_BAD_REQUEST)


        # Ensure required columns are present
        required_columns = [
            'date', 'Line', 'Section', 'Predicted_Absent_Count',
            'historical_mean', 'historical_std', 'deviation_from_mean', 'datetime', 'forecast_period'
        ]
        if not all(col in df.columns for col in required_columns):
            return error_response(error= 'Missing required columns in the Excel file', status=status.HTTP_400_BAD_REQUEST)

        # Clear existing data in the table
        AbsenteeismPrediction.objects.all().delete()

        # Iterate through the rows of the DataFrame and add them to the database
        records = []
        for _, row in df.iterrows():
            record = AbsenteeismPrediction(
                datetime=row['datetime'],
                predicted_absent_count=row['Predicted_Absent_Count'],
                line=row['Line'],
                section=row['Section'],
                forecast_period=row['forecast_period'],
                historical_mean=row['historical_mean'],
                historical_std=row['historical_std'],
                deviation_from_mean=row['deviation_from_mean']
            )
            records.append(record)

        # Bulk create the records for efficiency
        AbsenteeismPrediction.objects.bulk_create(records)

        return success_response(message= 'Data uploaded successfully', status=status.HTTP_201_CREATED)

    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
