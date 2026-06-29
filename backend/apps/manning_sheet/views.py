from .services.data_ingestion_service import styleob_file_upload, loading_plan_file_upload, loading_plan_file_upload_old, emp_fact_file_upload, wip_file_upload, fetch_emp_attendance_rockhr, fetch_emp_details_rockhr, fetch_and_transform_emp_attendance, fetch_and_transform_empdetails, fetch_wip_data_api, run_fetch_wip_data, uploading_planned_leaves, upload_wip_data, add_bulk_wip_data, upload_active_employees
from .services.manning_engine_service import manning_sheet_generation, generate_emp_fact, run_generate_emp_fact, manning_allocation, run_manning_generation, generate_dday_manning_data, run_dday_generation, generate_style_ob, run_generate_style_ob
from .services.data_retrieval_service import get_manning_data, get_actual_vs_planned_data, get_dday_data, get_dday_manning_data, get_unallocated_employees_count, get_dday_actual_vs_planned_data, get_attendance_data, get_unallocated_employees, get_unallocated_employees_dday
from .services.allocation_service import update_allocated_employees, update_employee_on_hold_individual, update_employee_on_hold, update_allocated_capacity
from .services.export_service import download_manning_data_by_section, download_manning_attendance_data, download_notification_file
from .services.notification_service import get_user_notifications, mark_notification_read, create_test_notification

NOTIFICATION_DISPLAY_TIME = {
    "dday_8_50": "8:50 AM",
    "dday_12_45": "12:45 PM",
    "dday_5_30": "5:30 PM",
}

NOTIFICATION_DISPLAY_TITLE = {
    'dday_8_50': 'D-Day 8:50 AM Allocation Data',
    'dday_12_45': 'D-day 12:45 PM Allocation Data',
    'dday_5_30': 'D-Day 5:30 PM Allocation Data',
    'manning_sheet': 'Manning Sheet Allocation Data',
    'absenteeism_prediction': 'Absenteeism Prediction Data',
}
