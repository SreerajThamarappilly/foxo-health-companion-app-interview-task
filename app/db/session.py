# app/db/session.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings

# Create engine and sessionmaker (singleton-like per process)
engine = create_engine(settings.SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """
    Dependency function that provides a database session.
    Implements a per-request singleton pattern.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
