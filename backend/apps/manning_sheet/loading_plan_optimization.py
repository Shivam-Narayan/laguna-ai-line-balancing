import numpy as np
import pandas as pd

from datetime import datetime


DEFAULT_CAPACITY = 1300  # Default capacity per day



# Function to read the Excel file and return a DataFrame after processing
def process_df(df_load_plan, holiday_dates, last_date_of_year, payable_dates):
    # Save the 'sheet_name' column separately before modifying headers
    sheet_name_column = df_load_plan['sheet_name'].copy()

    # Remove the first 5 rows (assuming header is on row 6)
    df_load_plan = df_load_plan.iloc[5:].reset_index(drop=True)

    # Step 9: Set the first row as the new column headers
    df_load_plan.columns = df_load_plan.iloc[0]  # Use the first row as header
    df_load_plan = df_load_plan.iloc[1:].reset_index(drop=True)  # Drop the first row after setting headers

    # Reattach the 'sheet_name' column correctly aligned
    df_load_plan['sheet_name'] = sheet_name_column.iloc[5:].reset_index(drop=True)  # Ensures proper alignment

    last_few_rows = df_load_plan.copy()

    df_load_plan.dropna(how='all', inplace=True)
    df_load_plan = df_load_plan.iloc[2:].reset_index(drop=True)
    df_load_plan = df_load_plan.drop(
        columns=[col for col in df_load_plan.columns if 'KPR L' in str(col) or str(col) == 'NaN' or col in ["Unnamed", "FABRIC", "FABRIC TYPE","REMARKS","IN HOUSE","NEW INH HOUSE","APPROVAL OF FIT/PP","Release of Production file & approved sample","Revised F/R","LC received","TRIMS AVAILABILITY","BAL TO LOAD"]],
        errors='ignore'
    )
    df_load_plan = df_load_plan.drop(columns=[col for col in df_load_plan.columns if str(col).strip().lower() == 'nan'], errors='ignore')
    df_load_plan = df_load_plan.dropna(axis=1, how='all') #44444444444444
    df_load_plan = df_load_plan[df_load_plan.drop(columns=['sheet_name'], errors='ignore').notna().any(axis=1)]

    df_load_plan = df_load_plan[df_load_plan['OC NO'].notna()]
    df_load_plan['OC NO'] = df_load_plan['OC NO'].astype(str).str.strip()
    unwanted_patterns = ['KANAKPURA', 'LINE', 'DATE', 'OC']
    df_load_plan = df_load_plan[~df_load_plan['OC NO'].str.contains('|'.join(unwanted_patterns), case=False, na=False)]
    df_load_plan['Line'] = df_load_plan['sheet_name'].str.strip().str.extract(r'(\d+)$').astype(float).astype('Int64')
    df_load_plan['Line'] = 'Line ' + df_load_plan['Line'].astype(str)

    # Identify columns that start with 'wk'
    wk_columns = [col for col in df_load_plan.columns if isinstance(col, str) and col.startswith('wk')]

    # Replace 'FAB', 'DEL', NaN, and empty strings in 'wk%' columns with 0
    df_load_plan[wk_columns] = df_load_plan[wk_columns].replace(['FAB', 'DEL', np.nan, ''], 0)

    # Melt the dataframe to transform 'wk' columns into rows
    df_load_plan = df_load_plan.melt(
        id_vars=[col for col in df_load_plan.columns if col not in wk_columns],
        value_vars=wk_columns,
        var_name='Week',
        value_name='Planned Qty'
    )

    #Extract the Week Number as an integer
    df_load_plan['Week'] = df_load_plan['Week'].str.extract(r'wk (\d+)')[0].astype(int)

    #Create a mapping of Week Number to Date Range from the column names
    week_date_mapping = {
        int(col.split()[1]): col.split(' ', 2)[-1] for col in wk_columns if col.startswith('wk')
    }

    #Map the extracted week number to its corresponding date range
    df_load_plan['Dates'] = df_load_plan['Week'].map(week_date_mapping)

    #Remove rows where 'Planned Qty' is 0 or NaN
    df_load_plan['Planned Qty'] = pd.to_numeric(df_load_plan['Planned Qty'], errors='coerce') # Convert to numeric manually
    df_load_plan = df_load_plan[df_load_plan['Planned Qty'] > 0]

    # Convert 'CFM DATE' to datetime
    df_load_plan['CFM DATE'] = pd.to_datetime(df_load_plan['CFM DATE'], errors='coerce')

    # Replace 'DEL DATE' with 'NEW DEL' where 'NEW DEL' has a valid date
    df_load_plan['DEL DATE'] = df_load_plan['NEW DEL'].combine_first(df_load_plan['DEL DATE'])

    # Replace any string value to last date of current year
    df_load_plan['DEL DATE'] = df_load_plan['DEL DATE'].apply(lambda x: convert_del_date(x, last_date_of_year))

    # Drop the 'NEW DEL' column
    df_load_plan.drop(columns=['NEW DEL'], inplace=True)

    # Get the current year
    current_year = datetime.now().year

    # Split the Dates column by '-'
    df_load_plan[['Date_Start', 'Date_End']] = df_load_plan['Dates'].str.split('-', expand=True)

    # Trim whitespace
    df_load_plan['Date_Start'] = df_load_plan['Date_Start'].str.strip()
    df_load_plan['Date_End'] = df_load_plan['Date_End'].str.strip()

    # Append the current year and format as dd/mm/yy
    df_load_plan['Date_Start'] = df_load_plan['Date_Start'] + f'/{current_year}'
    df_load_plan['Date_End'] = df_load_plan['Date_End'] + f'/{current_year}'

    # Convert to datetime format and reformat as string dd/mm/yy
    df_load_plan['Date_Start'] = pd.to_datetime(df_load_plan['Date_Start'], format='%d/%m/%Y').dt.strftime('%d/%m/%y')
    df_load_plan['Date_End'] = pd.to_datetime(df_load_plan['Date_End'], format='%d/%m/%Y').dt.strftime('%d/%m/%y')

    # Extract the 'Dates' column from df_dates
    valid_dates = list(set(df_load_plan['Dates'].tolist()))

    # Drop the original Dates column
    df_load_plan.drop(columns=['Dates'], inplace=True)

    sl_columns = ['OC NO', 'ORDER NO', 'STYLE','FABRIC ARTICLE']

    df_load_plan['raw_oc_no'] = df_load_plan['OC NO']
    df_load_plan['raw_style'] = df_load_plan['STYLE']
    df_load_plan['raw_fabric_article'] = df_load_plan['FABRIC ARTICLE']

    for col in sl_columns:
        if col in df_load_plan.columns:
            df_load_plan[col] = df_load_plan[col].astype(str).str.strip()
            df_load_plan[col] = df_load_plan[col].str.replace(r'\s+', ' ', regex=True)
            df_load_plan[col] = df_load_plan[col].str.replace(' ', '', regex=True)
            df_load_plan[col] = df_load_plan[col].str.lower()
            # df_load_plan[col] = df_load_plan[col].str.replace(r'[^a-z0-9]', '', regex=True) # Commented as it will remove special characters

    # Convert Date_Start and Date_End to datetime format
    df_load_plan['Date_Start'] = pd.to_datetime(df_load_plan['Date_Start'], format='%d/%m/%y', errors='coerce')
    df_load_plan['Date_End'] = pd.to_datetime(df_load_plan['Date_End'], format='%d/%m/%y', errors='coerce')

    # # Create an empty list to store expanded data
    # expanded_rows = []

    last_few_rows.drop(columns=['OC NO', 'ORDER NO', 'CFM DATE', 'MERCHANT', 'STYLE', 'BUYER', 'L/S-S/S', 'FABRIC', 'FABRIC TYPE', 'FABRIC ARTICLE', 'REMARKS',  'IN HOUSE', 'NEW INH HOUSE', 'APPROVAL OF FIT/PP', 'Release of Production file & approved sample', 'Revised F/R', 'SMV'], inplace=True)

    # Get all columns except 'QTY ORDER'
    columns_to_check = [col for col in last_few_rows.columns if col not in ['DEL DATE', 'MONTH CODE', 'NEW DEL', 'TRIMS AVAILABILITY', 'BAL TO LOAD', 'QTY ORDER', 'sheet_name']]

    # Filter columns in df_load_plan where the date part of the column name matches the 'Dates' column in df_dates
    columns_to_keep = [col for col in columns_to_check if isinstance(col, str) and any(isinstance(date, str) and date in col for date in valid_dates)]
    columns_to_keep.extend(['DEL DATE', 'MONTH CODE', 'NEW DEL', 'TRIMS AVAILABILITY', 'BAL TO LOAD', 'QTY ORDER', 'sheet_name'])

    
    # Filter df_load_plan to keep only the relevant columns
    last_few_rows_filtered = last_few_rows[columns_to_keep]
    capacity_per_day = last_few_rows_filtered[last_few_rows_filtered['QTY ORDER'] == 'CAPACITY/DAY']

    # Melt the DataFrame to get weeks in a single column
    df_melted = capacity_per_day.melt(
        id_vars=['sheet_name'],  # keep sheet_name
        value_vars=[col for col in capacity_per_day.columns if 'wk' in col],
        var_name='Week',
        value_name='Capacity/Day'
    )
    df_melted = pd.DataFrame(df_melted)

    # Select only the relevant columns (Week, Capacity/Day, Sheet Name)
    final_df_new = df_melted[['Week', 'Capacity/Day', 'sheet_name']]
    final_df_new['Week'] = final_df_new['Week'].str.extract(r'wk (\d+)')[0].astype(int)
    final_df_new['Dates'] = final_df_new['Week'].map(week_date_mapping)
    # Split the Dates column by '-'
    final_df_new[['Date_Start', 'Date_End']] = final_df_new['Dates'].str.split('-', expand=True)

    # Trim whitespace
    final_df_new['Date_Start'] = final_df_new['Date_Start'].str.strip()
    final_df_new['Date_End'] = final_df_new['Date_End'].str.strip()

    # Append the current year and format as dd/mm/yy
    final_df_new['Date_Start'] = final_df_new['Date_Start'] + f'/{current_year}'
    final_df_new['Date_End'] = final_df_new['Date_End'] + f'/{current_year}'

    # Convert to datetime format and reformat as string dd/mm/yy
    final_df_new['Date_Start'] = pd.to_datetime(final_df_new['Date_Start'], format='%d/%m/%Y').dt.strftime('%d/%m/%y')
    final_df_new['Date_End'] = pd.to_datetime(final_df_new['Date_End'], format='%d/%m/%Y').dt.strftime('%d/%m/%y')

    # df_load_plan_14 = df_load_plan[df_load_plan['Week']==14]
    df_load_plan = divide_qts_per_day(df_load_plan, final_df_new, holiday_dates, payable_dates)
    return df_load_plan, final_df_new



