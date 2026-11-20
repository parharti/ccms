"""
Database engine + session setup.

Set the DATABASE_URL environment variable, or the default local Postgres
connection below will be used (replace it with your actual credentials).
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/ihmcl_hr",
)

# Hosted providers (Aiven, Render, Heroku) hand out "postgres://..." URIs,
# which SQLAlchemy rejects -- accept them as-is so the URI can be pasted
# straight from the provider's console.
for _prefix in ("postgres://", "postgresql://"):
    if DATABASE_URL.startswith(_prefix):
        DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[len(_prefix):]
        break

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency -- provides a DB session per request, and
    closes it automatically once the request is done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
