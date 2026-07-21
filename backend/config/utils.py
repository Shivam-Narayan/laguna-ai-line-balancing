import logging

from django.db import connection

logger = logging.getLogger(__name__)


def truncate_table(model):
    table_name = model._meta.db_table  # Get the actual table name
    quoted_name = connection.ops.quote_name(table_name)
    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE TABLE {quoted_name} RESTART IDENTITY CASCADE;")
    logger.info(f"Table {table_name} truncated.")
