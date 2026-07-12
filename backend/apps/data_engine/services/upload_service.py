import logging
import pandas as pd

from django.http import HttpResponse

import typing
from django.core.exceptions import ObjectDoesNotExist
from datetime import datetime
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes, authentication_classes

from ..serializers import CalendarSerializer
from apps.manning_sheet.models import ActiveEmployees, EMPFact
from apps.absenteeism.utils import send_email, convert_to_excel_data, is_allowed_working_day
from apps.accounts.api.authentication import CookieJWTAuthentication
from apps.accounts.utils.response_handlers import success_response, error_response
from ..models import LocalHolidayCalendar, HistoricalWeather, EmployeeMaster, AttendanceMaster, PayableWorkingDays
from config.utils import truncate_table

logger = logging.getLogger('general')

def file_error_response(error_message):
    return error_response(error=error_message, status=status.HTTP_400_BAD_REQUEST)


def read_file(file):
    try:
        if file.name.endswith('.csv'):
            return pd.read_csv(file)
        elif file.name.endswith(('.xls', '.xlsx')):
            return pd.read_excel(file)
        return None
    except Exception as e:
        raise ValueError(f"Error reading file: {str(e)}")


def preprocess_dataframe(df):
    return df.fillna({
        'OC NO': '',
        'ORDER   NO': '',
        'STYLE': '',
        'Line': 0,
        'BUYER': '',
    }).fillna(0)  # Replace all other NaNs with zero


def extract_week_columns(df):
    return [col for col in df.columns if col.lower().startswith(('wk', 'week'))]


def extract_week_number(week_col):
    return int(''.join(filter(str.isdigit, week_col)))


@api_view(['POST'])
def upload_historical_weather_data(request):
    if request.method == 'POST':
        file = request.FILES.get('file')
        if not file:
            return error_response(error= 'No file uploaded', status=400)

        try:
            # Check the file type
            if file.name.endswith('.csv'):
                data = pd.read_csv(file)
            elif file.name.endswith(('.xls', '.xlsx')):
                data = pd.read_excel(file)
            else:
                return error_response(error= 'Unsupported file format. Please upload a CSV or Excel file.', status=400)

            # Replace NaN values with defaults for numeric fields
            data.fillna({
                'severerisk': 0,
                'precip': 0,
                'precipprob': 0,
                'precipcover': 0,
                'snow': 0,
                'snowdepth': 0,
                'windgust': 0,
                'windspeed': 0,
                'winddir': 0,
                'sealevelpressure': 0,
                'cloudcover': 0,
                'visibility': 0,
                'solarradiation': 0,
                'solarenergy': 0,
                'uvindex': 0,
                'moonphase': 0,
            }, inplace=True)

            # Iterate over the rows and save data to the database
            objects_to_create = []
            for row in data.to_dict('records'):
                # Define a helper function to safely strip strings
                def safe_strip(value):
                    if isinstance(value, str):  # Only strip if it's a string
                        return value.strip()
                    return value  # Return the value as is for non-strings
                
                weather_data = HistoricalWeather(
                    name=safe_strip(row.get('name')),
                    datetime=row.get('datetime'),
                    tempmax=row.get('tempmax'),
                    tempmin=row.get('tempmin'),
                    temp=row.get('temp'),
                    feelslikemax=row.get('feelslikemax'),
                    feelslikemin=row.get('feelslikemin'),
                    feelslike=row.get('feelslike'),
                    dew=row.get('dew'),
                    humidity=row.get('humidity'),
                    precip=row.get('precip', 0),
                    precipprob=row.get('precipprob', 0),
                    precipcover=row.get('precipcover', 0),
                    preciptype=safe_strip(row.get('preciptype')),
                    snow=row.get('snow', 0),
                    snowdepth=row.get('snowdepth', 0),
                    windgust=row.get('windgust'),
                    windspeed=row.get('windspeed'),
                    winddir=row.get('winddir'),
                    sealevelpressure=row.get('sealevelpressure'),
                    cloudcover=row.get('cloudcover'),
                    visibility=row.get('visibility'),
                    solarradiation=row.get('solarradiation'),
                    solarenergy=row.get('solarenergy'),
                    uvindex=row.get('uvindex'),
                    severerisk=row.get('severerisk'),
                    sunrise=row.get('sunrise'),
                    sunset=row.get('sunset'),
                    moonphase=row.get('moonphase'),
                    conditions=safe_strip(row.get('conditions')),
                    description=safe_strip(row.get('description')),
                    icon=safe_strip(row.get('icon')),
                    stations=safe_strip(row.get('stations'))
                )
                objects_to_create.append(weather_data)

            # Bulk insert all records
            HistoricalWeather.objects.bulk_create(objects_to_create)

            return success_response(message= 'Data uploaded successfully', status=200)

        except Exception as e:
            return error_response(error= f"Some error: {str(e)}", status=500)

    return error_response(error= 'Invalid request method', status=405)


