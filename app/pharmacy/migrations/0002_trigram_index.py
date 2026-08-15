"""Postgres trigram GIN index — `LIKE '%query%'` ni table scan'siz qiladi.

13k+ qator bo'yicha `name_normalized__icontains` so'rovi 10-20x tezlashadi.
SQLite (dev) da skip qilinadi — production env-driven PostgreSQL.
"""

from django.db import migrations


def create_trgm_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return  # SQLite dev — skip
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS pharmacy_drug_name_normalized_trgm_idx "
            "ON pharmacy_drug USING gin (name_normalized gin_trgm_ops);"
        )


def drop_trgm_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP INDEX IF EXISTS pharmacy_drug_name_normalized_trgm_idx;"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("pharmacy", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_trgm_index, drop_trgm_index),
    ]
