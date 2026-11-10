import sys
import inspect as pyinspect
from pathlib import Path

# Add backend directory to Python import path.
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import inspect, text
from app.database import engine
from app.models import (
    Document,
    DocumentChunk,
    Entity,
    ChunkEntityMention,
    EntityRelationship
)

print("\n========== MERIDIAN DATABASE SCHEMA ==========")

models = [
    Document,
    DocumentChunk,
    Entity,
    ChunkEntityMention,
    EntityRelationship
]

for model in models:

    print(f"\nTABLE: {model.__tablename__}")

    for column in model.__table__.columns:

        print(
            f"  {column.name} | "
            f"Type: {column.type} | "
            f"Nullable: {column.nullable} | "
            f"Default: {column.default}"
        )

print("\n========== DATABASE TABLES ==========")

db_inspector = inspect(engine)

for table_name in db_inspector.get_table_names():

    print(f"\nTable: {table_name}")

    with engine.connect() as connection:
        count = connection.execute(
            text(f'SELECT COUNT(*) FROM "{table_name}"')
        ).scalar()

    print(f"Rows: {count}")

print("\n========== DOCUMENT PROCESSOR ==========")

try:
    from app import document_processor

    for name, obj in vars(document_processor).items():

        if pyinspect.isfunction(obj) and not name.startswith("_"):

            print(f"\nFunction: {name}")
            print(pyinspect.signature(obj))

except Exception as error:
    print("Could not inspect document processor:", error)

print("\n========== INSPECTION COMPLETE ==========")

print("\n========== MODEL RELATIONSHIPS ==========")

for model in models:

    print(f"\nMODEL: {model.__name__}")

    for relationship in model.__mapper__.relationships:
        print(
            f"Relationship: {relationship.key} "
            f"-> {relationship.mapper.class_.__name__}"
        )

    for constraint in model.__table__.constraints:
        print(
            f"Constraint: {constraint}"
        )

print("\n========== INDEXES ==========")

for model in models:

    print(f"\nTABLE: {model.__tablename__}")

    for index in model.__table__.indexes:
        print(
            f"Index: {index.name} | "
            f"Columns: {[column.name for column in index.columns]}"
        )