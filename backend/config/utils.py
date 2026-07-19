from django.db import connection


def truncate_table(model):
    table_name = model._meta.db_table  # Get the actual table name
    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE;")
    print(f"Table {table_name} truncated.")
