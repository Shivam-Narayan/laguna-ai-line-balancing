import pandas as pd
from collections import defaultdict


def get_valid_dates(dates, order):
    """Filter dates based on order's Date_Start and Date_End constraints"""
    if 'Date_Start' in order['template_row'] and 'Date_End' in order['template_row']:
        date_start = pd.to_datetime(order['template_row']['Date_Start'])
        date_end = pd.to_datetime(order['template_row']['Date_End'])

        valid_dates = [date for date in dates if date_start <= date <= date_end]

        if not valid_dates:
            return dates
        return valid_dates
    return dates


def redistribute_production_plan(data, line_capacities=None, respect_date_ranges=True, max_styles_per_day=None):
    """
    Enhanced redistribution of production plan with flexible line capacities.
    Now considering both style and fabric article for sequencing while preserving
    original order information (OC NO, ORDER NO).

    Args:
        file_path: Path to the CSV file containing the production plan
        line_capacities: Dictionary mapping each line to its daily capacity
                         If None, defaults to 1300 for all lines
        preserve_original_dates: If True, try to maintain original planned dates
                                 Default is now False to provide more flexibility
        max_styles_per_day: Maximum number of style+fabric combinations allowed per day

    Returns:
        DataFrame: Optimized production plan
    """
    date_columns = ['CFM DATE', 'DEL DATE', 'Date_Start', 'Date_End', 'Planned Dates']
    for col in date_columns:
        if col in data.columns:
            data[col] = pd.to_datetime(data[col])

    if 'Week' not in data.columns:
        data['Week'] = data['Planned Dates'].dt.isocalendar().week


    if 'FABRIC ARTICLE' not in data.columns:
        print("Warning: 'FABRIC ARTICLE' column not found in data. Adding default value.")
        data['FABRIC ARTICLE'] = 'DEFAULT'  # Add a default fabric article if the column doesn't exist


    order_identifiers = []
    if 'ORDER NO' in data.columns:
        order_identifiers.append('ORDER NO')
    if 'OC NO' in data.columns:
        order_identifiers.append('OC NO')

    has_order_identifiers = len(order_identifiers) > 0
    if has_order_identifiers:
        print(f"Order identifiers found: {', '.join(order_identifiers)}")
        print("Order details will be preserved during optimization")
    else:
        print("No order identifiers found in data")

    lines = data['Line'].unique()
    planned_dates = sorted(data['Planned Dates'].unique())

    date_to_week = {}
    week_to_dates = defaultdict(list)
    # Check from holiday list and exclude that day 
    for date in planned_dates:
        week = data[data['Planned Dates'] == date]['Week'].iloc[0]
        date_to_week[date] = week
        week_to_dates[week].append(date)

    # Set default line capacities if not provided
    if line_capacities is None:
        line_capacities = {line: 1300 for line in lines}
    else:
        # Ensure all lines have a capacity defined
        for line in lines:
            if line not in line_capacities:
                line_capacities[line] = 1300
                print(f"Warning: No capacity defined for {line}, using default 1300")

    # Create a mapping of delivery dates to priority levels (earlier = higher priority)
    all_del_dates = sorted(data['DEL DATE'].unique())
    del_date_priority = {date: idx for idx, date in enumerate(all_del_dates)}
    # del_date_priority = {pd.Timestamp(date): idx for idx, date in enumerate(all_del_dates)}

    new_plan = []

    # Process each production line separately
    for line in lines:
        print(f"Processing {line} (Capacity: {line_capacities[line]} units/day)...")
        daily_capacity = line_capacities[line]
        line_data = data[data['Line'] == line].copy()

        # Determine style appearance sequence within each week
        style_fabric_week_sequence = {}
        style_fabric_week_first_date = {}

        # Group by Week and determine the first appearance order of styles
        for week, week_df in line_data.groupby('Week'):
            # Sort by Planned Dates to get chronological order
            week_df = week_df.sort_values('DEL DATE')


            style_fabric_order = {}
            style_fabric_first_date = {}
            order_idx = 0

            for _, row in week_df.iterrows():
                style = row['STYLE']
                fabric_article = row['FABRIC ARTICLE']
                style_fabric_key = f"{style}|{fabric_article}"
                if style_fabric_key not in style_fabric_order:
                    style_fabric_order[style_fabric_key] = order_idx
                    style_fabric_first_date[style_fabric_key] = row['DEL DATE']
                    order_idx += 1

            # Store sequence for this week
            style_fabric_week_sequence[week] = style_fabric_order
            style_fabric_week_first_date[week] = style_fabric_first_date
            print(f"  Week {week}: {len(style_fabric_order)} style+fabric combinations in sequence")

        # Process orders individually to preserve order details (instead of pre-aggregating)
        if has_order_identifiers:
            # Skip aggregation and process each row individually to preserve order info
            orders = []
            for idx, row in line_data.iterrows():
                style = row['STYLE']
                fabric_article = row['FABRIC ARTICLE']
                style_fabric_key = f"{style}|{fabric_article}"
                week = row['Week']
                del_date = row['DEL DATE']
                planned_qty = row['Planned Qty']

        
                if week in style_fabric_week_sequence and style_fabric_key in style_fabric_week_sequence[week]:
                    sequence = style_fabric_week_sequence[week][style_fabric_key]
                    first_appearance_date = del_date #style_fabric_week_first_date[week][style_fabric_key]
                else:
                    sequence = 999
                    first_appearance_date = None

                priority = del_date_priority[del_date]

                
                order = {
                    'style': style,
                    'fabric_article': fabric_article,
                    'style_fabric_key': style_fabric_key,
                    'week': week,
                    'del_date': del_date,
                    'sequence': sequence,
                    'first_appearance_date': first_appearance_date,
                    'priority': priority,
                    'qty': planned_qty,
                    'template_row': row.copy(),  # Keep all original data
                    'row_idx': idx
                }
                orders.append(order)

            
            orders.sort(key=lambda x: (x['week'], x['priority'], x['sequence'], -x['qty']))

        else:
            
            groups = []
            for (style, fabric_article, week, del_date), group_df in line_data.groupby(['STYLE', 'FABRIC ARTICLE', 'Week', 'DEL DATE']):
                total_qty = group_df['Planned Qty'].sum()
                sample_row = group_df.iloc[0].copy()

                
                style_fabric_key = f"{style}|{fabric_article}"
                if week in style_fabric_week_sequence and style_fabric_key in style_fabric_week_sequence[week]:
                    sequence = style_fabric_week_sequence[week][style_fabric_key]
                    first_appearance_date = del_date#[week][style_fabric_key]
                else:
                    sequence = 999
                    first_appearance_date = None

                priority = del_date_priority[del_date]

                groups.append({
                    'style': style,
                    'fabric_article': fabric_article,
                    'style_fabric_key': style_fabric_key,
                    'week': week,
                    'del_date': del_date,
                    'sequence': sequence,
                    'first_appearance_date': first_appearance_date,
                    'priority': priority,
                    'total_qty': total_qty,
                    'template_row': sample_row,
                    'original_rows': group_df.to_dict('records')
                })

            
            groups.sort(key=lambda x: (x['week'], x['priority'],x['sequence'],-x['total_qty'],))
            orders = groups  # Use the same variable name for the rest of the code


        # Initialize tracking structures for this line
        day_loads = {date: 0 for date in planned_dates}
        day_styles_fabrics = {date: set() for date in planned_dates}  # Track style+fabric combinations
        style_fabric_allocation = defaultdict(list)  # Track where each style+fabric is allocated

        # Add max styles tracking
        if max_styles_per_day:
            print(f"Limiting {line} to maximum {max_styles_per_day} style+fabric combinations per day")

        # Allocation strategy - modified to handle both grouped and individual orders
        current_week = None
        week_styles_fabrics_processed = set()


        for order in orders:
            style = order['style']
            fabric_article = order['fabric_article']
            style_fabric_key = order['style_fabric_key']
            week = order['week']

            # Get quantity - different depending on whether we're using groups or individual orders
            if has_order_identifiers:
                total_qty = order['qty']
            else:
                total_qty = order['total_qty']

            remaining_qty = total_qty
            template_row = order['template_row']

            # Moving to a new week ---here its the adjacent weeks
            if week != current_week:
                current_week = week
                week_styles_fabrics_processed = set()
                print(f"  Processing Week {week}")

    
            week_styles_fabrics_processed.add(style_fabric_key)

            # First try to allocate to dates in the current week
            week_dates = sorted(week_to_dates.get(week, []))
            valid_week_dates = get_valid_dates(week_dates, order)

            # check available dates
            if 'Date_Start' in order['template_row'] and 'Date_End' in order['template_row']:
                date_start = pd.to_datetime(order['template_row']['Date_Start'])
                date_end = pd.to_datetime(order['template_row']['Date_End'])

                # Filter available dates based on style's date range
                valid_week_dates = [date for date in week_dates
                                    if date_start <= date <= date_end]

                ###fallback to all week dates---optional in case no valid dates found
                if not valid_week_dates:
                    valid_week_dates = week_dates
            else:
                valid_week_dates = week_dates

            # Strategy 1: Try to find days within this week where this style+fabric can fit completely
            full_allocation_done = False

            for date in valid_week_dates:
                # Skip if max styles+fabrics constraint would be violated
                if (max_styles_per_day is not None and
                    style_fabric_key not in day_styles_fabrics[date] and
                    len(day_styles_fabrics[date]) >= max_styles_per_day):
                    continue

                available_capacity = daily_capacity - day_loads[date]

                ### If we can fit the entire style+fabric quantity here,let's do it
                if available_capacity >= remaining_qty:
                    new_row = template_row.copy()
                    new_row['Planned Dates'] = date
                    new_row['Planned Qty'] = remaining_qty

                    # Add a tracking ID to show this row was split (if using order details)
                    if has_order_identifiers:
                        new_row['Split_ID'] = f"{order['row_idx']}_1"

                    new_plan.append(new_row)

                    day_loads[date] += remaining_qty
                    day_styles_fabrics[date].add(style_fabric_key)
                    style_fabric_allocation[style_fabric_key].append(date)
                    remaining_qty = 0
                    full_allocation_done = True
                    break

            # Strategy 2: If full allocation not possible, try partial allocations within the week
            if not full_allocation_done and remaining_qty > 0:
                split_count = 0
                for date in valid_week_dates:
                    # Skip if max styles+fabrics constraint would be violated
                    if (max_styles_per_day is not None and
                        style_fabric_key not in day_styles_fabrics[date] and
                        len(day_styles_fabrics[date]) >= max_styles_per_day):
                        continue

                    available_capacity = daily_capacity - day_loads[date]
                    qty_to_allocate = min(remaining_qty, available_capacity)

                    if qty_to_allocate > 0:
                        split_count += 1
                        new_row = template_row.copy()
                        new_row['Planned Dates'] = date
                        new_row['Planned Qty'] = qty_to_allocate

                        
                        if has_order_identifiers:
                            new_row['Split_ID'] = f"{order['row_idx']}_{split_count}"

                        new_plan.append(new_row)

                        day_loads[date] += qty_to_allocate
                        day_styles_fabrics[date].add(style_fabric_key)
                        style_fabric_allocation[style_fabric_key].append(date)
                        remaining_qty -= qty_to_allocate

                    if remaining_qty <= 0:
                        break

            # Strategy 3: If still remaining, look for available days in adjacent weeks
            if remaining_qty > 0:
                adjacent_weeks = [w for w in week_to_dates.keys() if abs(w - week) <= 1 and w != week]
                adjacent_dates = []

                for adj_week in adjacent_weeks:
                    adjacent_dates.extend(week_to_dates.get(adj_week, []))

                adjacent_dates.sort()  # Sort by date
                valid_adjacent_dates = get_valid_dates(adjacent_dates, order)
                split_count = len([r for r in new_plan if (has_order_identifiers and
                                  'Split_ID' in r and
                                  r['Split_ID'].startswith(f"{order['row_idx']}_"))])

                for date in valid_adjacent_dates:
                    # Skip if max styles+fabrics constraint would be violated
                    if (max_styles_per_day is not None and
                        style_fabric_key not in day_styles_fabrics[date] and
                        len(day_styles_fabrics[date]) >= max_styles_per_day):
                        continue

                    available_capacity = daily_capacity - day_loads[date]
                    qty_to_allocate = min(remaining_qty, available_capacity)

                    if qty_to_allocate > 0:
                        split_count += 1
                        new_row = template_row.copy()
                        new_row['Planned Dates'] = date
                        new_row['Planned Qty'] = qty_to_allocate

                        
                        if has_order_identifiers:
                            new_row['Split_ID'] = f"{order['row_idx']}_{split_count}"

                        new_plan.append(new_row)

                        day_loads[date] += qty_to_allocate
                        day_styles_fabrics[date].add(style_fabric_key)
                        style_fabric_allocation[style_fabric_key].append(date)
                        remaining_qty -= qty_to_allocate

                    if remaining_qty <= 0:
                        break


            # Strategy 4: If still remaining, find any days with capacity left
            if remaining_qty > 0:
                available_days = [(date, daily_capacity - day_loads[date])
                                for date in planned_dates
                                if day_loads[date] < daily_capacity]
                available_days.sort(key=lambda x: x[0])  # Sort by date

                if 'Date_Start' in order['template_row'] and 'Date_End' in order['template_row']:
                    date_start = pd.to_datetime(order['template_row']['Date_Start'])
                    date_end = pd.to_datetime(order['template_row']['Date_End'])
                    available_days = [(date, capacity) for date, capacity in available_days
                                    if date_start <= date <= date_end]


                    if not available_days:
                        available_days = [(date, daily_capacity - day_loads[date])
                                        for date in planned_dates
                                        if day_loads[date] < daily_capacity]
                        available_days.sort(key=lambda x: x[0])


                split_count = len([r for r in new_plan if (has_order_identifiers and
                                  'Split_ID' in r and
                                  r['Split_ID'].startswith(f"{order['row_idx']}_"))])

                for date, available_capacity in available_days:
                    # Skip if max styles+fabrics constraint would be violated
                    if (max_styles_per_day is not None and
                        style_fabric_key not in day_styles_fabrics[date] and
                        len(day_styles_fabrics[date]) >= max_styles_per_day):
                        continue

                    qty_to_allocate = min(remaining_qty, available_capacity)

                    if qty_to_allocate > 0:
                        split_count += 1
                        new_row = template_row.copy()
                        new_row['Planned Dates'] = date
                        new_row['Planned Qty'] = qty_to_allocate

                        # Add a tracking ID to show this row was split (if using order details)
                        if has_order_identifiers:
                            new_row['Split_ID'] = f"{order['row_idx']}_{split_count}"

                        new_plan.append(new_row)

                        day_loads[date] += qty_to_allocate
                        day_styles_fabrics[date].add(style_fabric_key)
                        style_fabric_allocation[style_fabric_key].append(date)
                        remaining_qty -= qty_to_allocate

                    if remaining_qty <= 0:
                        break

            # Strategy 5: If we STILL have quantity, allow exceeding capacity slightly---this section needs one more iteration
            if remaining_qty > 0:
                print(f"Warning: Could not fully allocate {style} (fabric article: {fabric_article}) within capacity limits.")
                print(f"         Allowing slight overloading to accommodate {remaining_qty} units")

                # Try to add to days where this style+fabric is already allocated
                style_fabric_days = [date for date in planned_dates if style_fabric_key in day_styles_fabrics[date]]

                # Filter by date constraints
                if 'Date_Start' in order['template_row'] and 'Date_End' in order['template_row']:
                    date_start = pd.to_datetime(order['template_row']['Date_Start'])
                    date_end = pd.to_datetime(order['template_row']['Date_End'])
                    filtered_style_fabric_days = [date for date in style_fabric_days
                                                if date_start <= date <= date_end]

                    # Use filtered list if it's not empty
                    if filtered_style_fabric_days:
                        style_fabric_days = filtered_style_fabric_days

                split_count = len([r for r in new_plan if (has_order_identifiers and
                                  'Split_ID' in r and
                                  r['Split_ID'].startswith(f"{order['row_idx']}_"))])

                if style_fabric_days:
                    # lowest load day
                    best_day = min(style_fabric_days, key=lambda d: day_loads[d])
                    split_count += 1
                    new_row = template_row.copy()
                    new_row['Planned Dates'] = best_day
                    new_row['Planned Qty'] = remaining_qty

                    # Add a tracking ID to show this row was split (if using order details)
                    if has_order_identifiers:
                        new_row['Split_ID'] = f"{order['row_idx']}_{split_count}"

                    new_plan.append(new_row)

                    day_loads[best_day] += remaining_qty
                    print(f"         Added to existing style+fabric day {best_day}, new load: {day_loads[best_day]}")
                    remaining_qty = 0
                else:
                    # Try to add to days in the same week
                    same_week_days = week_to_dates.get(week, [])
                    if same_week_days:
                        best_day = min(same_week_days, key=lambda d: day_loads[d])
                        split_count += 1
                        new_row = template_row.copy()
                        new_row['Planned Dates'] = best_day
                        new_row['Planned Qty'] = remaining_qty

                       
                        if has_order_identifiers:
                            new_row['Split_ID'] = f"{order['row_idx']}_{split_count}"

                        new_plan.append(new_row)

                        day_loads[best_day] += remaining_qty
                        day_styles_fabrics[best_day].add(style_fabric_key)
                        print(f"         Added to same week day {best_day}, new load: {day_loads[best_day]}")
                        remaining_qty = 0
                    else:
                        ########################## version 6 in testing ####################################

                        # First try days in the same week
                        same_week_days = week_to_dates.get(week, [])
                        valid_days = same_week_days
                        
                        # Apply date range filtering
                        if 'Date_Start' in order['template_row'] and 'Date_End' in order['template_row']:
                            date_start = pd.to_datetime(order['template_row']['Date_Start'])
                            date_end = pd.to_datetime(order['template_row']['Date_End'])
                            filtered_days = [date for date in same_week_days if date_start <= date <= date_end]
                            
                            # Use filtered list only if it's not empty
                            if filtered_days:
                                valid_days = filtered_days
                        
                        # If still no valid days, fall back to all planned dates
                        if not valid_days:
                            # Use all planned dates as a last resort
                            valid_days = planned_dates
                            print(f"         WARNING: No valid days within date constraints for {style}, using any available day")
                        
                        # Find the day with the lowest load
                        best_day = min(valid_days, key=lambda d: day_loads[d]) if valid_days else planned_dates[0]
                        
                        # Create a safety net - if somehow best_day is still not defined, use the first planned date
                        if not best_day:
                            best_day = planned_dates[0]
                            print(f"         CRITICAL: Using first available date as fallback for {style}")
                        
                        split_count += 1
                        new_row = template_row.copy()
                        new_row['Planned Dates'] = best_day
                        new_row['Planned Qty'] = remaining_qty
                        
                        # Add a tracking ID to show this row was split (if using order details)
                        if has_order_identifiers:
                            new_row['Split_ID'] = f"{order['row_idx']}_{split_count}"
                        
                        new_plan.append(new_row)
                        
                        day_loads[best_day] += remaining_qty
                        day_styles_fabrics[best_day].add(style_fabric_key)
                        print(f"         Added to day {best_day} as last resort, new load: {day_loads[best_day]}")
                        remaining_qty = 0

                        #######################################################################
    new_plan_df = pd.DataFrame(new_plan)


    print("\nAnalyzing redistribution results...")
    original_total = analyze_redistribution(data, new_plan_df, line_capacities)
    if 'Planned Qty' in new_plan_df.columns:
        new_plan_df['Planned Qty'] = new_plan_df['Planned Qty'].astype(float)
        print("Rounded all planned quantities to whole numbers")

    return new_plan_df, original_total

