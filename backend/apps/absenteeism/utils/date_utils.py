import pandas as pd
from apps.data_engine.models import LocalHolidayCalendar, PayableWorkingDays

def is_allowed_working_day(date_obj):

    # Get all payable working days from the database for the date range
    payable_dates_qs = list(PayableWorkingDays.objects.all().values())
    payable_dates = set()
    if payable_dates_qs:
        payable_dates_df = pd.DataFrame(payable_dates_qs)
        if 'date' in payable_dates_df.columns:
            payable_dates_df['date'] = pd.to_datetime(payable_dates_df['date']).dt.date
            payable_dates = set(payable_dates_df['date'])

    if date_obj in payable_dates:
        return True, "Allowed working day"

    # Load the LocalHolidayCalendar data from the database
    holiday_qs = list(LocalHolidayCalendar.objects.all().values())
    holiday_dates = set()
    if holiday_qs:
        local_holiday_calender_df = pd.DataFrame(holiday_qs)
        if 'date' in local_holiday_calender_df.columns:
            local_holiday_calender_df['date'] = pd.to_datetime(local_holiday_calender_df['date']).dt.date
            holiday_dates = set(local_holiday_calender_df['date'])

    if date_obj in holiday_dates:
        return False, "Local Holiday"

    # Sunday logic
    if date_obj.weekday() == 6:  # 6 represents Sunday
        return False, "Sunday"

    # Saturday logic
    if date_obj.weekday() == 5:  # 5 represents Saturday
        saturdays = [
            d.date() for d in pd.date_range(date_obj.replace(day=1), date_obj.replace(day=28) + pd.DateOffset(days=4))
            if d.weekday() == 5 and d.month == date_obj.month
        ]

        # Check if it's the 2nd, 3rd, or 4th Saturday
        if date_obj in saturdays:
            index = saturdays.index(date_obj)
            if index in [1, 2, 3]:  # 2nd, 3rd, or 4th Saturday
                suffix = "th"
                if index == 1:
                    suffix = "nd"
                elif index == 2:
                    suffix = "rd"
                return False, f"{index + 1}{suffix} Saturday"

    return True, "Allowed working day"
