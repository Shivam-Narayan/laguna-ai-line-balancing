import logging
import pandas as pd

from django.http import HttpResponse

from datetime import datetime
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes, authentication_classes

from .serializers import CalendarSerializer
from apps.manning_sheet.models import ActiveEmployees
from apps.absenteeism.utils import send_email, convert_to_excel_data, is_allowed_working_day
from apps.accounts.authentication import MultiSessionTokenAuthentication
from apps.accounts.utils.response_handlers import success_response, error_response
from .models import LocalHolidayCalendar, HistoricalWeather, EmployeeMaster, AttendanceMaster, PayableWorkingDays

logger = logging.getLogger('general')




@api_view(['GET'])
def get_calendar(request):
    calendar = LocalHolidayCalendar.objects.all()
    if not calendar:
        return Response({'message': 'No data to display'}, status=status.HTTP_200_OK)
    serializer = CalendarSerializer(calendar, many=True)
    return Response(serializer.data)



        

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
            for _, row in data.iterrows():
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
            return error_response(error= f"som eerror {str(e)}", status=500)

    return error_response(error= 'Invalid request method', status=405)




# Helper Functions for load_plan_upload
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




# operators data fetching through Employee master table
@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def operators_data(request):
    try:
        line_no = request.query_params.get('line', ' ').strip()
       
        if not line_no:
            return error_response(
                error='Line are required.',
                status=status.HTTP_400_BAD_REQUEST
            )
       
        # validating the line number 
        valid_lines = ['line 1', 'line 2', 'line 3', 'line 4', 'line 5', 'line 6', 'line 7', 'line 8', 'line 9', 'line 10', 'all'] 
        if line_no.lower() not in valid_lines:
            return error_response(
                error='Enter valid line number(Valid Formats: "Line 1" or "line 3" or "LINE 5" or "all")',
                status=status.HTTP_400_BAD_REQUEST
            )
                   
        # Query all the data from the Employee Master table
        employee_queryset = EmployeeMaster.objects.all()
        
        # Filtering based on the line
        if line_no.lower() != 'all':
            employee_queryset = employee_queryset.filter(line__iexact=line_no.lower())
       
        # Handling the case where no record is present in the table
        if not employee_queryset.exists():
            return error_response(
                error=f'No data found for {line_no}',
                status=status.HTTP_200_OK
            )
       
        # converting the queryset to a list of dictionaries with specified fields
        data = list(employee_queryset.values())

        return success_response(
            message=f'Data for {line_no} fetched successfully.',
            data=data,
            status=status.HTTP_200_OK
        )
   
    except EmployeeMaster.DoesNotExist:
        return error_response(
            error="Employee Master Model does not exist.",
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return error_response(
            error=f"An error occured while fetching the data, {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# export operators data through csv
@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def export_operators_data(request):
    try:
        line_no = request.query_params.get('line', '').strip()

        if not line_no:
            return error_response(
                error='Line is required.',
                status=status.HTTP_400_BAD_REQUEST
            )

        valid_lines = ['line 1', 'line 2', 'line 3', 'line 4', 'line 5', 'line 6', 'line 7', 'line 8', 'line 9', 'line 10', 'all']
        if line_no.lower() not in valid_lines:
            return error_response(
                error='Enter valid line number (Valid Formats: "Line 1" or "line 3" or "LINE 5" or "all")',
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get the actual field names from the EmployeeMaster model
        fields = [field.name for field in EmployeeMaster._meta.get_fields()]
        
        if not fields:
            return error_response(
                error='No fields found in the Employee Master Table',
                status=status.HTTP_404_NOT_FOUND
            )
        
        employee_queryset = EmployeeMaster.objects.all()
        
        if line_no.lower() != 'all':
            employee_queryset = employee_queryset.filter(line__iexact=line_no.lower())

        if not employee_queryset.exists():
            return error_response(
                error=f'No data found for {line_no}',
                status=status.HTTP_200_OK
            )

        # Column name mapping (old_name -> new_name)
        column_mapping = {
            'emp_code': 'Employee Code',
            'emp_name': 'Employee Name',
            'date_of_joining': 'Date of Joining',
            'line': 'Line',
            'section': 'Section',
            'designation': 'Designation',
            'status': 'Status',
            'primary': 'Primary',
            'secondary': 'Secondary',
        }

        # Fetch data and rename columns
        data = [
            {column_mapping.get(key, key): value for key, value in record.items()}
            for record in employee_queryset.values(*fields)
        ]

        excel_data = convert_to_excel_data(data, "Operators Data")
        
        response = HttpResponse(excel_data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="OperatorsData_{line_no}.xlsx"'
        
        return response
    
    except EmployeeMaster.DoesNotExist:
        return error_response(
            error="Employee Master Model does not exist.",
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return error_response(
            error=f"An error occurred while exporting the data, {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# export operators data through email
@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def export_operators_data_email(request):
    try:
        recipient_email = request.query_params.get('email', '').strip()
        line_no = request.query_params.get('line', '').strip()

        if not recipient_email:
            return error_response(
                error='Recipient email is required.',
                status=status.HTTP_400_BAD_REQUEST
            )

        if not line_no:
            return error_response(
                error='Line is required.',
                status=status.HTTP_400_BAD_REQUEST
            )

        valid_lines = ['line 1', 'line 2', 'line 3', 'line 4', 'line 5', 'line 6', 'line 7', 'line 8', 'line 9', 'line 10', 'all']  
        if line_no.lower() not in valid_lines:
            return error_response(
                error='Enter valid line number (Valid Formats: "Line 1" or "line 3" or "LINE 5" or "all")',
                status=status.HTTP_400_BAD_REQUEST
            )
        
        fields = [field.name for field in EmployeeMaster._meta.get_fields()]
        
        if not fields:
            return error_response(
                error='No fields found in the Employee Master Table',
                status=status.HTTP_404_NOT_FOUND
            )

        employee_queryset = EmployeeMaster.objects.all()
        
        if line_no.lower() != 'all':
            employee_queryset = employee_queryset.filter(line__iexact=line_no.lower())

        if not employee_queryset.exists():
            return error_response(
                error=f'No data found for {line_no}',
                status=status.HTTP_200_OK
            )
        
        # Column name mapping (old_name -> new_name)
        column_mapping = {
            'emp_code': 'Employee Code',
            'emp_name': 'Employee Name',
            'date_of_joining': 'Date of Joining',
            'line': 'Line',
            'section': 'Section',
            'designation': 'Designation',
            'status': 'Status',
            'primary': 'Primary',
            'secondary': 'Secondary',
        }

        # Fetch data and rename columns
        data = [
            {column_mapping.get(key, key): value for key, value in record.items()}
            for record in employee_queryset.values(*fields)
        ]
        
        excel_data = convert_to_excel_data(data, "Operators Data")

        # Send email with CSV file as an attachment
        subject = f"Operators Data List for {line_no}"
        file_name = f'OperatorsData_{line_no}.xlsx'
        data_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        email_sent = send_email(recipient_email, excel_data, subject, data_type, file_name=file_name)

        if email_sent:
            return Response({"message": "Email sent successfully."}, status=status.HTTP_200_OK)
        else:
            return error_response(
                error="Failed to send email.",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    except EmployeeMaster.DoesNotExist:
        return error_response(
            error="Employee Master Model does not exist.",
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return error_response(
            error=f"An error occurred while exporting the data, {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        
@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
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
            df['employee_id'] = df['employee_id'].astype(int)
            df['attendance_date'] = pd.to_datetime(df['attendance_date']).dt.date
            df['last_updated'] = pd.to_datetime(df['last_updated']).dt.time
            df['early_departure'] = df['early_departure'].apply(lambda x: x.upper() == 'TRUE')

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
                ) for _, row in df.iterrows()
            ]

            AttendanceMaster.objects.all().delete()
    
            AttendanceMaster.objects.bulk_create(records, ignore_conflicts=True)

            return success_response(message= 'File uploaded and data saved successfully', status=201)
        
        except Exception as e:
            return error_response(error= str(e), status=400)

    return error_response(error= 'Invalid request', status=400)

from apps.manning_sheet.models import EMPFact
from backend_laguna.utils import truncate_table


@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def generate_employee_master(request):
    try:
        return run_generate_employee_master()  # Call the function without needing a request
    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)



def run_generate_employee_master():
    try:
        # Get today's date
        current_date = datetime.now().date()
        # Check if the filter date is a working day and not a holiday
        isWorkingDay, reason = is_allowed_working_day(current_date)
        if not isWorkingDay:
            return error_response(error=f'Skipping for {current_date} as it is {reason}', status=status.HTTP_400_BAD_REQUEST)

        logger.info(f"*******************************************************************")
        logger.info(f"Running Employee Master generation at {str(datetime.now())} hours!")
        # df_active_employees = pd.read_csv('csv_files/Active_Employees.csv')
        active_employees_queryset = ActiveEmployees.objects.all().values()
        df_active_employees = pd.DataFrame(list(active_employees_queryset))
        df_active_employees.rename(columns={'employee_id': 'Emp No', 'employee_name': 'Employee name', 'line': 'Line', 'section': 'Section', 'designation': 'Designation'}, inplace=True)

        # Fetch data from Django model
        queryset = EMPFact.objects.all().values()  # Convert QuerySet to a list of dictionaries

        # Convert QuerySet to Pandas DataFrame
        df_emp_fact = pd.DataFrame(list(queryset))

        # Convert Emp No and EMPLOYEE ID to numeric
        # df_active_employees["Emp No"] = pd.to_numeric(df_active_employees["Emp No"], errors="coerce")
        df_emp_fact["employee_id"] = pd.to_numeric(df_emp_fact["employee_id"], errors="coerce")

        # Converting values to lower case
        # df_active_employees["Department"] = df_active_employees["Department"].str.lower() # Ensure department is lowercase
        df_emp_fact["section"] = df_emp_fact["section"].str.lower()  # Ensure section is lowercase
        df_emp_fact["line"] = df_emp_fact["line"].str.lower()  # Ensure line is lowercase

        # ✅ Split "Department" into "Line" and "Section"
        # df_active_employees[["Line", "Section"]] = df_active_employees["Department"].str.extract(r"(?i)^(line \d+)\s*(.*)$", expand=True)


        # ✅ Merge using multiple conditions with lowercase values
        df_merged = df_active_employees.merge(
            df_emp_fact,
            left_on=["Emp No"],
            right_on=["employee_id"],
            how="left"
        )

        # Normalize operation type to lowercase
        df_merged["type"] = df_merged["type"].str.lower()

        # Assign primary and secondary operations
        df_merged["primary"] = df_merged["operation"].where(df_merged["type"] == "primary", "-")
        df_merged["secondary"] = df_merged["operation"].where(df_merged["type"] == "secondary", "-")

        # Rename and select relevant columns
        df_grouped = df_merged[["Emp No", "Employee name", "Line", "Section", "Designation", "primary", "secondary"]].copy()

        df_grouped.rename(columns={
            "Emp No": "emp_code",
            "Employee name": "name",
            "Line": "line",
            "Designation": "designation",
            "Section": "section"
        }, inplace=True)

        # Add a default status column
        df_grouped["status"] = "active"


        # Convert columns to title case
        df_grouped["line"] = df_grouped["line"].str.title()
        df_grouped["section"] = df_grouped["section"].str.title()

        # Group and aggregate primary & secondary operations
        df_employee_master = df_grouped.groupby(
            ["emp_code", "name", "line", "designation", "section", "status"],
            as_index=False
        ).agg({
            "primary": lambda x: ", ".join(filter(lambda v: v != "-", x)),  
            "secondary": lambda x: ", ".join(filter(lambda v: v != "-", x))  
        })

        # Replace empty values with "-"
        df_employee_master[["primary", "secondary"]] = df_employee_master[["primary", "secondary"]].replace("", "-")

        current_date = datetime.now().strftime("%Y-%m-%d")
        # Convert date format to YYYY-MM-DD
        df_employee_master["date_of_joining"] = current_date
        df_employee_master['designation'] = df_employee_master['designation'].str.lower()

        # Process and save the data
        records = [
            EmployeeMaster(
                emp_code=row['emp_code'],
                emp_name=row['name'],
                date_of_joining=row['date_of_joining'] if row['date_of_joining'] else None,
                line=row.get('line', '').upper(),  # ✅ Convert to uppercase before adding,
                section=row.get('section', ''),
                designation=row['designation'],
                status=row['status'] if row['status'] in ['active', 'inactive'] else 'active',
                primary=row['primary'],
                secondary=row['secondary']
            ) for _, row in df_employee_master.iterrows()
        ]
        truncate_table(EmployeeMaster)
        EmployeeMaster.objects.bulk_create(records)

        logger.info(f"Data saved successfully at {str(datetime.now())} hours!")
        logger.info(f"***************************************************\n\n")

        return success_response(message="Employee Master data is generated successfully.", status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error in run_generate_employee_master: {str(e)} at {datetime.now()} hours!", exc_info=True)
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)
    


@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
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
        holiday_df['day'] = holiday_df['date'].dt.day
        holiday_df['month'] = holiday_df['date'].dt.month
        holiday_df['year'] = holiday_df['date'].dt.year
        holiday_df['week'] = holiday_df['date'].dt.isocalendar().week  # ISO week number (1-53)
            
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
            ) for _, row in holiday_df.iterrows()
        ]
        truncate_table(LocalHolidayCalendar)
        LocalHolidayCalendar.objects.bulk_create(records)

        return success_response(message="Local Holiday Calender added successfully.", status=status.HTTP_200_OK)
    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)
    


@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
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
        holiday_df['day'] = holiday_df['date'].dt.day
        holiday_df['month'] = holiday_df['date'].dt.month
        holiday_df['year'] = holiday_df['date'].dt.year
        holiday_df['week'] = holiday_df['date'].dt.isocalendar().week  # ISO week number (1-53)
        print(holiday_df)
            
        # Process and save the data
        records = [
            PayableWorkingDays(
                date=row['date'],
                month=int(row['month']),
                year=int(row['year']),
                day=int(row['day']),
                week=int(row['week']),
            ) for _, row in holiday_df.iterrows()
        ]
        truncate_table(PayableWorkingDays)
        PayableWorkingDays.objects.bulk_create(records)

        return success_response(message="Payable Working days added successfully.", status=status.HTTP_200_OK)
    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)
    
