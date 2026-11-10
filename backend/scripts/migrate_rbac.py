"""Idempotently add multi-value document ACL columns for RBAC integration."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text

from app.database import engine


def add_column(connection, column: str) -> None:
    columns = {item["name"] for item in inspect(connection).get_columns("documents")}
    if column not in columns:
        connection.execute(text(f"ALTER TABLE documents ADD COLUMN {column} JSON"))


if __name__ == "__main__":
    with engine.begin() as connection:
        add_column(connection, "permission_teams")
        add_column(connection, "permission_departments")
    print("RBAC migration complete. Existing document ACL values were preserved.")
