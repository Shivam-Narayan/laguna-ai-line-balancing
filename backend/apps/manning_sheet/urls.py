from . import views
from django.urls import path

urlpatterns = [
    path('uploading_styleob_data/', views.styleob_file_upload, name='uploading style ob data'),
    path('uploading_loading_data/', views.loading_plan_file_upload, name='uploading Uploading ob data'),
    path('uploading_emp_fact_data/', views.emp_fact_file_upload, name='uploading Emp Fact data'),
    path('uploading_wip_data/', views.wip_file_upload, name='uploading WIP data'),
    path('generate_manning_sheet/', views.manning_allocation, name='Generating Manning Sheet'),
    path('get_manning_data/', views.get_manning_data, name='get manning data'),
    path('download_manning_data_by_section/', views.download_manning_data_by_section, name='get manning data'),
    path('generate_dday_manning_sheet/', views.generate_dday_manning_data, name='Generating Dday Manning Sheet'),
    path('get_dday_manning_data/', views.get_dday_manning_data, name='get Dday manning data'),
    path('get_attendance_data/', views.get_attendance_data, name='get Attendance data'),
    path('download_manning_attendance_data/', views.download_manning_attendance_data, name='Download Dday and Attendance data'),
    path('generate_emp_fact/', views.generate_emp_fact, name='generate_emp_fact'), # To fetch and populate EMPFact   
    path('notifications/', views.get_user_notifications, name='get_user_notifications'),
    path('notifications/download_file/', views.download_notification_file, name='download_notification_file'),
    path('notifications/mark-read/', views.mark_notification_read, name='mark_notification_read'),
    path('generate_style_ob', views.generate_style_ob, name='generate_style_ob'),
    path('get_unallocated_employees', views.get_unallocated_employees, name='get_unallocated_employees'),
    path('fetch_emp_attendance_rockhr', views.fetch_emp_attendance_rockhr, name='fetch_emp_attendance_rockhr'),
    path('fetch_emp_details_rockhr', views.fetch_emp_details_rockhr, name='fetch_emp_details_rockhr'),
    # path('fetch_wip_data', views.fetch_wip_data, name='fetch_wip_data'), # For testing
    path('fetch_wip_data', views.fetch_wip_data_api, name='fetch_wip_data'), # For testing
    path('update_allocated_employees', views.update_allocated_employees, name='update_allocated_employee'),
    path('update_employee_on_hold', views.update_employee_on_hold, name='update_employee_on_hold'),
    path('uploading_planned_leaves', views.uploading_planned_leaves, name='uploading_planned_leaves'),
    path('get_unallocated_employees_dday', views.get_unallocated_employees_dday, name='get_unallocated_employees_dday'),
    path('update_allocated_capacity', views.update_allocated_capacity, name='update_allocated_capacity'),
    path('upload_wip_data', views.upload_wip_data, name='upload_wip_data'),

    path('add_bulk_wip_data', views.add_bulk_wip_data, name='add_bulk_wip_data'),
]


manning_sheet_endpoints = [
    f"/manning-sheet/{pattern.pattern}" for pattern in urlpatterns
]