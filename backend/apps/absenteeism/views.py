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
from .prediction import model_prediction
from backend_laguna.utils import truncate_table
from apps.manning_sheet.views import NOTIFICATION_DISPLAY_TITLE
from apps.manning_sheet.models import ManningSheetData, LoadingPlan
from apps.accounts.authentication import MultiSessionTokenAuthentication
from .models import Absenteeism, PredictionData, AbsenteeismPrediction
from apps.manning_sheet.utils import create_bulk_push_notifications, custom_round
from apps.accounts.utils.response_handlers import error_response, success_response
from apps.dataEngine.models import LocalHolidayCalendar, EmployeeMaster, AttendanceMaster
from .absenteeism_percentage import calculate_line_percentages, get_working_days_around_date
from .utils import generate_csv, send_email, generate_prediction_data, convert_number, update_sections, merge_duplicates, is_allowed_working_day, sum_section_counts, normalize_sections, write_absenteeism_data_to_csv, export_absenteeism_predictions_excel

logger = logging.getLogger('general')
 
prediction_response = {}

@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def export_data(request):
    try:
        # Fetching data from the database dynamically
        fields = [field.name for field in LocalHolidayCalendar._meta.get_fields()]
        queryset = LocalHolidayCalendar.objects.all()
        data = list(queryset.values(*fields))

        # Check if data exists
        if not data:
            return error_response(
                error="No data found to export.",
                status=status.HTTP_404_NOT_FOUND
            )

        # Create DataFrame from recieved data
        try:
            df = pd.DataFrame(data)
        except Exception as e:
            return error_response(
                error=f"Error creating DataFrame: {str(e)}",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Generate and return the CSV file as an HttpResponse
        try:
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="absent.csv"'
            response['Success-Message'] = 'Absent CSV file generated successfully.'
            df.to_csv(response, index=False)
            return response 
        except Exception as e:
            return error_response(
                error=f"Error generating CSV file: {str(e)}",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    except Exception as e:
        # exception handler for unexpected errors
        return error_response(
            error=f"An unexpected error occurred: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
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
            data = pd.read_csv(file, header=1)
        elif file.name.endswith('.xlsx'):
            data = pd.read_excel(file, header=1)
        else:
            return error_response(error= 'Unsupported file format.', status=status.HTTP_400_BAD_REQUEST)

        # Rename columns for dates
        month_number = list(calendar.month_abbr).index(month[:3])
        _, endDate = calendar.monthrange(year, month_number)
        columns_to_rename = {i: f'{i:02d}-{month}-{year}' for i in range(1, endDate + 1)}
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
        if melted_data['Date'].isnull().any():
            return error_response(error='Invalid date values found in the data.', status=status.HTTP_400_BAD_REQUEST)
        
        melted_data[['P', 'WO', 'H', 'L', 'Ab', 'DP', 'OT1']] = melted_data[['P', 'WO', 'H', 'L', 'Ab', 'DP', 'OT1']].fillna(0)


        # Validate data before creating objects
        absenteeism_objects = []
        for _, row in melted_data.iterrows():
            if pd.isnull(row['Empcode']) or row['Empcode'] == '':
                # Skip rows where 'Empcode' is empty or NaN
                continue

            try:
                absenteeism_objects.append(Absenteeism(
                    empcode=row['Empcode'],
                    name=row['Name'],
                    department=row['Department'],
                    doj=row['DOJ'],  # Can be None
                    date=row['Date'],  # Mandatory
                    attendance=row['Attendance'],
                    P=row['P'],
                    WO=row['WO'],
                    H=row['H'],
                    L=row['L'],
                    Ab=row['Ab'],
                    DP=row['DP'],
                    OT1=row['OT1']
                ))
            except Exception as e:
                print(f"Error creating object for row: {row}, Error: {str(e)}")

        # Save to database
        if absenteeism_objects:
            try:
                Absenteeism.objects.bulk_create(absenteeism_objects)
                return success_response(data= f'Data successfully uploaded {month} {year} and saved.', status=status.HTTP_201_CREATED)
            except Exception as e:
                print(f"Error during bulk_create: {str(e)}")
                return error_response(error=f"Error saving data to the database: {str(e)}", status=status.HTTP_400_BAD_REQUEST)
        else:
            return error_response(error='No valid data to save. All rows had missing Empcode.', status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        return error_response(error=f'Error processing the data: {str(e)}', status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def export_absenteeism_data(request):
    try:
        # Fetch all fields dynamically from the model
        fields = [field.name for field in Absenteeism._meta.get_fields()]
        queryset = Absenteeism.objects.all()
        data = list(queryset.values(*fields))

        # Check if data exists
        if not data:
            return error_response(
                error= "No data found to export.",
                status=status.HTTP_404_NOT_FOUND
            )

        # Create a DataFrame
        try:
            df = pd.DataFrame(data)
        except Exception as e:
            return error_response(
                error= f"Error creating DataFrame: {str(e)}",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Generate CSV response
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="absent.csv"'
        df.to_csv(response, index=False)
        return response

    except Exception as e:
        # Handle unexpected errors
        return error_response(
            error= f"An unexpected error occurred: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    

@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def absenteeism_data_preprocessing(request):
    try:
        # Filter records with "LINE" in the department
        absenteeism_records = Absenteeism.objects.filter(department__icontains="LINE")

        prediction_data_objects = []
        batch_size = 200  # Set a batch size (adjust based on your DB performance)

        truncate_table(PredictionData)

        for record in absenteeism_records:
            try:
                match = re.match(r"(LINE\s*\d+)\s+(.*)", record.department)
                if match:
                    department = match.group(1).replace(" ", "")
                    department = re.sub(r"LINE(\d+)", r"LINE \1", department)
                    section = match.group(2)
                    section = section.replace(" ", "")
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

                # When batch size is reached, insert data and clear the list
                if len(prediction_data_objects) >= batch_size:
                    with transaction.atomic():
                        PredictionData.objects.bulk_create(prediction_data_objects, batch_size=batch_size)
                    prediction_data_objects.clear()  # Clear processed records

            except Exception:
                continue  # Skip problematic records silently

        # Insert remaining records
        if prediction_data_objects:
            with transaction.atomic():
                PredictionData.objects.bulk_create(prediction_data_objects, batch_size=batch_size)

        return success_response(
            data="Records processed and saved successfully."
        )

    except Exception as e:
        return error_response(
            error=f"An unexpected error occurred: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    

# Export the csv file through email
@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def send_csv_via_email(request):
    try:
        # Getting the email from the request body
        email = request.data.get("email")
        if not email:
            return error_response(
                error="Email address is required.",
                status=status.HTTP_400_BAD_REQUEST
            )

        # Generate the CSV data in memory in utils function
        csv_data = generate_csv()

        if not csv_data:
            return error_response(
                error="No data found to export.",
                status=status.HTTP_404_NOT_FOUND
            )

        # Sending email with CSV as attachment
        email_subject = "Download Absenteeism CSV File"
        file_name="absent.csv"
        email_body = send_email(email, csv_data, email_subject, file_name=file_name)

        if not email_body:
            return error_response(
                error="Error sending email, Invalid email address.",
                status=status.HTTP_404_NOT_FOUND
            )

        return success_response(
            message=f"Email sent successfully to {email}.",
            data={"message": "CSV file attached to the email."}
        )

    except Exception as e:
        return error_response(
            error=f"An unexpected error occurred: {str(e)}",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        
        
@api_view(['POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])        
def absenteeism_prediction(request):
    if request.method == 'POST':  
        viaAPI = True
        return run_absenteeism_prediction(viaAPI)
    return error_response(error='Invalid request method.', status=405)



# Function to generate the Absenteeism Prediction and can be used in a view as well as in a scheduler
def run_absenteeism_prediction(viaAPI):
    try:
        # Get today's date
        current_date = datetime.now().date()
        # Check if the filter date is a working day and not a holiday
        isWorkingDay, reason = is_allowed_working_day(current_date)
        if not isWorkingDay:
            return error_response(error=f'Skipping for {current_date} as it is {reason}', status=status.HTTP_400_BAD_REQUEST)

        current_time = datetime.now()
        if not viaAPI:
            logger.info(f"*******************************************************************")
            logger.info(f"Running Absenteeism generation at {str(current_time)} hours!")

        # Get the current script directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        models_dir = os.path.join(current_dir, "models")

        # Check if "models" directory exists, if not, create it
        if not os.path.exists(models_dir):
            os.makedirs(models_dir)

        # Get today's date
        today = date.today()

        consolidated_df = model_prediction()
        
        # Convert 'datetime' column to date format
        consolidated_df['datetime'] = pd.to_datetime(consolidated_df['datetime']).dt.date

        # Define max allowed dates for each forecast period
        forecast_limits = {
            7: today + timedelta(days=7),
            15: today + timedelta(days=15),
            30: today + timedelta(days=30),
            45: today + timedelta(days=45),
            60: today + timedelta(days=60),
        }

        # # Apply filtering
        # consolidated_df = consolidated_df[
        #     consolidated_df.apply(lambda row: row['datetime'] <= forecast_limits.get(row['forecast_period'], today), axis=1)
        # ]

        # And ensure the filtering includes today
        consolidated_df = consolidated_df[
            consolidated_df.apply(
                lambda row: (row['datetime'] >= today) & 
                        (row['datetime'] <= forecast_limits.get(row['forecast_period'], today)), 
                axis=1
            )
        ]
        
        # **Step 1: Batch delete old records**
        batch_size = 5000  # Adjust as needed
        while True:
            ids_to_delete = list(AbsenteeismPrediction.objects.values_list('id', flat=True)[:batch_size])
            if not ids_to_delete:
                break
            AbsenteeismPrediction.objects.filter(id__in=ids_to_delete).delete()

        truncate_table(AbsenteeismPrediction)
        # Step 2: Prepare batch insertion
        batch_size = 1000
        prediction_data_objects = []

        consolidated_df.dropna(inplace=True)

        for _, row in consolidated_df.iterrows():
            prediction_data_objects.append(
                AbsenteeismPrediction(
                    datetime=row['datetime'],
                    day_of_week=row['day_of_week'],
                    predicted_absent_count=int(row['Predicted_Absent_Count']),
                    line=row['Line'],
                    section=row['Section'].strip(),
                    forecast_period=row['forecast_period'],
                    historical_mean=row['historical_mean'],
                    historical_std=row['historical_std'],
                    deviation_from_mean=row['deviation_from_mean'],
                )
            )

            if len(prediction_data_objects) >= batch_size:
                with transaction.atomic():
                    AbsenteeismPrediction.objects.bulk_create(prediction_data_objects, batch_size=batch_size)
                prediction_data_objects.clear()

        # Insert remaining records
        if prediction_data_objects:
            with transaction.atomic():
                AbsenteeismPrediction.objects.bulk_create(prediction_data_objects, batch_size=batch_size)

        if not viaAPI:
            notification_type="absenteeism_prediction"
            create_bulk_push_notifications(
                notification_type=notification_type,
                title=NOTIFICATION_DISPLAY_TITLE.get(notification_type, "Unknown"),
                message=f"Kindly review the Absenteeism Prediction data generated at {str(current_time.strftime('%B %d, %Y %I:%M %p'))}",
                users=User.objects.filter(status=True),  # only active users
            )
            logger.info(f"Data saved successfully at {str(datetime.now())} hours!")
            logger.info(f"***************************************************\n\n")

        return success_response(message='Data saved successfully.')

    except Exception as e:
        logger.error(f"Error in run_absenteeism_prediction: {str(e)} at {datetime.now()} hours!", exc_info=True)
        return error_response(error=str(e), status=500)


@api_view(['GET', 'POST'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def absenteeism_prediction_data(request):
    try:
        line_no = request.query_params.get('line', '').strip()
        forecast_period = request.query_params.get('forecast_period', '').strip()
        get_all = request.query_params.get('get_all', 'false').strip().lower() == 'true'
        
        if request.method == 'POST' and get_all:
            response = export_absenteeism_predictions_excel()
            return response

        if not line_no or not forecast_period:
            return error_response(error='"line" and "forecast_period" are required.', status=status.HTTP_400_BAD_REQUEST)

        try:
            forecast_period = int(forecast_period)
        except ValueError:
            return error_response(error='"forecast_period" must be an integer.', status=status.HTTP_400_BAD_REQUEST)

        prediction_response = prepare_prediction_data(line_no, forecast_period)

        if prediction_response.data['status'] == 'error':
            return prediction_response

        if request.method == 'GET':
            updatedResponse={
                'data': prediction_response.data['data'],
                'message': "Data fetched successfully",
                'status': 'success'
            }
        
            # Serialize and compress
            raw_json = json.dumps(updatedResponse)
            data = gzip.compress(smart_bytes(raw_json))
            # Return compressed response
            return HttpResponse(
                data,
                content_type='application/json',
                status=status.HTTP_200_OK,
                headers={
                    'Content-Encoding': 'gzip',
                    'Vary': 'Accept-Encoding'
                }
            )
            # return success_response(message='Data fetched successfully', data=prediction_response.data['data'], status=status.HTTP_200_OK)

        elif request.method == 'POST':
            excel_data = generate_prediction_data(prediction_response.data['data'])
            export_type = request.query_params.get('type', '').lower()
            if not export_type:
                return error_response(error='Type (excel/email) of data to export not provided', status=status.HTTP_400_BAD_REQUEST)

            if export_type == 'excel':
                response = HttpResponse(excel_data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                response['Content-Disposition'] = f'attachment; filename="Prediction_Data_{line_no}_{forecast_period}.xlsx"'
                return response

            elif export_type == 'email':
                email = request.query_params.get("email")
                if not email:
                    return error_response(error='Email not provided', status=status.HTTP_400_BAD_REQUEST)

                subject = "Download Absenteeism File"
                file_name = f"Prediction_Data_{line_no}_{forecast_period}.xlsx"
                email_sent = send_email(email, excel_data, subject, "text/excel", file_name)

                if not email_sent:
                    return error_response(error="Error sending email. Invalid email address.", status=status.HTTP_404_NOT_FOUND)

                return success_response(message=f"Email sent successfully to {email}.", data={"message": "File attached to the email."})

            return error_response(error='Type should be either "excel" or "email"', status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        return error_response(error=f"Unknown error: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def prepare_prediction_data(line_no, forecast_period, summation=False):
    try:
        line_no_upper = line_no.upper()
        line_no_lower = line_no.lower()

        valid_lines = [f"line {i}" for i in range(1, 11)] + ['all']
        if line_no_lower not in valid_lines:
            return None, None, error_response(error='Invalid line number.', status=status.HTTP_400_BAD_REQUEST)

        today = date.today()
        filter_date = today + timedelta(days=forecast_period)

        employee_filter = Q()
        if line_no_lower != 'all':
            employee_filter = Q(line=line_no_upper)

        total_emp_count = EmployeeMaster.objects.filter(employee_filter).count()
        if total_emp_count == 0:
            return None, None, error_response(error='No employees found.', status=status.HTTP_404_NOT_FOUND)

        absenteeism_filter = {'forecast_period': forecast_period}
        loading_plan_filter = {'planned_dates': filter_date}
        manning_sheet_filter = {'planned_dates': filter_date, 'machinist': True}
        employee_master_filters = {'designation': 'machinist'}

        if line_no_lower != 'all':
            absenteeism_filter['line'] = line_no_upper
            loading_plan_filter['line'] = line_no.title()
            manning_sheet_filter['line'] = line_no.title()
            employee_master_filters['line'] = line_no_upper

        if forecast_period == 1:
            absenteeism_filter['forecast_period'] = 7

            search_date = today
            while True:
                prediction_qs = AbsenteeismPrediction.objects.filter(
                    datetime=search_date,
                    forecast_period=7,
                    **({'line': line_no_upper} if line_no_lower != 'all' else {})
                ).exclude(section__iexact='nan')

                if prediction_qs.exists():
                    break
                search_date += timedelta(days=1)

            absenteeism_filter['datetime'] = search_date
            total_values = 1
        else:
            absenteeism_filter['datetime'] = filter_date
            prediction_qs = AbsenteeismPrediction.objects.filter(
                datetime=filter_date,
                forecast_period=forecast_period,
                **({'line': line_no_upper} if line_no_lower != 'all' else {})
            ).exclude(section__iexact='nan')
            total_values = prediction_qs.values('datetime').distinct().count()

        # Check if the filter date is a working day and not a holiday
        isWorkingDay, reason = is_allowed_working_day(filter_date)
        if not isWorkingDay:
            return error_response(error=f'No data found for {filter_date} as it is {reason}', status=status.HTTP_400_BAD_REQUEST)

        if not prediction_qs.exists():
            return None, None, error_response(error='No predictions found.', status=status.HTTP_404_NOT_FOUND)

        manning_sheet_qs = ManningSheetData.objects.filter(**manning_sheet_filter)
        manning_sheet_target = (
            manning_sheet_qs
            .values('section', 'code', 'style')
            .annotate(total_planned_qty=Sum('allocated_capacity'))
        )

        # Find the minimum value per section (including all matching records)
        min_entries = {}

        # for item in manning_sheet_target:
        #     section = item['section']
        #     qty = item['total_planned_qty']
        #     if section not in min_entries or qty < min_entries[section]['total_planned_qty']:
        #         min_entries[section] = item  # Keep only one item with min qty

        for item in manning_sheet_target:
            key = (item['section'], item['style'])  # tuple as key
            qty = item['total_planned_qty']
            
            if key not in min_entries or qty < min_entries[key]['total_planned_qty']:
                min_entries[key] = item  # Keep only one item with min qty

        # Convert result to list
        min_entries_list = list(min_entries.values())

        # Aggregate total_planned_qty per section
        section_summary = defaultdict(float)

        for item in min_entries_list:
            section_summary[item['section']] += item['total_planned_qty']

        # Convert to list of dicts if needed
        result = [{'section': sec, 'total_planned_qty': qty} for sec, qty in section_summary.items()]

        # OLD LOGIC
        # for item in manning_sheet_target:
        #     item['total_planned_qty'] = round(item['total_planned_qty'], 2)

        # # Process to compute sum of total_planned_qty per section
        # section_totals = defaultdict(lambda: {'sum_qty': 0, 'count': 0})

        # for record in manning_sheet_target:
        #     section = record['section']
        #     total_qty = record['total_planned_qty']

        #     section_totals[section]['sum_qty'] += total_qty
        #     section_totals[section]['count'] += 1

        # # Now, calculate the average per section and convert to array
        # section_avg_array = []

        # for section, data in section_totals.items():
        #     average_qty = round(data['sum_qty'] / data['count'], 2) if data['count'] else 0
        #     section_avg_array.append({'section': section, 'total_planned_qty': average_qty})

        section_data = (
            EmployeeMaster.objects
            .filter(employee_filter)
            .values('section')
            .annotate(count=Count('emp_code'))
        )
        total_operators = list(section_data)

        total_planned_qty = (
            LoadingPlan.objects
            .filter(**loading_plan_filter)
            .aggregate(total_planned_qty=Sum('planned_qty'))
        )['total_planned_qty'] or 0

        sections = ['Assembly', 'Cuff', 'Front', 'Back', 'Sleeve', 'Collar']
        production_target = [
            {'section': section, 'total_planned_qty': round(total_planned_qty, 2)}
            for section in sections
        ]

        total_gap_summary = (
            AbsenteeismPrediction.objects
            .filter(**absenteeism_filter)
            .exclude(section='nan')
            .values('section')
            .annotate(count=Sum('predicted_absent_count'))
        )

        gap_summary_normalized = [
            {
                'section': entry['section'].strip().capitalize(),
                'count': convert_number(entry['count'] / total_values)
            }
            for entry in total_gap_summary
        ]

        section_emp_count = {
            item['section']: item['count']
            for item in section_data
        }

        # Calculate absenteeism percentage by section
        absenteeism_percentage_by_section = {
            item['section']: round((item['count'] / section_emp_count[item['section']] * 100), 1) if total_emp_count else 0
            for item in gap_summary_normalized
        }

        total_operators_gap = merge_duplicates(gap_summary_normalized)
        total_sum = sum(item['count'] for item in total_operators_gap)
        absenteeism_percentage = round((total_sum / total_emp_count) * 100, 1) if total_emp_count else 0

        total_operators_supply = []
        for op in total_operators:
            gap = next((g for g in total_operators_gap if g['section'].lower() == op['section'].lower()), None)
            supply = op['count'] - gap['count'] if gap else op['count']
            total_operators_supply.append({'section': op['section'], 'count': supply})

        # Old Logic for predicted production
        # predicted_production = [
        #     {
        #         'section': item['section'],
        #         'total_planned_qty': round(item['total_planned_qty'] * (1 - absenteeism_percentage / 100), 2)
        #     }
        #     for item in production_target
        # ]
        
        # Calculate predicted production based on absenteeism percentage
        # predicted_production = [
        #     {
        #         'section': item['section'],
        #         'total_planned_qty': custom_round(item['total_planned_qty'] - (item['total_planned_qty'] * absenteeism_percentage_by_section.get(item['section'], 0) / 100))
        #     }
        #     for item in result
        # ]
        predicted_production = result # No longer need to subtract the absenteeism percentage so reassigning the variable

        # Special handling for "all" lines case
        if line_no_lower == "all":
            # First calculate individual line predictions
            all_line_predictions = {}
            required_machinists_all = []
            actual_machinists_all = []
            for line_index in range(1, 11):
                individual_line = f"line {line_index}"
                # Call recursively but don't return, just store results
                response_data = prepare_prediction_data(individual_line, forecast_period, summation=True)
                response_data = response_data.data
                
                # If the response is valid, extract the prediction data
                if isinstance(response_data, tuple):
                    continue  # Skip invalid responses
                
                if 'data' in response_data and 'Target data' in response_data['data']:
                    prediction_data = response_data['data']['Target data'][0]['predicted_production']
                    # Store by line number for aggregation
                    all_line_predictions[individual_line] = prediction_data
                    required_machinists_all.append(response_data['data']['required_machinists'])
                    actual_machinists_all.append(response_data['data']['actual_machinists'])

            required_machinists = sum_section_counts(required_machinists_all)
            actual_machinists = sum_section_counts(actual_machinists_all)
            # 1. Accumulate totals per section
            section_totals = defaultdict(float)

            for sections in all_line_predictions.values():
                for item in sections:
                    section_totals[item["section"]] += item["total_planned_qty"]

            # 2. Convert to desired list-of-dict format
            predicted_production = [{"section": section, "total_planned_qty": qty} for section, qty in section_totals.items()]


        if summation==False:
            # First, find if any non-Assembly section has zero quantity
            non_assembly_zero = any(
                item['section'] != 'Assembly' and item['total_planned_qty'] == 0.0
                for item in predicted_production
            )
            # If condition met, directly update Assembly section in same loop
            if non_assembly_zero:
                for item in predicted_production:
                    if item['section'] == 'Assembly':
                        item['total_planned_qty'] = 0.0
                        break


        production_data = [{
            "production_target": production_target,
            "predicted_production": predicted_production,
            "absenteeism_percentage_by_section": absenteeism_percentage_by_section
        }]

        total_operators_gap = update_sections(total_operators, total_operators_gap)

        # Reference order
        section_order = ['Assembly', 'Back', 'Collar', 'Cuff', 'Front', 'Sleeve']

        # Sort the lists using the section order
        total_operators = sorted(total_operators, key=lambda x: section_order.index(x['section']))
        total_operators_supply = sorted(total_operators_supply, key=lambda x: section_order.index(x['section']))
        total_operators_gap = sorted(total_operators_gap, key=lambda x: section_order.index(x['section']))


        # Added required machinists count and actual machinists count as a CR
        # Step 1: Group data by section and operation with unique (machine_type, operator_name, operator_id)
        grouped_result = defaultdict(lambda: defaultdict(set))
        
        grouped_data = manning_sheet_qs.only(
            'section', 'operation', 'machine_type', 'allocated_emp_name', 'allocated_emp_id'
        )

        for row in grouped_data:
            section = row.section or "Unknown"
            operation = row.operation or "Unknown"
            key = (row.machine_type, row.allocated_emp_name or "N/A", row.allocated_emp_id)
            grouped_result[section][operation].add(key)

        # Step 2: Flatten grouped data into required output structure
        grouped_machine_nonMachine_info = {}
        required_machinists = []

        for section, operations in grouped_result.items():
            machine_type_count = defaultdict(int)
            machinist_count = 0

            for entries in operations.values():
                for machine_type, operator_name, operator_id in entries:
                    machine_type_count[machine_type] += 1
                    machinist_count += 1

            # Store machine type counts
            grouped_machine_nonMachine_info[section] = dict(machine_type_count)

            # Store machinist count if needed
            required_machinists.append({
                'section': section,
                'count': machinist_count
            })

        # Fetch actual machinists count
        actual_machinists = list(
            EmployeeMaster.objects
            .filter(**employee_master_filters)
            .values('section')
            .annotate(count=Count('emp_code'))
            .order_by('section')
        )

        required_machinists = normalize_sections(required_machinists, section_order)
        actual_machinists = normalize_sections(actual_machinists, section_order)

        required_machinists = sorted(required_machinists, key=lambda x: section_order.index(x['section']))
        actual_machinists = sorted(actual_machinists, key=lambda x: section_order.index(x['section']))

        prediction_response = {
            'text': 'As per seasonal and cyclical trends and weather impact across last 3 years',
            'status': 'success',
            'line': line_no,
            'forecast_period': forecast_period,
            'total_employees': total_emp_count,
            'total_predicted_absenteeism': total_sum,
            'projected_attendance': total_emp_count - total_sum,
            'absenteeism_percentage': absenteeism_percentage,
            'total_operators': total_operators,
            'total_operators_supply': total_operators_supply,
            'total_operators_gap': total_operators_gap,
            'Target data': production_data,
            'required_machinists': required_machinists,
            'actual_machinists': actual_machinists,
        }

        return success_response(message='Data fetched successfully', data=prediction_response, status=status.HTTP_200_OK)

    except Exception as e:
        print(f"Error in prepare_prediction_data: {str(e)}")
        return error_response(error=f"Unknown error: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Function to send the absenteeism prediction data via email using APScheduler
def scheduler_prediction_data_email(line_no, forecast_period):
    try:
        # Get today's date
        current_date = datetime.now().date()
        # Check if the filter date is a working day and not a holiday
        isWorkingDay, reason = is_allowed_working_day(current_date)
        if not isWorkingDay:
            return error_response(error=f'Skipping for {current_date} as it is {reason}', status=status.HTTP_400_BAD_REQUEST)

        logger.info(f"*******************************************************************")
        logger.info(f"Running Prediction Data(Scheduler) at {str(datetime.now())} hours!")
        prediction_response = prepare_prediction_data(line_no, forecast_period)
        excel_data = generate_prediction_data(prediction_response.data['data'])

        if prediction_response.data['status'] == 'error':
            logger.info(f"Error ({prediction_response.status_code}) in preparing prediction data: {prediction_response.data['error']}")
            return prediction_response
        
        userEmails = list(User.objects.filter(send_mail=True, status=True).values_list('email', flat=True))

        subject = "Download Absenteeism File"
        file_name = f"Prediction_Data_{line_no}_{forecast_period}.xlsx"
        email_sent = send_email(userEmails, excel_data, subject, "text/excel", file_name)

        if not email_sent:
            logger.info(f"Error in sending email.")
            return error_response(error="Error in sending email.", status=status.HTTP_404_NOT_FOUND)

        return success_response(message=f"Email sent successfully to {userEmails}.", data={"message": "File attached to the email."})
    except Exception as e:
        print(f"Unexpected Error: {e}")
        return error_response(error=f"An unexpected error occurred ({e}).", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    



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



# anup code
@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def get_absenteeism_forecast(request):
    try:
        # Step 0: Validate forecast_period
        forecast_period = request.GET.get('forecast_period', 7)
        try:
            forecast_period = int(forecast_period)
            if forecast_period not in [1, 7, 30, 60]:
                return Response({"error": "Forecast period must be 1, 7, 30, or 60 days"}, status=400)
        except ValueError:
            return Response({"error": "Invalid forecast period. Must be an integer."}, status=400)

        line = request.GET.get('line', 'all').upper()
        if line != 'ALL' and not line.startswith('LINE '):
            return Response({"error": "Line parameter must be in format 'LINE X'"}, status=400)

        todays_date = datetime.now().date()
        target_date = todays_date + timedelta(days=forecast_period)

        # Step 1: Get employee counts by line
        active_employees = EmployeeMaster.objects.filter(status='active').only('line')
        if not active_employees:
            return Response({"error": "No active employee data found"}, status=500)

        emp_counts = defaultdict(int)
        for emp in active_employees:
            emp_line = emp.line.upper() if emp.line else "UNKNOWN"
            emp_counts[emp_line] += 1

        # Step 2: Precompute all required dates
        current_year = todays_date.year
        years_to_include = [current_year - i for i in range(1, 4)]

        all_needed_dates = set()
        year_to_dates = {}

        for year in years_to_include:
            hist_target_date = todays_date.replace(year=year) + timedelta(days=forecast_period)
            working_dates = get_working_days_around_date(hist_target_date)
            expanded_dates = set()

            for work_date in working_dates:
                all_needed_dates.add(work_date)
                for offset in range(-3, 4):
                    similar = work_date + timedelta(days=offset)
                    if similar.month == work_date.month:
                        all_needed_dates.add(similar)
                        expanded_dates.add(similar)

            year_to_dates[year] = working_dates  # We'll use this in results

        # Step 3: Fetch attendance data for only required dates
        attendance_query = PredictionData.objects.filter(date__in=list(all_needed_dates))
        if line != 'ALL':
            attendance_query = attendance_query.filter(department=line)
        if not attendance_query.exists():
            return Response({"error": f"No attendance data found for {line}"}, status=404)

        attendance_by_date = defaultdict(list)
        for record in attendance_query:
            attendance_by_date[record.date].append(record)

        # Step 4: Build historical results
        historical_data = {}
        for year, working_dates in year_to_dates.items():
            year_results = []

            for work_date in working_dates:
                data_for_date = attendance_by_date.get(work_date, [])

                if data_for_date:
                    percentage = calculate_line_percentages(data_for_date, emp_counts, line)
                else:
                    # fallback ±3 days in same month (already fetched)
                    similar_dates = [
                        d for d in (work_date + timedelta(days=offset) for offset in range(-3, 4))
                        if d.month == work_date.month
                    ]

                    similar_data = []
                    for sim_date in similar_dates:
                        similar_data.extend(attendance_by_date.get(sim_date, []))

                    percentage = calculate_line_percentages(similar_data, emp_counts, line) if similar_data else 0.0

                year_results.append({
                    "date": work_date.strftime('%Y-%m-%d'),
                    "percentage": percentage
                })

            if year_results:
                historical_data[str(year)] = year_results

        return Response({
            "forecast_period": forecast_period,
            "historical_data": historical_data,
            "line": line.lower(),
            "target_date": target_date.strftime('%Y-%m-%d'),
            "todays_date": todays_date.strftime('%Y-%m-%d')
        })

    except Exception as e:
        return Response({
            "status": "error",
            "message": f"An error occurred while generating the forecast: {str(e)}"
        }, status=500)
    



@api_view(['GET'])
@authentication_classes([MultiSessionTokenAuthentication])
@permission_classes([IsAuthenticated])
def get_today_absenteeism_report(request):
    try:
        viaAPI=True
        excel_data, file_name = run_absenteeism_report(viaAPI)  # Call the function without needing a request
        response = HttpResponse(excel_data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{file_name}"'
        return response
    except Exception as e:
        return error_response(error= str(e), status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# This function runs the absenteeism report generation and sends it via email or returns it as a response
def run_absenteeism_report(viaAPI):
    try:
        # Get today's date
        current_date = datetime.now().date()
        # Check if the filter date is a working day and not a holiday
        isWorkingDay, reason = is_allowed_working_day(current_date)
        if not isWorkingDay:
            return error_response(error=f'Skipping for {current_date} as it is {reason}', status=status.HTTP_400_BAD_REQUEST)

        if not viaAPI:
            logger.info(f"*******************************************************************")
            logger.info(f"Running Absenteeism Report generation at {str(datetime.now())} hours!")

        # Main execution
        today = date.today()
        formatted_date = today.strftime("%Y_%m_%d")
        file_name=f"Absenteeism_Report_{formatted_date}.csv"

        # Define the path to the absenteeism report file
        absenteeism_report = "exports/absenteeism_data.json"

        # Check if the absenteeism report file exists
        if not os.path.exists(absenteeism_report):
            return error_response(error='Absenteeism report not found.', status=status.HTTP_404_NOT_FOUND)

        # Load the absenteeism report data
        with open(absenteeism_report, "r") as f:
            allLineData = json.load(f)
        csv_buffer, file_name = write_absenteeism_data_to_csv(allLineData, file_name)

        if not viaAPI:
            # userEmails = list(User.objects.filter(send_mail=True, status=True).values_list('email', flat=True))
            userEmails = [
                # Laguna email ids
                "smithas@laguna-clothing.com", 
                "manish_sinha@laguna-clothing.com", 
                "sundaram_bm@laguna-clothing.com", 
                "sadashiv_naik@laguna-clothing.com", 
                "ravi.prakash@cieltextile.com", 
                "alok_kumar@laguna-clothing.com", 
                "naveen_kumar@laguna-clothing.com",

                # Ascendum email ids
                "amrendra.pathak@ascendum.com",
                # "vatsal.vohera@ascendum.com",
                "nayankumar.ghosh@ascendum.com",
                "raghavendra.nadgir@ascendum.com",
                "kavyashree.v@ascendum.com"
            ]

            subject = "Download Absenteeism Report"
            # email_sent = send_email(userEmails, excel_data, subject, "text/excel", file_name)
            email_sent = send_email(userEmails, csv_buffer, subject, "text/csv", file_name)

            if not email_sent:
                logger.info(f"Error in sending email.")
                return error_response(error="Error in sending email.", status=status.HTTP_404_NOT_FOUND)

            logger.info(f"Data sent via mail successfully at {str(datetime.now())} hours!")
            logger.info(f"***************************************************\n\n")

            return success_response(message="Absenteeism Report sent via mail successfully.", status=status.HTTP_200_OK)
        else:
            return csv_buffer, file_name
    except Exception as e:
        print(f"Error in run_absenteeism_report: {str(e)}")
        logger.error(f"Error in run_absenteeism_report: {str(e)} at {datetime.now()} hours!", exc_info=True)
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)


# This function writes absenteeism data to a json file for next working day
def save_absenteeism_report():
    try:
        next_day = datetime.now().date() + timedelta(days=1)  # Start from tomorrow
        # Keep incrementing until a valid working day is found
        while True:
            isWorkingDay, reason = is_allowed_working_day(next_day)
            if isWorkingDay:
                break
            next_day += timedelta(days=1)

        allLinesData = {
            'prediction_date': next_day.strftime("%Y-%m-%d"),
            'generated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        for line in range(1, 11):
            individual_line = f"line {line}"
            # Call recursively but don't return, just store results
            response_data = prepare_prediction_data(individual_line, 1)
            response_data = response_data.data

            # If the response is valid, extract the prediction data
            if isinstance(response_data, tuple):
                continue  # Skip invalid responses

            if 'data' in response_data:
                absenteeism_percentage = response_data['data'].get('absenteeism_percentage', 0)
                total_operators = response_data['data'].get('total_operators', [])
                total_employee_count = {item['section']: item['count'] for item in total_operators}
                total_operators_gap = response_data['data'].get('total_operators_gap', [])
                allLinesData[individual_line] = {
                    'predicted_absenteeism_percentage': absenteeism_percentage,
                    'total_employee_count': total_employee_count,
                    'predicted_absent_count': total_operators_gap
                }

        with open("exports/absenteeism_data.json", "w") as f:
            json.dump(allLinesData, f, indent=2)

        return success_response(message="Absenteeism Report saved successfully.", status=status.HTTP_200_OK)
    except Exception as e:
        print(f"Error in run_absenteeism_report: {str(e)}")
        logger.error(f"Error in run_absenteeism_report: {str(e)} at {datetime.now()} hours!", exc_info=True)
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)


# This function appends data to json file for today's absenteeism report for 12:45 PM
def fetch_absenteeism_report_data():
    try:
        today = date.today()

        # Define the path to the absenteeism report file
        absenteeism_report = "exports/absenteeism_data.json"

        # Check if the absenteeism report file exists
        if not os.path.exists(absenteeism_report):
            return error_response(error='Absenteeism report not found.', status=status.HTTP_404_NOT_FOUND)

        # Load the absenteeism report data
        with open(absenteeism_report, "r") as f:
            absenteeism_data = json.load(f)

        # Check if the data is empty
        if not absenteeism_data:
            return error_response(error='No absenteeism data found.', status=status.HTTP_404_NOT_FOUND)
        
        section_order = ['Assembly', 'Back', 'Collar', 'Cuff', 'Front', 'Sleeve']

        attendance_filter = {'attendance_date': today}

        for line in range(1, 11):
            individual_line = f"line {line}"
            attendance_filter['line'] = individual_line.title()

            attendance_summary = (
                AttendanceMaster.objects
                .filter(**attendance_filter)
                .exclude(section='nan')
                .values('section')
                .annotate(
                    present=Count(Case(When(status='P', then=1), output_field=IntegerField())),
                    absent=Count(Case(When(~Q(status='P'), then=1), output_field=IntegerField())),
                )
            )
            actual_present_count = []
            actual_absent_count = []

            for entry in attendance_summary:
                actual_present_count.append({'section': entry['section'], 'count': entry['present']})
                actual_absent_count.append({'section': entry['section'], 'count': entry['absent']})

            actual_present_count = sorted(actual_present_count, key=lambda x: section_order.index(x['section']))
            actual_absent_count = sorted(actual_absent_count, key=lambda x: section_order.index(x['section']))

            present_emp_count = sum(item['count'] for item in actual_present_count)
            absent_emp_count = sum(item['count'] for item in actual_absent_count)
            total_emp_count = present_emp_count + absent_emp_count

            # Avoid division by zero
            if total_emp_count > 0:
                actual_absenteeism_percentage = round(((absent_emp_count / total_emp_count) * 100), 1)
            else:
                actual_absenteeism_percentage = 0


            absenteeism_data[individual_line]['actual_absent_count'] = actual_absent_count
            absenteeism_data[individual_line]['actual_absenteeism_percentage'] = actual_absenteeism_percentage

        with open("exports/absenteeism_data.json", "w") as f:
            json.dump(absenteeism_data, f, indent=2)

        return success_response(message='Absenteeism report data fetched successfully.', data=absenteeism_data, status=status.HTTP_200_OK)
    except Exception as e:
        print(f"Error in fetch_absenteeism_report_data: {str(e)}")
        logger.error(f"Error in fetch_absenteeism_report_data: {str(e)} at {datetime.now()} hours!", exc_info=True)
        return error_response(error= str(e), status=status.HTTP_400_BAD_REQUEST)



def absenteeism_report(line_no, today):
    try:
        section_order = ['Assembly', 'Back', 'Collar', 'Cuff', 'Front', 'Sleeve']

        absenteeism_filter = {'datetime': today, 'forecast_period': 7}
        attendance_filter = {'attendance_date': today}
        employee_filter = Q()

        if line_no.lower() != 'all':
            absenteeism_filter['line'] = line_no.upper()
            attendance_filter['line'] = line_no.title()
            employee_filter = Q(line=line_no.upper())

        total_emp_count = EmployeeMaster.objects.filter(employee_filter).count()
        if total_emp_count == 0:
            return None, None, error_response(error='No employees found.', status=status.HTTP_404_NOT_FOUND)


        total_employee_queryset = (
            EmployeeMaster.objects
            .filter(employee_filter)
            .values('section')
            .annotate(count=Count('emp_code'))
        )
        total_employee_list = list(total_employee_queryset)
        total_employee_list = sorted(total_employee_list, key=lambda x: section_order.index(x['section']))

        total_employee_count = {
            item['section']: item['count']
            for item in total_employee_list
        }

        predicted_absent_queryset = (
            AbsenteeismPrediction.objects
            .filter(**absenteeism_filter)
            .exclude(section='nan')
            .values('section')
            .annotate(count=Sum('predicted_absent_count'))
        )
        # Convert 'section' to title case
        for item in predicted_absent_queryset:
            item['section'] = item['section'].title()
        predicted_absent_count = sorted(predicted_absent_queryset, key=lambda x: section_order.index(x['section']))

        # Calculate absenteeism percentage by section
        predicted_absenteeism_percentage = {
            item['section']: round((item['count'] / total_employee_count[item['section']] * 100), 1) if total_emp_count else 0
            for item in predicted_absent_queryset
        }

        actual_absent_queryset = (
            AttendanceMaster.objects
            .filter(**attendance_filter)
            .exclude(section='nan')  # Optional: ignore 'nan' values
            .values('section')
            .annotate(
                count=Count(Case(When(~Q(status='P'), then=1)))
            )
        )
        actual_absent_count = sorted(actual_absent_queryset, key=lambda x: section_order.index(x['section']))

        # Calculate absenteeism percentage by section
        actual_absenteeism_percentage = {
            item['section']: round((item['count'] / total_employee_count[item['section']] * 100), 1) if total_emp_count else 0
            for item in actual_absent_count
        }

        response = {
            "total_employee_count": total_employee_count,
            "predicted_absent_count": predicted_absent_count,
            "predicted_absenteeism_percentage": predicted_absenteeism_percentage,
            "actual_absent_count": actual_absent_count,
            "actual_absenteeism_percentage": actual_absenteeism_percentage
        }

        return success_response(message='Data fetched successfully', data=response, status=status.HTTP_200_OK)

    except Exception as e:
        print(f"Error in prepare_prediction_data: {str(e)}")
        return error_response(error=f"Unknown error: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)

