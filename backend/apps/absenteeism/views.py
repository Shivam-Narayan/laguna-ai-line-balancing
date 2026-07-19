from django.http import HttpResponse
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated

from apps.accounts.authentication import CookieJWTAuthentication
from apps.accounts.utils.response_handlers import error_response

from .services.data_ingestion_service import (
    run_absenteeism_data_preprocessing,
    run_upload_absenteesim_data,
    run_upload_prediction_data,
)
from .services.export_service import (
    run_export_absenteeism_data,
    run_export_data,
    run_send_csv_via_email,
)
from .services.prediction_orchestrator import (
    run_absenteeism_prediction_data,
    run_absenteeism_prediction_trigger,
    run_get_absenteeism_forecast,
)
from .services.report_service import (
    run_absenteeism_report,
)


@api_view(["POST"])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def upload_absenteesim_data(request):
    file = request.FILES.get("file")
    month = request.POST.get("month")
    year = request.POST.get("year")
    return run_upload_absenteesim_data(file, month, year)


@api_view(["POST"])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def absenteeism_data_preprocessing(request):
    return run_absenteeism_data_preprocessing()


@api_view(["POST"])
def upload_prediction_data(request):
    uploaded_file = request.FILES.get("file")
    return run_upload_prediction_data(uploaded_file)


@api_view(["GET"])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def export_data(request):
    return run_export_data()


@api_view(["GET"])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def export_absenteeism_data(request):
    return run_export_absenteeism_data()


@api_view(["POST"])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def send_csv_via_email(request):
    email = request.data.get("email")
    return run_send_csv_via_email(email)


@api_view(["GET"])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_absenteeism_forecast(request):
    forecast_period = request.GET.get("forecast_period", 7)
    line = request.GET.get("line", "all").upper()
    return run_get_absenteeism_forecast(forecast_period, line)


@api_view(["POST"])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def absenteeism_prediction(request):
    return run_absenteeism_prediction_trigger()


@api_view(["GET", "POST"])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def absenteeism_prediction_data(request):
    line_no = request.query_params.get("line", "").strip()
    forecast_period = request.query_params.get("forecast_period", "").strip()
    get_all = request.query_params.get("get_all", "false").strip().lower() == "true"
    is_export = request.method == "POST"
    export_type = request.query_params.get("type", "").lower()
    email = request.query_params.get("email")
    return run_absenteeism_prediction_data(
        line_no, forecast_period, get_all, is_export, export_type, email
    )


@api_view(["GET"])
@authentication_classes([CookieJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_today_absenteeism_report(request):
    try:
        viaAPI = True
        excel_data, file_name = run_absenteeism_report(viaAPI)
        response = HttpResponse(
            excel_data,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{file_name}"'
        return response
    except Exception as e:
        return error_response(error=str(e), status=500)
