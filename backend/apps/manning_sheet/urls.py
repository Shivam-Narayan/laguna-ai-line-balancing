from django.urls import path

from . import views

urlpatterns = [
    # --- Data Ingestion ---
    path(
        "style-obs/upload/",
        views.StyleObFileUploadAPIView.as_view(),
        name="uploading style ob data",
    ),
    path(
        "loading-plans/upload/",
        views.LoadingPlanFileUploadAPIView.as_view(),
        name="uploading Uploading ob data",
    ),
    path(
        "emp-facts/upload/",
        views.EmpFactFileUploadAPIView.as_view(),
        name="uploading Emp Fact data",
    ),
    path(
        "wips/upload-file/",
        views.WipFileUploadAPIView.as_view(),
        name="uploading WIP data",
    ),
    path(
        "planned-leaves/upload/",
        views.UploadingPlannedLeavesAPIView.as_view(),
        name="uploading_planned_leaves",
    ),
    path(
        "wips/upload/",
        views.UploadWipDataAPIView.as_view(),
        name="upload_wip_data",
    ),
    path(
        "wips/bulk/",
        views.AddBulkWipDataAPIView.as_view(),
        name="add_bulk_wip_data",
    ),
    path(
        "employees/upload/",
        views.UploadActiveEmployeesAPIView.as_view(),
        name="upload_active_employees",
    ),

    # --- Manning Engine ---
    path(
        "manning-sheets/generate/",
        views.ManningAllocationAPIView.as_view(),
        name="Generating Manning Sheet",
    ),
    path(
        "manning-sheets/d-day/generate/",
        views.GenerateDdayManningAPIView.as_view(),
        name="Generating Dday Manning Sheet",
    ),
    path(
        "emp-facts/generate/",
        views.GenerateEmpFactAPIView.as_view(),
        name="generate_emp_fact",
    ),
    path(
        "style-obs/generate/",
        views.GenerateStyleObAPIView.as_view(),
        name="generate_style_ob",
    ),

    # --- Data Retrieval ---
    path(
        "manning-sheets/",
        views.ManningDataAPIView.as_view(),
        name="get manning data",
    ),
    path(
        "manning-sheets/d-day/",
        views.DdayManningDataAPIView.as_view(),
        name="get Dday manning data",
    ),
    path(
        "attendance/",
        views.AttendanceDataAPIView.as_view(),
        name="get Attendance data",
    ),
    path(
        "employees/unallocated/",
        views.UnallocatedEmployeesAPIView.as_view(),
        name="get_unallocated_employees",
    ),
    path(
        "employees/unallocated/d-day/",
        views.UnallocatedEmployeesDdayAPIView.as_view(),
        name="get_unallocated_employees_dday",
    ),

    # --- Exports ---
    path(
        "manning-sheets/export/",
        views.DownloadManningDataBySectionAPIView.as_view(),
        name="get manning data export",
    ),
    path(
        "attendance/export/",
        views.DownloadManningAttendanceAPIView.as_view(),
        name="Download Dday and Attendance data",
    ),
    path(
        "notifications/download/",
        views.DownloadNotificationFileAPIView.as_view(),
        name="download_notification_file",
    ),

    # --- Notifications ---
    path(
        "notifications/",
        views.UserNotificationsAPIView.as_view(),
        name="get_user_notifications",
    ),
    path(
        "notifications/mark-read/",
        views.MarkNotificationReadAPIView.as_view(),
        name="mark_notification_read",
    ),

    # --- External API Fetches ---
    path(
        "attendance/rockhr/",
        views.FetchEmpAttendanceRockHRAPIView.as_view(),
        name="fetch_emp_attendance_rockhr",
    ),
    path(
        "employees/rockhr/",
        views.FetchEmpDetailsRockHRAPIView.as_view(),
        name="fetch_emp_details_rockhr",
    ),
    path(
        "wips/",
        views.FetchWipDataAPIView.as_view(),
        name="fetch_wip_data",
    ),

    # --- Allocation Management ---
    path(
        "employees/allocated/",
        views.UpdateAllocatedEmployeesAPIView.as_view(),
        name="update_allocated_employee",
    ),
    path(
        "employees/on-hold/",
        views.UpdateEmployeeOnHoldAPIView.as_view(),
        name="update_employee_on_hold",
    ),
    path(
        "employees/capacity/",
        views.UpdateAllocatedCapacityAPIView.as_view(),
        name="update_allocated_capacity",
    ),
]


manning_sheet_endpoints = [
    f"/manning-sheet/{pattern.pattern}" for pattern in urlpatterns
]