def analyze_redistribution(original_df, new_df, line_capacities):
    """
    Comprehensive analysis of the difference between original and new production plans.
    Now accounting for both style and fabric article in the analysis.

    Args:
        original_df: Original production plan DataFrame
        new_df: Redistributed production plan DataFrame
        line_capacities: Dictionary mapping each line to its daily capacity
    """
    # Calculate daily loads for original and new plans
    original_loads = defaultdict(float)
    new_loads = defaultdict(float)

    original_style_fabrics = defaultdict(set)
    new_style_fabrics = defaultdict(set)

    if 'FABRIC ARTICLE' not in original_df.columns:
        original_df = original_df.copy()
        original_df['FABRIC ARTICLE'] = 'DEFAULT'
    if 'FABRIC ARTICLE' not in new_df.columns:
        new_df = new_df.copy()
        new_df['FABRIC ARTICLE'] = 'DEFAULT'

    # Process original plan
    for _, row in original_df.iterrows():
        key = f"{row['Line']}|{row['Planned Dates']}"
        original_loads[key] += row['Planned Qty']
        style_fabric_key = f"{row['STYLE']}|{row['FABRIC ARTICLE']}"
        original_style_fabrics[key].add(style_fabric_key)

    # Process new plan
    for _, row in new_df.iterrows():
        key = f"{row['Line']}|{row['Planned Dates']}"
        new_loads[key] += row['Planned Qty']
        style_fabric_key = f"{row['STYLE']}|{row['FABRIC ARTICLE']}"
        new_style_fabrics[key].add(style_fabric_key)

    # Analyze overloading
    original_overloaded = 0
    new_overloaded = 0
    original_total_over = 0
    new_total_over = 0

    for key, load in original_loads.items():
        line = key.split('|')[0]
        capacity_limit = line_capacities.get(line, 1300)
        if load > capacity_limit:
            original_overloaded += 1
            original_total_over += (load - capacity_limit)

    for key, load in new_loads.items():
        line = key.split('|')[0]
        capacity_limit = line_capacities.get(line, 1300)
        if load > capacity_limit:
            new_overloaded += 1
            new_total_over += (load - capacity_limit)

    print(f"Original plan: {original_overloaded} days exceeding capacity ({original_total_over:.2f} total units over)")
    print(f"New plan: {new_overloaded} days exceeding capacity ({new_total_over:.2f} total units over)")

    # Analyze style distribution
    original_style_fabric_count = [len(style_fabrics) for style_fabrics in original_style_fabrics.values()]
    new_style_fabric_count = [len(style_fabrics) for style_fabrics in new_style_fabrics.values()]

    original_avg_style_fabrics = sum(original_style_fabric_count) / len(original_style_fabric_count) if original_style_fabric_count else 0
    new_avg_style_fabrics = sum(new_style_fabric_count) / len(new_style_fabric_count) if new_style_fabric_count else 0

    original_single_style_fabric = sum(1 for count in original_style_fabric_count if count == 1)
    new_single_style_fabric = sum(1 for count in new_style_fabric_count if count == 1)

    print(f"Original plan: {original_avg_style_fabrics:.2f} avg style+fabric combinations per day, {original_single_style_fabric} single-combination days")
    print(f"New plan: {new_avg_style_fabrics:.2f} avg style+fabric combinations per day, {new_single_style_fabric} single-combination days")

    ######### capacity utilization by line
    lines = set([key.split('|')[0] for key in new_loads.keys()])
    for line in lines:
        line_keys = [key for key in new_loads.keys() if key.split('|')[0] == line]
        capacity = line_capacities.get(line, 1300)

        original_line_util = [original_loads.get(key, 0) / capacity * 100 for key in line_keys]
        new_line_util = [new_loads.get(key, 0) / capacity * 100 for key in line_keys]

        if original_line_util:
            orig_avg = sum(original_line_util) / len(original_line_util)
            new_avg = sum(new_line_util) / len(new_line_util)

            print(f"{line}: Original capacity utilization: {orig_avg:.2f}%, New: {new_avg:.2f}%")

    # Check for any potential issues with the new plan
    under_utilized_lines = {}
    for key, load in new_loads.items():
        line = key.split('|')[0]
        capacity = line_capacities.get(line, 1300)
        utilization = load / capacity * 100

        if utilization < 50:
            if line not in under_utilized_lines:
                under_utilized_lines[line] = 0
            under_utilized_lines[line] += 1

            ####strategy 6 needs to be included to handle this

    if under_utilized_lines:
        print("\nWarning: Some days have less than 50% capacity utilization:")
        for line, count in under_utilized_lines.items():
            print(f"  {line}: {count} days under 50% capacity")

    # Verify total quantities remain the same
    original_total = original_df['Planned Qty'].sum()
    new_total = new_df['Planned Qty'].sum()

    if abs(original_total - new_total) > 0.01:
        print(f"\nWarning: Total quantities differ! Original: {original_total:.2f}, New: {new_total:.2f}")
    else:
        print(f"\nTotal quantities preserved: {original_total:.2f} units")

    if 'ORDER NO' in new_df.columns or 'OC NO' in new_df.columns:
        order_split_analysis(new_df)

    return original_total

