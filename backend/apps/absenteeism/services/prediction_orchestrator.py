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
from ..prediction import model_prediction
from backend_laguna.utils import truncate_table
from apps.manning_sheet.views import NOTIFICATION_DISPLAY_TITLE
from apps.manning_sheet.models import ManningSheetData, LoadingPlan
from apps.accounts.authentication import CookieJWTAuthentication
from ..models import Absenteeism, PredictionData, AbsenteeismPrediction
from apps.manning_sheet.utils import create_bulk_push_notifications, custom_round
from apps.accounts.utils.response_handlers import error_response, success_response
from apps.data_engine.models import LocalHolidayCalendar, EmployeeMaster, AttendanceMaster
from ..absenteeism_percentage import calculate_line_percentages, get_working_days_around_date
from ..utils import generate_csv, send_email, generate_prediction_data, convert_number, update_sections, merge_duplicates, is_allowed_working_day, sum_section_counts, normalize_sections, write_absenteeism_data_to_csv, export_absenteeism_predictions_excel

logger = logging.getLogger('general')
prediction_response = {}

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
        
        if consolidated_df is None:
            return error_response(error='Prediction generation failed. Ensure there is enough historical attendance and weather data.', status=status.HTTP_400_BAD_REQUEST)

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

        # Convert forecast_period to int to ensure dictionary matching
        consolidated_df['forecast_period'] = consolidated_df['forecast_period'].astype(int)
        
        # Map limit dates to a new column for vectorized comparison
        consolidated_df['limit_date'] = consolidated_df['forecast_period'].map(forecast_limits)

        # Vectorized filtering for dates between today and the limit_date
        consolidated_df = consolidated_df[
            (consolidated_df['datetime'] >= today) & 
            (consolidated_df['datetime'] <= consolidated_df['limit_date'])
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

        consolidated_df.dropna(inplace=True)  # type: ignore

        for _, row in consolidated_df.iterrows():  # type: ignore
            prediction_data_objects.append(
                AbsenteeismPrediction(
                    datetime=row['datetime'],
                    day_of_week=row['day_of_week'],
                    predicted_absent_count=int(row['Predicted_Absent_Count']),
                    line=row['Line'],
                    section=row['Section'].strip(),  # type: ignore
                    forecast_period=row['forecast_period'],
                    historical_mean=row['historical_mean'],
                    historical_std=row['historical_std'],
                    deviation_from_mean=row['deviation_from_mean'],
                )
            )

            if len(prediction_data_objects) >= batch_size:
                with transaction.atomic():  # type: ignore
                    AbsenteeismPrediction.objects.bulk_create(prediction_data_objects, batch_size=batch_size)
                prediction_data_objects.clear()

        # Insert remaining records
        if prediction_data_objects:
            with transaction.atomic():  # type: ignore
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


def prepare_prediction_data(line_no, forecast_period, summation=False):
    try:
        line_no_upper = line_no.upper()
        line_no_lower = line_no.lower()

        valid_lines = [f"line {i}" for i in range(1, 11)] + ['all']
        if line_no_lower not in valid_lines:
            return error_response(error='Invalid line number.', status=status.HTTP_400_BAD_REQUEST)

        today = date.today()
        filter_date = today + timedelta(days=forecast_period)

        employee_filter = Q()
        if line_no_lower != 'all':
            employee_filter = Q(line=line_no_upper)

        total_emp_count = EmployeeMaster.objects.filter(employee_filter).count()
        if total_emp_count == 0:
            return error_response(error='No employees found.', status=status.HTTP_404_NOT_FOUND)

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
            return error_response(error='No predictions found.', status=status.HTTP_404_NOT_FOUND)

        manning_sheet_qs = ManningSheetData.objects.filter(**manning_sheet_filter)  # type: ignore
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
            LoadingPlan.objects  # type: ignore
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
        absenteeism_percentage_by_section = {}
        for item in gap_summary_normalized:
            sec_count = section_emp_count.get(item['section'], 0)
            if sec_count > 0:
                absenteeism_percentage_by_section[item['section']] = round((item['count'] / sec_count * 100), 1)
            else:
                absenteeism_percentage_by_section[item['section']] = 0

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
                
                # If the response is an error, skip it
                if response_data.get('status') == 'error':
                    continue
                
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

        # Sort the lists using the section order safely
        def safe_index(section):
            try:
                return section_order.index(section)
            except ValueError:
                return len(section_order)

        total_operators = sorted(total_operators, key=lambda x: safe_index(x['section']))
        total_operators_supply = sorted(total_operators_supply, key=lambda x: safe_index(x['section']))
        total_operators_gap = sorted(total_operators_gap, key=lambda x: safe_index(x['section']))


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
        logger.info(f"Error in prepare_prediction_data: {str(e)}")
        return error_response(error=f"Unknown error: {str(e)}", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([CookieJWTAuthentication])
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


@api_view(['POST'])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])        
def absenteeism_prediction(request):
    if request.method == 'POST':  
        import threading
        viaAPI = True
        # Run the heavy ML process in the background to prevent 504 Gateway Time-out
        thread = threading.Thread(target=run_absenteeism_prediction, args=(viaAPI,))
        thread.start()
        
        return success_response(
            message='Prediction generation has started in the background. It will take a few minutes to complete.'
        )
    return error_response(error='Invalid request method.', status=405)


@api_view(['GET', 'POST'])
@authentication_classes([CookieJWTAuthentication])
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
            data = gzip.compress(smart_bytes(raw_json))  # type: ignore
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
                response = HttpResponse(excel_data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')  # type: ignore
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
