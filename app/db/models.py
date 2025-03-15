# app/db/models.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Enum, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, backref
from datetime import datetime
import enum

Base = declarative_base()

# User roles
class UserRole(enum.Enum):
    client = "client"
    admin = "admin"
    superuser = "superuser"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True, nullable=True)  # for clients
    username = Column(String, unique=True, index=True, nullable=True)      # for admin users
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.client, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

# Report processing status
class ReportStatus(enum.Enum):
    pending = "pending"
    success = "success"
    failure = "failure"

class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, nullable=False)
    report_unique_id = Column(String, unique=True, index=True)
    s3_path = Column(String, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    processing_status = Column(Enum(ReportStatus), default=ReportStatus.pending)

    # Add relationship back to HealthParameter
    parameters = relationship("HealthParameter", back_populates="report")

# Health parameter status
class HealthParameterStatus(enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"

class HealthParameter(Base):
    __tablename__ = "health_parameters"
    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    parameter_name = Column(String, nullable=False)
    value = Column(String)
    unit = Column(String)
    reference_range = Column(String)
    method = Column(String)
    status = Column(Enum(HealthParameterStatus), default=HealthParameterStatus.pending)
    created_at = Column(DateTime, default=datetime.utcnow)
    action_timestamp = Column(DateTime)
    approved_by = Column(Integer, nullable=True)
    remarks = Column(Text, nullable=True)
    map_to_existing = Column(String, default="None")

    # Relationship to Report
    report = relationship("Report", back_populates="parameters")
