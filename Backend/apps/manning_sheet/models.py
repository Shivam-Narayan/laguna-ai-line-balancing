from django.db import models

class StyleOB(models.Model):
    style = models.CharField(max_length=255)
    section = models.CharField(max_length=255)
    op_seq = models.IntegerField()
    operation = models.CharField(max_length=255)
    code = models.CharField(max_length=255)
    sam = models.FloatField()
    # color = models.CharField(max_length=255, default="Black")
    machine_type = models.CharField(max_length=255, default="Machine Type")
    machinist = models.CharField(max_length=255, default='False')

    class Meta:
        db_table = 'style_ob'

    def __str__(self):
        return self.style
    
class LoadingPlan(models.Model):
    oc_no = models.CharField(max_length=255)
    order_no = models.CharField(max_length=255, default='NaN')
    cfm_date = models.DateField(null=True, blank=True)
    merchant = models.CharField(max_length=255)
    style = models.CharField(max_length=255)
    buyer = models.CharField(max_length=255)
    ls_ss = models.CharField(max_length=255)
    fabric_article = models.CharField(max_length=255)
    smv = models.FloatField()
    del_date = models.DateField(null=True, blank=True)
    month_code = models.CharField(max_length=255)
    qty_order = models.IntegerField()
    sheet_name = models.CharField(max_length=255)
    line = models.CharField(max_length=255)
    week = models.IntegerField()
    planned_qty = models.FloatField()
    date_start = models.DateField(null=True, blank=True)
    date_end = models.DateField(null=True, blank=True)
    planned_dates = models.DateField(null=True, blank=True)
    raw_oc_no = models.CharField(max_length=255, null=True, blank=True)
    raw_style = models.CharField(max_length=255, null=True, blank=True)
    raw_fabric_article = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = 'loading_plan'

    def __str__(self):
        return f"{self.oc_no} - {self.order_no}"

class EMPFact(models.Model):
    employee_id = models.IntegerField()
    employee_name = models.CharField(max_length=255)
    line = models.CharField(max_length=255)
    section = models.CharField(max_length=255)
    designation = models.CharField(max_length=255)
    code = models.CharField(max_length=255)
    operation = models.CharField(max_length=255)
    type = models.CharField(max_length=255)
    sam = models.FloatField()
    peak_capacity = models.IntegerField()
    average_capacity = models.IntegerField()
    machine = models.CharField(max_length=255)
    status = models.CharField(max_length=255)
    factory = models.CharField(max_length=255, default='Factory 1')
    floor = models.CharField(max_length=255, default='Floor 1')

    class Meta:
        db_table = 'emp_fact'

    def __str__(self):
        return self.employee_name
    
class ManningSheetData(models.Model):
    oc_no = models.CharField(max_length=255)
    order_no = models.CharField(max_length=255)
    buyer = models.CharField(max_length=255)
    style = models.CharField(max_length=255)
    line = models.CharField(max_length=255)
    week = models.IntegerField()
    planned_dates = models.DateField()
    planned_qty = models.FloatField()
    factory = models.CharField(max_length=255)
    floor = models.CharField(max_length=255)
    workdays = models.IntegerField()
    # id = models.IntegerField()
    section = models.CharField(max_length=255)
    op_seq = models.IntegerField()
    operation = models.CharField(max_length=255)
    code = models.CharField(max_length=255)
    sam = models.FloatField()
    smv = models.FloatField(default=0)
    allocated_emp_id = models.IntegerField()
    allocated_emp_name = models.CharField(max_length=255, null=True, blank=True)
    allocated_capacity = models.FloatField(null=True, blank=True)
    allocated_frm_line = models.CharField(max_length=255, null=True, blank=True)
    allocated_frm_factory = models.CharField(max_length=255, null=True, blank=True)
    allocated_frm_floor = models.CharField(max_length=255, null=True, blank=True)
    skill_type = models.CharField(max_length=255, null=True, blank=True)
    machine = models.CharField(max_length=255, null=True, blank=True)
    shortage_flag = models.CharField(max_length=255, null=True, blank=True)
    designation = models.CharField(max_length=255, null=True, blank=True)
    target_100 = models.FloatField(null=True, blank=True)
    target_90 = models.FloatField(null=True, blank=True)
    # buyer_y = models.CharField(max_length=255, null=True, blank=True)
    forecast_period = models.IntegerField()
    shortage_reason = models.CharField(max_length=255, null=True, blank=True)
    split_order_id = models.CharField(max_length=255, null=True, blank=True)
    machine_type = models.CharField(max_length=255, default="Machine Type")
    machinist = models.CharField(max_length=255, default='False')
    color = models.CharField(max_length=255, default='Black')
    raw_oc_no = models.CharField(max_length=255, null=True, blank=True)
    raw_style = models.CharField(max_length=255, null=True, blank=True)
    raw_color = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = 'manning_sheet_data'
    
    def __str__(self):
        return f"{self.order_no} - {self.style} - {self.line}"


