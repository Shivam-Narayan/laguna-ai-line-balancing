from rest_framework import serializers

from .models import LocalHolidayCalendar


class CalendarSerializer(serializers.ModelSerializer):
    class Meta:
        model = LocalHolidayCalendar
        fields = ["date", "day", "month", "year", "week", "event", "leave_type"]
