# Default libraries
import logging
import os
import sys

def configure_logging(logger_name="", log_level=None):
    """
    Configure logging for the specified logger with the given log level,
    falling back to environment variable if not provided.
    """

    if log_level is None:
        log_level = os.getenv("LOG_LEVEL", "INFO")

    logger = logging.getLogger(logger_name)
    logger.setLevel(log_level)
    # Allow log propagation to enable hybrid logging with Django's global settings
    logger.propagate = True

    # Remove all handlers associated with the root logger
    for console_handler in logger.handlers[:]:
        logger.removeHandler(console_handler)

    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)

    if not logger.handlers:
        logger.addHandler(console_handler)

    return logger