# Function to check if a date is the 1st or 5th Saturday of the month
# def is_included_saturday(date):
#     if date.weekday() == 5:  # 5 = Saturday
#         first_saturday = (date.replace(day=1) + pd.DateOffset(days=(5 - date.replace(day=1).weekday() + 7) % 7))
#         fifth_saturday = first_saturday + pd.DateOffset(weeks=4)  # Calculate 5th Saturday (if exists)
#         return date == first_saturday or (fifth_saturday.month == date.month and date == fifth_saturday)
#     return False

# Function to check if a date is the 1st or 5th Saturday of the month
def is_included_saturday(check_date):
    if check_date.weekday() != 5:
        return False

    # Count how many Saturdays have occurred in the month up to this date
    saturday_count = 0
    for day in range(1, check_date.day + 1):
        d = check_date.replace(day=day)
        if d.weekday() == 5:
            saturday_count += 1
    return saturday_count in [1, 5]



# Function to divide quantities per day based on the load plan and capacity
def divide_qts_per_day(df_load_plan, final_df_new, holiday_dates, payable_dates):
    # Dictionary to map week to capacity per day
    week_to_capacity = dict(zip(final_df_new['Week'], final_df_new['Capacity/Day']))
    
    # Create a copy of the input dataframe to preserve original data
    result_df = pd.DataFrame(columns=list(df_load_plan.columns) + ['Planned_Dates'])
    
    # Dictionary to track remaining capacity for each working day
    day_capacities = {}
    
    # Group the load plan by Week for processing
    for week, week_group in df_load_plan.groupby('Week'):
        # Get the capacity per day for this week
        per_day_qty = week_to_capacity.get(week, DEFAULT_CAPACITY)  # Default to DEFAULT_CAPACITY if week not found
        print(f"Processing Week {week} with daily capacity: {per_day_qty}")
        
        # Process each order in this week's group
        for _, row in week_group.iterrows():
            start_date = row['Date_Start']
            end_date = row['Date_End']
            remaining_qty = row['Planned Qty']

            original_qty_order = row['QTY ORDER'] # New line
            
            # Generate full date range
            full_date_range = pd.date_range(start=start_date, end=end_date)
            
            # Remove holidays from the date range
            full_date_range = full_date_range[~full_date_range.isin(holiday_dates)]
            
            # # Keep only weekdays + 1st & 5th Saturdays (drop other Saturdays & Sundays)
            # working_days = [
            #     date for date in full_date_range
            #     if date.weekday() != 6 and (date.weekday() != 5 or is_included_saturday(date))
            # ]

            # Keep only weekdays + 1st & 5th Saturdays + any dates in PayableWorkingDays
            # (drop other Saturdays & Sundays unless they're in PayableWorkingDays)
            working_days = [
                date for date in full_date_range
                if (
                    date.date() in payable_dates or  # Include if explicitly in PayableWorkingDays
                    (date.weekday() != 6 and (date.weekday() != 5 or is_included_saturday(date)))
                )
            ]
            
            # Initialize capacity for each working day if not already done
            for day in working_days:
                day_str = day.strftime('%Y-%m-%d')
                if day_str not in day_capacities:
                    day_capacities[day_str] = per_day_qty

            # Track how much of the original planned quantity we've processed
            total_planned = row['Planned Qty'] # New line
            qty_processed = 0 # New line
            
            # Schedule this order across working days
            for day in working_days:
                day_str = day.strftime('%Y-%m-%d')
                
                # Skip days with no remaining capacity
                if day_capacities[day_str] <= 0 or remaining_qty <= 0:
                    continue
                
                # Determine quantity to be scheduled on this day
                qty_for_today = min(remaining_qty, day_capacities[day_str])
                
                if qty_for_today > 0:
                    # Calculate the proportion of this split compared to the total
                    proportion = qty_for_today / total_planned # New line

                    # Calculate proportional QTY ORDER
                    proportional_qty_order = original_qty_order * proportion # New line
                    
                    # Create a new row for the final dataframe
                    new_row = row.copy()
                    new_row['Planned Qty'] = qty_for_today
                    new_row['Planned_Dates'] = day_str
                    new_row['QTY ORDER'] = proportional_qty_order # New line
                    
                    # Add the new row to the result dataframe
                    result_df = pd.concat([result_df, pd.DataFrame([new_row])], ignore_index=True)
                    
                    # Update remaining quantity and day capacity
                    remaining_qty -= qty_for_today
                    day_capacities[day_str] -= qty_for_today
                    qty_processed += qty_for_today # New line
                
                # If order is fully scheduled, move to next order
                if remaining_qty <= 0:
                    break
            
            # Check if we couldn't schedule all of the quantity
            if qty_processed < total_planned: # New line
                print(f"Warning: Could not schedule all quantity for order {row['OC NO']}. Scheduled: {qty_processed}/{total_planned}")
    
    # Verify all quantities have been scheduled
    total_planned = df_load_plan['Planned Qty'].sum()
    total_scheduled = result_df['Planned Qty'].sum()
    
    if abs(total_planned - total_scheduled) > 0.001:  # Using small threshold to account for floating point errors
        print(f"Warning: Not all quantities scheduled. Original: {total_planned}, Scheduled: {total_scheduled}")
        print(f"Difference: {total_planned - total_scheduled}")

    # Verify QTY ORDER has been properly split
    total_qty_order_original = df_load_plan['QTY ORDER'].sum() # New line
    total_qty_order_scheduled = result_df['QTY ORDER'].sum() # New line

    if abs(total_qty_order_original - total_qty_order_scheduled) > 0.001: # New line
        print(f"Warning: QTY ORDER totals don't match. Original: {total_qty_order_original}, Scheduled: {total_qty_order_scheduled}")
        print(f"Difference: {total_qty_order_original - total_qty_order_scheduled}")
    
    # Print daily capacity usage
    print("\nDaily capacity usage:")
    daily_usage = result_df.groupby(['Week', 'Planned_Dates'])['Planned Qty'].sum().reset_index()
    
    for week, week_group in daily_usage.groupby('Week'):
        capacity = week_to_capacity.get(week, DEFAULT_CAPACITY)
        print(f"\nWeek {week} (Capacity/Day: {capacity}):")
        for _, row in week_group.iterrows():
            date = row['Planned_Dates']
            usage = row['Planned Qty']
            print(f"  {date}: {usage:.1f} / {capacity}")    
    return result_df



# Function to check and convert each value
def convert_del_date(val, last_date_of_year):
    if isinstance(val, str):
        return last_date_of_year
    return val