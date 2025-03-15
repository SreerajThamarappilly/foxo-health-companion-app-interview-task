# app/auth/crud.py
from sqlalchemy.orm import Session
from app.db.models import User, UserRole
from passlib.context import CryptContext

# CryptContext for secure password hashing (using bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_user_by_phone(db: Session, phone_number: str):
    return db.query(User).filter(User.phone_number == phone_number).first()

def get_user_by_username(db: Session, username: str):
    return db.query(User).filter(User.username == username).first()

def create_user(db: Session, phone_number: str, username: str, password: str, role: UserRole):
    """
    Creates a new user.
    Follows the Single Responsibility Principle: only responsible for user creation.
    """
    hashed_password = pwd_context.hash(password)
    user = User(
        phone_number=phone_number,
        username=username,
        hashed_password=hashed_password,
        role=role
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def authenticate_user(db: Session, phone_number: str = None, username: str = None, password: str = None):
    user = get_user_by_phone(db, phone_number) if phone_number else get_user_by_username(db, username)
    if not user or not pwd_context.verify(password, user.hashed_password):
        return None
    return user
