import pytest
from unittest.mock import patch
from rest_framework import status
from apps.data_engine.models import EmployeeMaster
from apps.manning_sheet.models import ActiveEmployees, EMPFact
from apps.data_engine.services.employee_service import (
    run_operators_data,
    run_generate_employee_master,
)


@pytest.mark.django_db
class TestEmployeeService:
    def test_run_operators_data_missing_line(self):
        response = run_operators_data(None)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Line is required" in response.data["error"]

    def test_run_operators_data_invalid_line(self):
        response = run_operators_data("invalid_line")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Enter valid line number" in response.data["error"]

    def test_run_operators_data_no_data(self):
        # Database is empty
        response = run_operators_data("line 1")
        assert response.status_code == status.HTTP_200_OK
        assert "No data found for line 1" in response.data["error"]

    def test_run_operators_data_success(self):
        # Create some test data
        EmployeeMaster.objects.create(
            emp_code=1001,
            emp_name="John Doe",
            date_of_joining="2022-01-01",
            line="Line 1",
            section="Section A",
            designation="Operator",
            status="active"
        )
        EmployeeMaster.objects.create(
            emp_code=1002,
            emp_name="Jane Smith",
            date_of_joining="2022-02-01",
            line="Line 2",
            section="Section B",
            designation="Supervisor",
            status="active"
        )

        response = run_operators_data("line 1")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["message"] == "Data for line 1 fetched successfully."
        assert len(response.data["data"]) == 1
        assert response.data["data"][0]["emp_name"] == "John Doe"

    def test_run_operators_data_all_lines(self):
        EmployeeMaster.objects.create(
            emp_code=1001,
            emp_name="John Doe",
            date_of_joining="2022-01-01",
            line="Line 1",
            section="Section A",
            designation="Operator",
            status="active"
        )
        EmployeeMaster.objects.create(
            emp_code=1002,
            emp_name="Jane Smith",
            date_of_joining="2022-02-01",
            line="Line 2",
            section="Section B",
            designation="Supervisor",
            status="active"
        )

        response = run_operators_data("all")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["data"]) == 2

    @patch("apps.data_engine.services.employee_service.is_allowed_working_day")
    def test_run_generate_employee_master_not_working_day(self, mock_is_allowed):
        mock_is_allowed.return_value = (False, "Holiday")
        response = run_generate_employee_master()
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Skipping for" in response.data["error"]

    @patch("apps.data_engine.services.employee_service.is_allowed_working_day")
    def test_run_generate_employee_master_success(self, mock_is_allowed):
        mock_is_allowed.return_value = (True, "")
        
        # Create active employee
        ActiveEmployees.objects.create(
            employee_id=123,
            employee_name="Alice Worker",
            line="line 1",
            section="stitching",
            designation="tailor",
        )
        
        # Create corresponding emp facts
        EMPFact.objects.create(
            employee_id=123,
            employee_name="Alice Worker",
            line="line 1",
            section="stitching",
            designation="tailor",
            code="OP1",
            operation="Sewing",
            type="primary",
            sam=1.5,
            peak_capacity=100,
            average_capacity=80,
            machine="Juki",
            status="active",
        )
        EMPFact.objects.create(
            employee_id=123,
            employee_name="Alice Worker",
            line="line 1",
            section="stitching",
            designation="tailor",
            code="OP2",
            operation="Checking",
            type="secondary",
            sam=0.5,
            peak_capacity=100,
            average_capacity=80,
            machine="Manual",
            status="active",
        )

        response = run_generate_employee_master()
        assert response.status_code == status.HTTP_200_OK
        assert response.data["message"] == "Employee Master data is generated successfully."

        # Verify EmployeeMaster table has been populated correctly
        emp_master = EmployeeMaster.objects.get(emp_code=123)
        assert emp_master.emp_name == "Alice Worker"
        assert emp_master.line == "LINE 1" # Capitalized by the code
        assert emp_master.section == "Stitching" # Title cased by the code
        assert emp_master.primary == "Sewing"
        assert emp_master.secondary == "Checking"
        assert emp_master.status == "active"