@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def upload_attendance_file(request):
    if request.method == 'POST':
        file = request.FILES.get('file')
        if not file:
            return error_response(error="File is required", status=status.HTTP_404_NOT_FOUND)
        
        try:
            # Read the Excel file into a DataFrame
            df = pd.read_csv(file, dtype=str)  # Read as string to avoid type issues
            
            # Rename columns to match the Django model
            df.rename(columns={
                "EMPLOYEE ID": "employee_id",
                "EMPLOYEE NAME": "employee_name",
                "LINE": "line",
                "FACTORY": "factory",
                "FLOOR": "floor",
                "SECTION": "section",
                "Attendance Date": "attendance_date",
                "Last_Updated": "last_updated",
                "Status": "status",
                "Type": "type",
                "Early_Departure": "early_departure",
            }, inplace=True)
            
            # Drop duplicates and clean missing values
            df.drop_duplicates(inplace=True)
            df.dropna(subset=['employee_id', 'attendance_date'], inplace=True)
            
            # Convert data types
            df['employee_id'] = pd.to_numeric(df['employee_id'], errors='coerce').fillna(0).astype(int)
            df['attendance_date'] = pd.to_datetime(df['attendance_date'], errors='coerce').dt.date
            df['last_updated'] = pd.to_datetime(df['last_updated'], errors='coerce').dt.time.replace({pd.NaT: None})
            df['early_departure'] = df['early_departure'].apply(lambda x: str(x).upper() == 'TRUE')

            # Bulk insert into database
            records = [
                AttendanceMaster(
                    employee_id=row['employee_id'],
                    employee_name=row['employee_name'],
                    line=row['line'],
                    factory=row['factory'],
                    floor=row['floor'],
                    section=row['section'],
                    attendance_date=row['attendance_date'],
                    last_updated=row['last_updated'],
                    status=row['status'],
                    type=row['type'],
                    early_departure=row['early_departure']
                ) for row in df.to_dict('records')
            ]

            AttendanceMaster.objects.all().delete()
    
            AttendanceMaster.objects.bulk_create(records, ignore_conflicts=True)

            return success_response(message= 'File uploaded and data saved successfully', status=201)
        
        except Exception as e:
            return error_response(error= str(e), status=400)

    return error_response(error= 'Invalid request', status=400)


@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def add_local_holiday_calender(request):
    try:
        file = request.FILES.get('file')
        if not file:
            return error_response(error='File is required', status=status.HTTP_400_BAD_REQUEST)
        
        # Check the file type and read data accordingly
        if file.name.endswith('.csv'):
            holiday_df = pd.read_csv(file)
        elif file.name.endswith('.xlsx'):
            holiday_df = pd.read_excel(file)
        else:
            return error_response(error= 'Unsupported file format.', status=status.HTTP_400_BAD_REQUEST)
        
        holiday_df.columns = holiday_df.columns.str.lower()  # Convert all column names to lowercase for consistency

        holiday_df['date'] = pd.to_datetime(holiday_df['date'])
        # Extract day, month, year and week from the date
        holiday_df['day'] = holiday_df['date'].dt.day # type: ignore
        holiday_df['month'] = holiday_df['date'].dt.month # type: ignore
        holiday_df['year'] = holiday_df['date'].dt.year # type: ignore
        holiday_df['week'] = holiday_df['date'].dt.isocalendar().week  # ISO week number (1-53) # type: ignore
            
        # Process and save the data
        records = [
            LocalHolidayCalendar(
                date=row['date'],
                month=int(row['month']),
                year=int(row['year']),
                day=int(row['day']),
                week=int(row['week']),
                event=row['event'],
                leave_type=row.get('leave_type', 'full')
            ) for row in holiday_df.to_dict('records')
        ]
        truncate_table(LocalHolidayCalendar)
        LocalHolidayCalendar.objects.bulk_create(records)

        return success_response(message="Local Holiday Calender added successfully.", status=status.HTTP_200_OK)
    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def add_payable_working_days(request):
    try:
        # file = request.FILES.get('file')
        # if not file:
        #     return error_response(error='File is required', status=status.HTTP_400_BAD_REQUEST)
        
        # # Check the file type and read data accordingly
        # if file.name.endswith('.csv'):
        #     holiday_df = pd.read_csv(file)
        # elif file.name.endswith('.xlsx'):
        #     holiday_df = pd.read_excel(file)
        # else:
        #     return error_response(error= 'Unsupported file format.', status=status.HTTP_400_BAD_REQUEST)
        
        # holiday_df.columns = holiday_df.columns.str.lower()  # Convert all column names to lowercase for consistency

        # Create the DataFrame
        holiday_df = pd.DataFrame({
            'date': ["21-12-2024", "21-06-2025"]
        })

        holiday_df['date'] = pd.to_datetime(holiday_df['date'])
        # Extract day, month, year and week from the date
        holiday_df['day'] = holiday_df['date'].dt.day # type: ignore
        holiday_df['month'] = holiday_df['date'].dt.month # type: ignore
        holiday_df['year'] = holiday_df['date'].dt.year # type: ignore
        holiday_df['week'] = holiday_df['date'].dt.isocalendar().week  # ISO week number (1-53) # type: ignore
        logger.info(holiday_df)
            
        # Process and save the data
        records = [
            PayableWorkingDays(
                date=row['date'],
                month=int(row['month']),
                year=int(row['year']),
                day=int(row['day']),
                week=int(row['week']),
            ) for row in holiday_df.to_dict('records')
        ]
        truncate_table(PayableWorkingDays)
        PayableWorkingDays.objects.bulk_create(records)

        return success_response(message="Payable Working days added successfully.", status=status.HTTP_200_OK)
    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)
