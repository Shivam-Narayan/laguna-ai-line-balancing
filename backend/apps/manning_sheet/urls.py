from . import views
from django.urls import path

urlpatterns = [
    path('style-obs/upload/', views.styleob_file_upload, name='uploading style ob data'),
    path('loading-plans/upload/', views.loading_plan_file_upload, name='uploading Uploading ob data'),
    path('emp-facts/upload/', views.emp_fact_file_upload, name='uploading Emp Fact data'),
    path('wips/upload-file/', views.wip_file_upload, name='uploading WIP data'),
    path('manning-sheets/generate/', views.manning_allocation, name='Generating Manning Sheet'),
    path('manning-sheets/', views.get_manning_data, name='get manning data'),
    path('manning-sheets/export/', views.download_manning_data_by_section, name='get manning data'),
    path('manning-sheets/d-day/generate/', views.generate_dday_manning_data, name='Generating Dday Manning Sheet'),
    path('manning-sheets/d-day/', views.get_dday_manning_data, name='get Dday manning data'),
    path('attendance/', views.get_attendance_data, name='get Attendance data'),
    path('attendance/export/', views.download_manning_attendance_data, name='Download Dday and Attendance data'),
    path('emp-facts/generate/', views.generate_emp_fact, name='generate_emp_fact'), # To fetch and populate EMPFact   
    path('notifications/', views.get_user_notifications, name='get_user_notifications'),
    path('notifications/download/', views.download_notification_file, name='download_notification_file'),
    path('notifications/mark-read/', views.mark_notification_read, name='mark_notification_read'),
    path('style-obs/generate/', views.generate_style_ob, name='generate_style_ob'),
    path('employees/unallocated/', views.get_unallocated_employees, name='get_unallocated_employees'),
    path('attendance/rockhr/', views.fetch_emp_attendance_rockhr, name='fetch_emp_attendance_rockhr'),
    path('employees/rockhr/', views.fetch_emp_details_rockhr, name='fetch_emp_details_rockhr'),
    # path('wips/', views.fetch_wip_data, name='fetch_wip_data'), # For testing
    path('wips/', views.fetch_wip_data_api, name='fetch_wip_data'), # For testing
    path('employees/allocated/', views.update_allocated_employees, name='update_allocated_employee'),
    path('employees/on-hold/', views.update_employee_on_hold, name='update_employee_on_hold'),
    path('planned-leaves/upload/', views.uploading_planned_leaves, name='uploading_planned_leaves'),
    path('employees/unallocated/d-day/', views.get_unallocated_employees_dday, name='get_unallocated_employees_dday'),
    path('employees/capacity/', views.update_allocated_capacity, name='update_allocated_capacity'),
    path('wips/upload/', views.upload_wip_data, name='upload_wip_data'),

    path('wips/bulk/', views.add_bulk_wip_data, name='add_bulk_wip_data'),
]


manning_sheet_endpoints = [
    f"/manning-sheet/{pattern.pattern}" for pattern in urlpatterns
]