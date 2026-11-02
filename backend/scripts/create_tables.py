import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base, engine
from app.models import Document
from app import models
Base.metadata.create_all(bind=engine)

print("Database tables created successfully!")