class DDayData(models.Model):
    id = models.AutoField(primary_key=True)
    oc_no = models.CharField(max_length=255)
    order_no = models.CharField(max_length=255)
    buyer = models.CharField(max_length=255)
    style = models.CharField(max_length=255)
    line = models.CharField(max_length=255)
    week = models.IntegerField()
    planned_dates = models.DateTimeField()
    planned_qty = models.FloatField()
    factory = models.CharField(max_length=255)
    floor = models.CharField(max_length=255)
    workdays = models.IntegerField()
    section = models.CharField(max_length=255)
    op_seq = models.IntegerField()
    operation = models.CharField(max_length=255)
    code = models.CharField(max_length=50)
    sam = models.FloatField()
    allocated_emp_id = models.IntegerField(null=True, blank=True)
    allocated_emp_name = models.CharField(max_length=255, null=True, blank=True)
    allocated_capacity = models.FloatField(null=True, blank=True)
    allocated_frm_line = models.CharField(max_length=255, null=True, blank=True)
    allocated_frm_factory = models.CharField(max_length=255, null=True, blank=True)
    allocated_frm_floor = models.CharField(max_length=255, null=True, blank=True)
    skill_type = models.CharField(max_length=255, null=True, blank=True)
    machine = models.CharField(max_length=255, null=True, blank=True)
    shortage_flag = models.CharField(max_length=255, null=True, blank=True)
    designation = models.CharField(max_length=255, null=True, blank=True)
    target_100 = models.FloatField(null=True, blank=True)
    target_90 = models.FloatField(null=True, blank=True)
    # buyer_y = models.CharField(max_length=255, null=True, blank=True)
    forecast_period = models.IntegerField()
    run_history = models.JSONField(default=list, blank=True)
    current_run = models.JSONField(null=True, blank=True)
    original_emp = models.CharField(max_length=255, null=True, blank=True)
    new_emp = models.CharField(max_length=255, null=True, blank=True)
    reallocation_level = models.CharField(max_length=255, null=True, blank=True)
    re_allocated_employee = models.CharField(max_length=255, null=True, blank=True)
    preferred_employees = models.TextField(null=True, blank=True)  # Storing as text, can be parsed as needed
    shortage_reason = models.CharField(max_length=255, null=True, blank=True)
    split_order_id = models.CharField(max_length=255, null=True, blank=True)
    reallocation_reason = models.CharField(max_length=255, null=True, blank=True)
    machine_type = models.CharField(max_length=255, default="Machine Type", null=True, blank=True)
    machinist = models.CharField(max_length=255, default='False', null=True, blank=True)
    color = models.CharField(max_length=255, default="Black", null=True, blank=True)
    backlog_flag = models.CharField(max_length=255, default='Back Log', null=True, blank=True)
    original_emp_name = models.CharField(max_length=255, default='Original Employee Name', null=True, blank=True)
    original_planned_qty = models.FloatField(default=0, null=True, blank=True)
    average_capacity_per_hour = models.FloatField(default=0, null=True, blank=True)
    attendance_status = models.CharField(max_length=255, default='P', null=True, blank=True)
    smv = models.FloatField(default=0, null=True, blank=True)
    final_allocation = models.TextField(null=True, blank=True)  # Storing as text, can be parsed as needed
    wip_quantity = models.FloatField(default=0, null=True, blank=True)

    class Meta:
        db_table = 'dday_manning_data'

    def __str__(self):
        return f"{self.order_no} - {self.operation}"
    
    
