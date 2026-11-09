"""Idempotently add ACL columns without deleting or recreating data."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text

from app.database import engine


def add_column(connection, table: str, column: str, definition: str) -> None:
    columns = {item["name"] for item in inspect(connection).get_columns(table)}
    if column not in columns:
        connection.execute(
            text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        )


with engine.begin() as connection:
    add_column(connection, "documents", "permission_tier", "VARCHAR(20)")
    add_column(connection, "documents", "permission_team", "VARCHAR(100)")
    add_column(connection, "documents", "permission_department", "VARCHAR(100)")
    add_column(connection, "documents", "restricted_user_ids", "JSON")
    add_column(connection, "document_chunks", "permission_tier", "VARCHAR(20)")

    # Existing records without known permissions become deny-by-default.
    # Existing non-null assignments are never overwritten.
    connection.execute(
        text("UPDATE documents SET permission_tier = 'restricted' "
             "WHERE permission_tier IS NULL")
    )
    connection.execute(
        text(
            "UPDATE document_chunks AS c SET permission_tier = d.permission_tier "
            "FROM documents AS d WHERE c.document_id = d.id "
            "AND c.permission_tier IS NULL"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_documents_permission_tier "
            "ON documents (permission_tier)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_permission_tier "
            "ON document_chunks (permission_tier)"
        )
    )

print(
    "ACL migration complete. Existing documents without ACL metadata are "
    "restricted with no allow-list and therefore inaccessible until classified."
)
