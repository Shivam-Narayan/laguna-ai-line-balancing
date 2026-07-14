import math
from collections import defaultdict

def convert_number(value):
    if value - math.floor(value) < 0.5:
        return math.floor(value)
    else:
        return math.ceil(value)


def update_sections(input_array, main_array):
    main_sections = {item['section'] for item in main_array}  # Extract existing sections
    
    for item in input_array:
        if item['section'] not in main_sections:
            main_array.append({'section': item['section'], 'count': 0})
    
    return main_array


def merge_duplicates(lst, key="section", value="count"):
    merged_data = defaultdict(int)
    
    for item in lst:
        normalized_key = item[key].strip()  # Normalize by stripping spaces
        merged_data[normalized_key] += item[value]

    return [{key: k, value: v} for k, v in merged_data.items()]


def sum_section_counts(data):
    section_totals = {}

    # Aggregate counts per section
    for entry_list in data:
        for item in entry_list:
            section = item['section']
            count = item['count']
            section_totals[section] = section_totals.get(section, 0) + count

    # Convert the result to list of dicts
    result = [{'section': section, 'count': count} for section, count in section_totals.items()]
    return result


def normalize_sections(data, section_order):
    section_map = {item['section']: item['count'] for item in data}

    normalized = []
    for section in section_order:
        count = section_map.get(section, 0)
        normalized.append({'section': section, 'count': count})

    return normalized
