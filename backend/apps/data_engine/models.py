from django.db import models

from apps.core.models import BaseModel


class LocalHolidayCalendar(BaseModel):
    objects = models.Manager()
    date = models.DateField()
    month = models.IntegerField()
    year = models.IntegerField()
    day = models.IntegerField()
    week = models.IntegerField()
    event = models.CharField(max_length=100)
    leave_type = models.CharField(max_length=100, default="full")

    class Meta:
        db_table = "local_holiday_calendar"


class HistoricalWeather(BaseModel):
    objects = models.Manager()
    name = models.CharField(max_length=255)
    datetime = models.DateField(db_index=True)
    tempmax = models.FloatField()
    tempmin = models.FloatField()
    temp = models.FloatField()
    feelslikemax = models.FloatField()
    feelslikemin = models.FloatField()
    feelslike = models.FloatField()
    dew = models.FloatField()
    humidity = models.FloatField()
    precip = models.FloatField()
    precipprob = models.FloatField()
    precipcover = models.FloatField(null=True, blank=True)
    preciptype = models.CharField(max_length=255, null=True, blank=True)
    snow = models.FloatField(null=True, blank=True)
    snowdepth = models.FloatField(null=True, blank=True)
    windgust = models.FloatField()
    windspeed = models.FloatField()
    winddir = models.FloatField()
    sealevelpressure = models.FloatField()
    cloudcover = models.FloatField()
    visibility = models.FloatField()
    solarradiation = models.FloatField()
    solarenergy = models.FloatField()
    uvindex = models.IntegerField()
    severerisk = models.IntegerField()
    sunrise = models.DateTimeField()
    sunset = models.DateTimeField()
    moonphase = models.FloatField()
    conditions = models.CharField(max_length=255)
    description = models.TextField(max_length=500)
    icon = models.CharField(max_length=100)
    stations = models.TextField()

    class Meta:
        db_table = "historical_weather"


class EmployeeStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


class EmployeeMaster(BaseModel):
    objects = models.Manager()
    emp_code = models.IntegerField(unique=True, db_index=True)
    emp_name = models.CharField(max_length=100)
    date_of_joining = models.DateField()
    line = models.CharField(max_length=100, null=True, blank=True)
    section = models.CharField(max_length=100, null=True, blank=True)
    designation = models.CharField(max_length=100)
    status = models.CharField(
        max_length=40, choices=EmployeeStatus.choices, default=EmployeeStatus.ACTIVE
    )
    primary = models.CharField(max_length=200, null=True, blank=True)
    secondary = models.CharField(max_length=200, null=True, blank=True)

    class Meta:
        db_table = "employee_master"


class AttendanceMaster(BaseModel):
    objects = models.Manager()
    employee_id = models.IntegerField(db_index=True)
    employee_name = models.CharField(max_length=255)
    line = models.CharField(max_length=50)
    factory = models.CharField(max_length=50)
    floor = models.CharField(max_length=50)
    section = models.CharField(max_length=50)
    attendance_date = models.DateField(db_index=True)
    last_updated = models.TimeField()
    status = models.CharField(max_length=10)  # Assuming "P" stands for Present
    type = models.CharField(max_length=50)  # Assuming "Primary" is a category
    early_departure = models.BooleanField()  # Storing TRUE/FALSE as a boolean

    class Meta:
        db_table = "attendance_master"

    def __str__(self):
        return f"{self.employee_name} - {self.attendance_date}"


class PayableWorkingDays(BaseModel):
    objects = models.Manager()
    date = models.DateField()
    month = models.IntegerField()
    year = models.IntegerField()
    day = models.IntegerField()
    week = models.IntegerField()

    class Meta:
        db_table = "payable_working_days"
