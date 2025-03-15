# app/auth/schemas.py
from pydantic import BaseModel, Field
from enum import Enum

class Role(str, Enum):
    client = "client"
    admin = "admin"
    superuser = "superuser"

class UserCreate(BaseModel):
    phone_number: str = Field(None, example="1234567890")
    username: str = Field(None, example="admin1")
    password: str
    role: Role = Role.client

class UserLogin(BaseModel):
    phone_number: str = Field(None, example="1234567890")
    username: str = Field(None, example="admin1")
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