class ManningGeneralInfo(models.Model):
    style = models.CharField(max_length=255)
    line = models.CharField(max_length=50)
    section = models.CharField(max_length=100)
    code = models.CharField(max_length=50)
    planned_qty = models.IntegerField(null=True, blank=True)
    allocated_capacity = models.IntegerField(null=True, blank=True)
    shortage_capacity = models.IntegerField(null=True, blank=True)
    forecast_period = models.IntegerField(null=True, blank=True)
    median_average_capacity = models.FloatField(null=True, blank=True)
    section_average_capacity = models.FloatField(null=True, blank=True)
    total_active_operators = models.IntegerField(null=True, blank=True)
    machinist_available = models.FloatField(null=True, blank=True)
    non_machinist_available = models.FloatField(null=True, blank=True)
    total_operators_required = models.FloatField(null=True, blank=True)
    machinist_required = models.FloatField(null=True, blank=True)
    non_machinist_required = models.FloatField(null=True, blank=True)
    machine = models.CharField(max_length=100, null=True, blank=True)
    planned_dates = models.DateField(null=True, blank=True)
    
    class Meta:
        db_table = 'manning_general_info'

    def __str__(self):
        return f"{self.style} - {self.line} - {self.code}"


class WIPData(models.Model):
    oc_no = models.CharField(max_length=255)
    order_no = models.CharField(max_length=255)
    buyer = models.CharField(max_length=255)
    style = models.CharField(max_length=255)
    line = models.CharField(max_length=255)
    color = models.CharField(max_length=255)
    section = models.CharField(max_length=255)
    op_seq = models.IntegerField()
    operation = models.CharField(max_length=255)
    code = models.CharField(max_length=50)
    wip_qty = models.FloatField()

    class Meta:
        db_table = 'wip_data'

    def __str__(self):
        return f"{self.oc_no} - {self.order_no}"
    


class SkillShortages(models.Model):
    line = models.CharField(max_length=255, null=True, blank=True)
    code = models.CharField(max_length=255, null=True, blank=True)
    period = models.IntegerField(null=True, blank=True)
    shortage_qty = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = 'skill_shortages'

    def __str__(self):
        return f"{self.line} - {self.code}"
    


class UnallocatedEmployees(models.Model):
    date = models.DateField()
    employee_id = models.IntegerField(null=True, blank=True)
    employee_name = models.CharField(max_length=255, null=True, blank=True)
    line = models.CharField(max_length=255, null=True, blank=True)
    section = models.CharField(max_length=255, null=True, blank=True)
    code = models.CharField(max_length=255, null=True, blank=True)
    type = models.CharField(max_length=255, null=True, blank=True)
    initial_capacity = models.FloatField(null=True, blank=True)
    remaining_capacity = models.FloatField(null=True, blank=True)
    utilization_pct = models.FloatField(null=True, blank=True)
    reason = models.CharField(max_length=5000, null=True, blank=True)
    category = models.CharField(max_length=500, null=True, blank=True)
    period = models.IntegerField(null=True, blank=True)
    designation = models.CharField(max_length=255, blank=True, null=True)


    class Meta:
        db_table = 'unallocated_employees'

    def __str__(self):
        return f"{self.employee_id} - {self.employee_name}"


class EmployeesOnHold(models.Model):
    date = models.DateField()
    line = models.CharField(max_length=255, null=True, blank=True)
    section = models.CharField(max_length=255, null=True, blank=True)
    code = models.CharField(max_length=255, null=True, blank=True)
    preferred_employees = models.TextField(null=True, blank=True)  # Storing as text, can be parsed as needed
    count = models.IntegerField(null=True, blank=True)
    class Meta:
        db_table = 'employees_on_hold'

    def __str__(self):
        return f"{self.date} - {self.line} - {self.section}"


class PushNotification(models.Model):
    NOTIFICATION_TYPES = (
        ('dday_8_50', 'D-Day 8:50 AM Allocation Notification'),
        ('dday_12_45', 'D-day 12:45 PM Allocation Data'),
        ('dday_5_30', 'D-Day 5:30 PM Allocation Notification'),
        ('manning_sheet', 'Manning Sheet Allocation Notification'),
        ('absenteeism_prediction', 'Absenteeism Prediction Data'),
    )
    
    notification_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPES)
    title = models.CharField(max_length=255)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='notifications')
    data = models.JSONField(null=True, blank=True)  # Additional data for the notification
    
    class Meta:
        db_table = 'push_notifications'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.notification_type} - {self.title} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"    
    



class ActiveEmployees(models.Model):
    employee_id = models.IntegerField(null=True, blank=True)
    employee_name = models.CharField(max_length=255, null=True, blank=True)
    line = models.CharField(max_length=255, null=True, blank=True)
    section = models.CharField(max_length=255, null=True, blank=True)
    designation = models.CharField(max_length=255, null=True, blank=True)
    machinist = models.CharField(max_length=255, default='False')
    service_years = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=255, null=True, blank=True)
    gender = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = 'active_employees'

    def __str__(self):
        return f"{self.employee_id} - {self.employee_name}"