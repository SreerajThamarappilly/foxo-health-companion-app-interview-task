# app/admin/routes.py
from fastapi import Request, APIRouter, Depends, HTTPException, status, Form, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from app.db.session import get_db
from app.db.models import User, Report, HealthParameter, HealthParameterStatus
from app.auth.routes import get_current_user
from app.pdf import s3_utils
from app.db.models import Report
from celery_worker import extract_pdf_task
from datetime import datetime
import os
from typing import List

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))

# Dummy dependency for admin user verification.
def get_current_admin_user():
    # In a real application, verify the JWT token and fetch the admin's info.
    # Here we return a dummy admin with an 'id' key.
    return {"username": "admin1", "role": "admin", "id": 1}

@router.get("/clients")
def get_registered_clients(db: Session = Depends(get_db), admin=Depends(get_current_admin_user)):
    """
    Section 1: Returns registered client details.
    """
    clients = db.query(User).filter(User.role == "client").all()
    return clients

@router.get("/reports")
def get_uploaded_reports(db: Session = Depends(get_db), admin=Depends(get_current_admin_user)):
    """
    Section 2: Returns details of uploaded PDF reports.
    """
    reports = db.query(Report).all()
    return reports

@router.get("/approved-parameters")
def get_approved_parameters(db: Session = Depends(get_db), admin=Depends(get_current_admin_user)):
    """
    Section 3: Returns approved health parameters.
    """
    params = db.query(HealthParameter).filter(HealthParameter.status == HealthParameterStatus.approved).all()
    return params

@router.get("/pending-parameters")
def get_pending_parameters(db: Session = Depends(get_db), admin=Depends(get_current_admin_user)):
    """
    Section 4: Returns health parameters with status pending or rejected.
    """
    params = db.query(HealthParameter).filter(
        HealthParameter.status.in_([HealthParameterStatus.pending, HealthParameterStatus.rejected])
    ).all()
    return params

@router.post("/parameters/{param_id}/approve")
def approve_parameter(param_id: int, remarks: str = Form(None),
                      admin=Depends(get_current_admin_user),
                      db: Session = Depends(get_db)):
    """
    Approve a pending health parameter.
    If the parameter exists and its status is 'pending' or 'rejected', update its status to 'approved',
    record the approval timestamp, the approving admin, and any remarks.
    """
    param = db.query(HealthParameter).filter(HealthParameter.id == param_id).first()
    if not param:
        raise HTTPException(status_code=404, detail="Parameter not found")
    param.status = HealthParameterStatus.approved
    param.action_timestamp = datetime.utcnow()  # Using Python's datetime for consistency.
    param.approved_by = admin.get("id", 1)
    param.remarks = remarks
    db.commit()
    return {"message": "Parameter approved", "parameter_id": param_id}

@router.post("/parameters/{param_id}/reject")
def reject_parameter(param_id: int, remarks: str = Form(None),
                     admin=Depends(get_current_admin_user),
                     db: Session = Depends(get_db)):
    """
    Reject a pending health parameter.
    Updates the record to 'rejected' status and records the timestamp and any remarks.
    """
    param = db.query(HealthParameter).filter(HealthParameter.id == param_id).first()
    if not param:
        raise HTTPException(status_code=404, detail="Parameter not found")
    param.status = HealthParameterStatus.rejected
    param.action_timestamp = datetime.utcnow()
    param.remarks = remarks
    db.commit()
    return {"message": "Parameter rejected", "parameter_id": param_id}

@router.post("/parameters/{param_id}/map")
def map_parameter(param_id: int, map_to_existing: str = Form(...),
                  admin=Depends(get_current_admin_user),
                  db: Session = Depends(get_db)):
    param = db.query(HealthParameter).filter(HealthParameter.id == param_id).first()
    if not param:
        raise HTTPException(status_code=404, detail="Parameter not found")
    param.map_to_existing = map_to_existing
    db.commit()
    return {"message": "Mapping updated", "parameter_id": param_id}

@router.post("/parameters/{param_id}/update")
def update_parameter(param_id: int,
                     action: str = Form(...),
                     remarks: str = Form(None),
                     admin=Depends(get_current_admin_user),
                     db: Session = Depends(get_db)):
    """
    Single endpoint to update a parameter's status.
    If action is 'approve', the parameter is updated to approved (including admin details).
    If action is 'reject', it is updated to rejected.
    No DynamoDB update is performed here; only PostgreSQL is updated.
    """
    param = db.query(HealthParameter).filter(HealthParameter.id == param_id).first()
    if not param:
        raise HTTPException(status_code=404, detail="Parameter not found")

    if action == "approve":
        param.status = HealthParameterStatus.approved
        param.action_timestamp = datetime.utcnow()
        param.approved_by = admin.get("id", 1)
        param.remarks = remarks
        db.commit()
        return {"message": "Parameter approved", "parameter_id": param_id}
    elif action == "reject":
        param.status = HealthParameterStatus.rejected
        param.action_timestamp = datetime.utcnow()
        param.remarks = remarks
        db.commit()
        return {"message": "Parameter rejected", "parameter_id": param_id}

    raise HTTPException(status_code=400, detail="Invalid action")

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    # Section 1: Clients
    clients = db.query(User).filter(User.role == "client").all()
    
    # Section 2: Uploaded Reports
    reports = db.query(Report).all()

    # Section 3: Approved Health Parameters
    approved_params = (
        db.query(HealthParameter)
        .options(joinedload(HealthParameter.report))
        .filter(HealthParameter.status == HealthParameterStatus.approved)
        .all()
    )

    # Section 4: Pending/Rejected Health Parameters
    pending_rejected_params = (
        db.query(HealthParameter)
        .options(joinedload(HealthParameter.report))
        .filter(HealthParameter.status.in_([HealthParameterStatus.pending, HealthParameterStatus.rejected]))
        .all()
    )

    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "clients": clients,
        "reports": reports,
        "approved_params": approved_params,
        "pending_rejected_params": pending_rejected_params
    })

@router.post("/upload", tags=["PDF Upload"])
async def upload_report(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are accepted")

    # Retrieve client details from token payload
    client_phone = current_user.get("phone_number")
    client_id = current_user.get("user_id")
    report_name = file.filename.split('.')[0]

    try:
        # Upload PDF to S3
        s3_key, report_id, timestamp = s3_utils.upload_pdf_to_s3(file.file, client_phone, client_id, report_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"S3 upload failed: {str(e)}")

    # Create a new Report record in the database if not already created
    new_report = Report(
        client_id=client_id,
        s3_path=s3_key,
        report_unique_id=report_id,
        processing_status="pending"
    )
    db.add(new_report)
    db.commit()
    db.refresh(new_report)

    # Trigger asynchronous PDF extraction
    extract_pdf_task.delay(s3_key)

    return {"message": "Report uploaded successfully", "s3_key": s3_key, "report_id": report_id, "timestamp": timestamp}
