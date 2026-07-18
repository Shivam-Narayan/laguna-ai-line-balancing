from django.test import TestCase
from datetime import date
from django.utils import timezone
from apps.manning_sheet.models import (
    StyleOB,
    LoadingPlan,
    EMPFact,
    ManningSheetData,
    DDayData,
    ManningGeneralInfo,
    WIPData,
    SkillShortages,
    UnallocatedEmployees,
    EmployeesOnHold,
    PushNotification,
    ActiveEmployees,
    NotificationType
)
from apps.accounts.models import User

class StyleOBModelTest(TestCase):
    def test_creation(self):
        record = StyleOB.objects.create(
            style='S1',
            section='Cutting',
            op_seq=1,
            operation='Cut',
            code='C1',
            sam=1.5
        )
        self.assertEqual(str(record), 'S1')


class LoadingPlanModelTest(TestCase):
    def test_creation(self):
        record = LoadingPlan.objects.create(
            oc_no='OC1',
            merchant='M1',
            style='S1',
            buyer='B1',
            ls_ss='LS',
            fabric_article='FA1',
            smv=2.5,
            month_code='Jan',
            qty_order=100,
            sheet_name='Sheet1',
            line='L1',
            week=1,
            planned_qty=50.0
        )
        self.assertEqual(str(record), 'OC1 - NaN')


class EMPFactModelTest(TestCase):
    def test_creation(self):
        record = EMPFact.objects.create(
            employee_id=1,
            employee_name='Bob',
            line='L1',
            section='Sewing',
            designation='Op',
            code='C1',
            operation='Sew',
            type='Primary',
            sam=1.5,
            peak_capacity=100,
            average_capacity=80,
            machine='SNLS',
            status='Active'
        )
        self.assertEqual(str(record), 'Bob')


class ManningSheetDataModelTest(TestCase):
    def test_creation(self):
        record = ManningSheetData.objects.create(
            oc_no='OC1',
            order_no='OR1',
            buyer='B1',
            style='S1',
            line='L1',
            week=1,
            planned_dates=date.today(),
            planned_qty=100,
            factory='F1',
            floor='FL1',
            workdays=5,
            section='S1',
            op_seq=1,
            operation='Op1',
            code='C1',
            sam=1.0,
            allocated_emp_id=1,
            forecast_period=7
        )
        self.assertEqual(str(record), 'OR1 - S1 - L1')


class DDayDataModelTest(TestCase):
    def test_creation(self):
        record = DDayData.objects.create(
            oc_no='OC1',
            order_no='OR1',
            buyer='B1',
            style='S1',
            line='L1',
            week=1,
            planned_dates=timezone.now(),
            planned_qty=100,
            factory='F1',
            floor='FL1',
            workdays=5,
            section='S1',
            op_seq=1,
            operation='Op1',
            code='C1',
            sam=1.0,
            forecast_period=7
        )
        self.assertEqual(str(record), 'OR1 - Op1')


class ManningGeneralInfoModelTest(TestCase):
    def test_creation(self):
        record = ManningGeneralInfo.objects.create(
            style='S1',
            line='L1',
            section='S1',
            code='C1'
        )
        self.assertEqual(str(record), 'S1 - L1 - C1')


class WIPDataModelTest(TestCase):
    def test_creation(self):
        record = WIPData.objects.create(
            oc_no='OC1',
            order_no='OR1',
            buyer='B1',
            style='S1',
            line='L1',
            color='Black',
            section='S1',
            op_seq=1,
            operation='Op1',
            code='C1',
            wip_qty=50.0
        )
        self.assertEqual(str(record), 'OC1 - OR1')


class SkillShortagesModelTest(TestCase):
    def test_creation(self):
        record = SkillShortages.objects.create(
            line='L1',
            code='C1',
            period=7,
            shortage_qty=5.0
        )
        self.assertEqual(str(record), 'L1 - C1')


class UnallocatedEmployeesModelTest(TestCase):
    def test_creation(self):
        record = UnallocatedEmployees.objects.create(
            date=date.today(),
            employee_id=1,
            employee_name='Charlie'
        )
        self.assertEqual(str(record), '1 - Charlie')


class EmployeesOnHoldModelTest(TestCase):
    def test_creation(self):
        record = EmployeesOnHold.objects.create(
            date=date.today(),
            line='L1',
            section='S1'
        )
        self.assertEqual(str(record), f"{date.today()} - L1 - S1")


class PushNotificationModelTest(TestCase):
    def test_creation(self):
        user = User.objects.create_user(
            username='notifuser',
            email='notif@example.com',
            password='pwd',
            location='A',
            department='B',
            phonenumber='1234'
        )
        record = PushNotification.objects.create(
            notification_type=NotificationType.DDAY_8_50,
            title='Test',
            message='Test message',
            user=user
        )
        self.assertTrue('Test' in str(record))


class ActiveEmployeesModelTest(TestCase):
    def test_creation(self):
        record = ActiveEmployees.objects.create(
            employee_id=1,
            employee_name='Dave'
        )
        self.assertEqual(str(record), '1 - Dave')
