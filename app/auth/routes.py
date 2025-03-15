# app/auth/routes.py
from fastapi import APIRouter, Depends, Security, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.auth import schemas, crud
from app.db.session import get_db
from app.utils.jwt_utils import create_access_token, verify_token
from datetime import timedelta
from app.config import settings

router = APIRouter()
# Define the security scheme (HTTP Bearer)
bearer_scheme = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)):
    """
    Dependency that extracts and verifies the JWT token from the Authorization header.
    Returns the decoded token payload if valid.
    """
    token = credentials.credentials
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    return payload

@router.post("/signup", response_model=schemas.Token)
def signup(user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    # Check for existing user (by phone or username)
    if user_in.phone_number:
        existing = crud.get_user_by_phone(db, user_in.phone_number)
    else:
        existing = crud.get_user_by_username(db, user_in.username)
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already exists")
    user = crud.create_user(db, user_in.phone_number, user_in.username, user_in.password, user_in.role)
    access_token = create_access_token(
        data={
            "sub": user.phone_number or user.username,
            "role": user.role.value,
            "user_id": user.id,
            "phone_number": user.phone_number
        },
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/login", response_model=schemas.Token)
def login(user_in: schemas.UserLogin, db: Session = Depends(get_db)):
    user = crud.authenticate_user(
        db,
        phone_number=user_in.phone_number,
        username=user_in.username,
        password=user_in.password
    )
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    access_token = create_access_token(
        data={
            "sub": user.phone_number or user.username,
            "role": user.role.value,
            "user_id": user.id,
            "phone_number": user.phone_number
        },
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": access_token, "token_type": "bearer"}
