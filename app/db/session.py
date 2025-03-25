# app/db/session.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings

# Create engine and sessionmaker (singleton-like per process)
# This is a singleton database (shared) engine. SQLAlchemy internally maintains a single Engine per process.
engine = create_engine(settings.SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)
# A factory  (shared) that produces DB sessions bound to the same engine.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """
    Dependency function that provides a database session.
    Dependency injection for FastAPI routes, providing a new session per request and closing it after response.
    Implements a per-request singleton pattern for the engine.
    Each FastAPI request gets its own DB session, used and closed in get_db().
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
