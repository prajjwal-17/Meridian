"""Create authentication tables without altering existing Meridian data.

The migration is additive and idempotent. It uses SQLAlchemy's create_all,
which creates only missing tables and leaves existing tables and rows intact.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base, engine
from app import models  # noqa: F401 - registers all mapped tables with Base


if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    print("Authentication migration complete. Existing tables and rows were preserved.")
