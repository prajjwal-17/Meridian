"""Idempotently add external source identity fields to documents."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text

from app.database import engine

CONSTRAINT_NAME = "uq_document_source_identity"


def add_column(connection, column: str, definition: str) -> bool:
    columns = {
        item["name"]
        for item in inspect(connection).get_columns("documents")
    }
    if column in columns:
        return False
    connection.execute(
        text(f"ALTER TABLE documents ADD COLUMN {column} {definition}")
    )
    return True


def source_constraint_exists(connection) -> bool:
    for constraint in inspect(connection).get_unique_constraints("documents"):
        if constraint.get("name") == CONSTRAINT_NAME:
            return True
        if set(constraint.get("column_names") or []) == {
            "source_name",
            "source_document_id",
        }:
            return True
    return False


with engine.begin() as connection:
    changed = []
    if add_column(connection, "source_name", "VARCHAR(100)"):
        changed.append("added documents.source_name")
    if add_column(connection, "source_document_id", "VARCHAR(255)"):
        changed.append("added documents.source_document_id")

    if not source_constraint_exists(connection):
        connection.execute(
            text(
                "ALTER TABLE documents ADD CONSTRAINT "
                f"{CONSTRAINT_NAME} UNIQUE "
                "(source_name, source_document_id)"
            )
        )
        changed.append(f"added constraint {CONSTRAINT_NAME}")

if changed:
    print("Source identity migration changes:")
    for item in changed:
        print(f"  - {item}")
else:
    print("Source identity migration: no changes needed.")