def order_split_analysis(new_df):
    # new_df.to_csv("csv_files/debug_df.csv", index=False)

    """
    Analyze how orders were split during optimization
    """

    if 'Split_ID' not in new_df.columns:
        print("\nNo split tracking information available")
        return

    
    if 'ORDER NO' in new_df.columns:
        order_column = 'ORDER NO'
    elif 'OC NO' in new_df.columns:
        order_column = 'OC NO'
    else:
        return

    total_orders = new_df[order_column].nunique()

    split_ids = new_df['Split_ID'].dropna()
    row_ids = [int(split_id.split('_')[0]) for split_id in split_ids if '_' in split_id]
    unique_row_ids = set(row_ids)

    split_counts = {}
    for row_id in unique_row_ids:
        matching_splits = [s for s in split_ids if s.startswith(f"{row_id}_")]
        if len(matching_splits) > 1:  # Only count as split if more than one piece
            split_counts[row_id] = len(matching_splits)

    total_split_orders = len(split_counts)
    max_split_count = max(split_counts.values()) if split_counts else 0
    avg_split_count = sum(split_counts.values()) / len(split_counts) if split_counts else 0

    print(f"\nOrder split analysis:")
    print(f"  Total orders: {total_orders}")
    print(f"  Orders split across multiple days: {total_split_orders} ({total_split_orders/total_orders*100:.1f}%)")
    print(f"  Maximum splits for a single order: {max_split_count}")
    print(f"  Average splits per split order: {avg_split_count:.2f}")
