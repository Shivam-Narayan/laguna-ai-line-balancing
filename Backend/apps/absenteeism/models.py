from django.db import models


class Absenteeism(models.Model):
    date = models.DateField(verbose_name="Date")
    empcode = models.CharField(max_length=20, verbose_name="Employee Code")
    name = models.CharField(null=True, max_length=100, verbose_name="Employee Name")
    department = models.CharField(null=True, max_length=100, verbose_name="Department")
    doj = models.DateField(null=True, verbose_name="Date of Joining")
    attendance = models.CharField(max_length=30, default='A')
    P = models.IntegerField(null=True, default=0, verbose_name="Present Days")
    WO = models.IntegerField(null=True, default=0, verbose_name="Weekly Offs")
    H = models.IntegerField(null=True, default=0, verbose_name="Holidays")
    L = models.IntegerField(null=True, default=0, verbose_name="Leaves")
    Ab = models.IntegerField(null=True, default=0, verbose_name="Absent Days")
    DP = models.IntegerField(null=True, default=0, verbose_name="Double Present")
    OT1 = models.IntegerField(null=True, default=0, verbose_name="Overtime Hours")
    
    
    class Meta:
        db_table = 'absenteeism_master'
        ordering = ["-date"]  # Orders by latest date first

    def __str__(self):
        return f"{self.name} ({self.empcode}) - {self.date}"
    
class PredictionData(models.Model):
    date = models.DateField(verbose_name="Date")
    empcode = models.CharField(max_length=20, verbose_name="Employee Code")
    name = models.CharField(max_length=100, verbose_name="Employee Name")
    department = models.CharField(max_length=100, verbose_name="Department")
    section = models.CharField(max_length=100, null=True, verbose_name="Section")
    attendance = models.CharField(max_length=30, default='A')
    

    class Meta:
        db_table = 'absenteeism_data'

    def __str__(self):
        return f"{self.name} ({self.empcode}) - {self.date}"
    
class AbsenteeismPrediction(models.Model):
    datetime = models.DateField()
    day_of_week = models.CharField(max_length=25, default='NA')
    predicted_absent_count = models.FloatField()
    line = models.CharField(max_length=100)
    section = models.CharField(max_length=100)
    forecast_period = models.IntegerField()
    historical_mean = models.FloatField()
    historical_std = models.FloatField()
    deviation_from_mean = models.FloatField()
    
    class Meta:
        db_table = 'absenteeism_prediction'

    def __str__(self):
        return f"{self.datetime} - {self.line} - {self.section}"
