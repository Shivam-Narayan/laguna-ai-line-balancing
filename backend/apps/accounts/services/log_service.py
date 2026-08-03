import os
import pathlib
from typing import Optional, Tuple

from django.conf import settings

# Path to logs directory
LOGS_DIR = os.path.join(settings.BASE_DIR, "logs")


def _get_validated_log_path(
    log_filename: str,
) -> Tuple[Optional[str], Optional[str], int]:
    """Validates the log filename and returns the safe path, error, and status code."""
    # Sanitize filename: strip directory components to prevent path traversal
    safe_name = pathlib.Path(log_filename).name
    log_path = os.path.join(LOGS_DIR, f"{safe_name}.log")

    # Double-check the resolved path is still inside LOGS_DIR
    if not os.path.realpath(log_path).startswith(os.path.realpath(LOGS_DIR)):
        return None, "Invalid log filename.", 400

    if not os.path.exists(log_path):
        return None, "Log file not found.", 404

    return log_path, None, 200


def clear_log_file(log_filename: str) -> Tuple[Optional[str], Optional[str], int]:
    """Clears the contents of a log file."""
    log_path, error_msg, status_code = _get_validated_log_path(log_filename)
    if error_msg:
        return None, error_msg, status_code

    try:
        with open(log_path, "w") as log_file:
            log_file.truncate(0)
        safe_name = pathlib.Path(log_filename).name
        return f"{safe_name}.log has been cleared successfully.", None, 200
    except Exception as e:
        return None, f"An error occurred while clearing the log file: {str(e)}", 500


def get_log_file_path(log_filename: str) -> Tuple[Optional[str], Optional[str], int]:
    """Retrieves the safe path for a log file to be downloaded/viewed."""
    log_path, error_msg, status_code = _get_validated_log_path(log_filename)
    if error_msg:
        return None, error_msg, status_code
    return log_path, None, 200
