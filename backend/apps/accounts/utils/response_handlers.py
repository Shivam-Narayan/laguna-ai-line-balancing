from rest_framework import status  # type:ignore
from rest_framework.response import Response  # type:ignore


def success_response(message="", data=None, status=status.HTTP_200_OK):

    response_data = {
        "status": "success",
        "message": message,
    }
    if data:
        response_data["data"] = data
    return Response(response_data, status=status)


def error_response(error, status=status.HTTP_400_BAD_REQUEST):

    response_data = {
        "status": "error",
        "error": error,
    }
    return Response(response_data, status=status)
