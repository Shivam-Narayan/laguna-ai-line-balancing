from django.db import models

from apps.core.models import BaseModel


class Absenteeism(BaseModel):
    objects = models.Manager()
    date = models.DateField(verbose_name="Date", db_index=True)
    empcode = models.CharField(
        max_length=20, verbose_name="Employee Code", db_index=True
    )
    name = models.CharField(
        blank=True, null=True, max_length=100, verbose_name="Employee Name"
    )
    department = models.CharField(
        blank=True, null=True, max_length=100, verbose_name="Department", db_index=True
    )
    doj = models.DateField(null=True, verbose_name="Date of Joining")
    attendance = models.CharField(max_length=30, default="A")
    present_days = models.IntegerField(
        null=True, default=0, verbose_name="Present Days"
    )
    weekly_offs = models.IntegerField(null=True, default=0, verbose_name="Weekly Offs")
    holidays = models.IntegerField(null=True, default=0, verbose_name="Holidays")
    leaves = models.IntegerField(null=True, default=0, verbose_name="Leaves")
    absent_days = models.IntegerField(null=True, default=0, verbose_name="Absent Days")
    double_present = models.IntegerField(
        null=True, default=0, verbose_name="Double Present"
    )
    overtime_hours = models.IntegerField(
        null=True, default=0, verbose_name="Overtime Hours"
    )

    class Meta:
        db_table = "absenteeism_master"
        ordering = ["-date"]  # Orders by latest date first
        constraints = [
            models.UniqueConstraint(fields=["date", "empcode"], name="unique_absenteeism_date_empcode")
        ]

    def __str__(self):
        return f"{self.name} ({self.empcode}) - {self.date}"


class PredictionData(BaseModel):
    objects = models.Manager()
    date = models.DateField(verbose_name="Date", db_index=True)
    empcode = models.CharField(max_length=20, verbose_name="Employee Code", db_index=True)
    name = models.CharField(max_length=100, verbose_name="Employee Name")
    department = models.CharField(
        max_length=100, verbose_name="Department", db_index=True
    )
    section = models.CharField(
        max_length=100, null=True, verbose_name="Section", db_index=True
    )
    attendance = models.CharField(max_length=30, default="A")

    class Meta:
        db_table = "absenteeism_data"
        constraints = [
            models.UniqueConstraint(fields=["date", "empcode"], name="unique_prediction_data_date_empcode")
        ]

    def __str__(self):
        return f"{self.name} ({self.empcode}) - {self.date}"


class AbsenteeismPrediction(BaseModel):
    objects = models.Manager()
    datetime = models.DateField(db_index=True)
    day_of_week = models.CharField(max_length=25, default="NA")
    predicted_absent_count = models.FloatField()
    line = models.CharField(max_length=100, db_index=True)
    section = models.CharField(max_length=100, db_index=True)
    forecast_period = models.IntegerField()
    historical_mean = models.FloatField()
    historical_std = models.FloatField()
    deviation_from_mean = models.FloatField()

    class Meta:
        db_table = "absenteeism_prediction"
        constraints = [
            models.UniqueConstraint(
                fields=["datetime", "line", "section", "forecast_period"],
                name="unique_absenteeism_prediction"
            )
        ]

    def __str__(self):
        return f"{self.datetime} - {self.line} - {self.section}"
