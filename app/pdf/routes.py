# app/pdf/routes.py
from fastapi import APIRouter, File, UploadFile, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import Report, HealthParameter, HealthParameterStatus
from app.auth.routes import get_current_user  # Assuming you have a dependency to get the current user (via JWT)
from app.pdf import s3_utils
from app.pdf.parser import extract_health_parameters_from_pdf
from celery_worker import extract_pdf_task  # Import the Celery task

router = APIRouter()

@router.post("/upload", tags=["PDF Upload"])
async def upload_report(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are accepted")

    # Get client details from token payload
    client_phone = current_user.get("phone_number")
    client_id = current_user.get("user_id")
    report_name = file.filename.split('.')[0]

    try:
        # Upload the file to S3
        s3_key, report_id, timestamp = s3_utils.upload_pdf_to_s3(file.file, client_phone, client_id, report_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"S3 upload failed: {str(e)}")

    # Create a new Report record in the SQL database
    new_report = Report(
        client_id=client_id,
        s3_path=s3_key,
        report_unique_id=report_id,
        processing_status="pending"
    )
    db.add(new_report)
    db.commit()
    db.refresh(new_report)

    # Call asynchronous processing for PDF extraction
    extract_pdf_task.delay(s3_key)

    return {
        "message": "Report uploaded successfully",
        "s3_key": s3_key,
        "report_id": report_id,
        "timestamp": timestamp
    }

@router.post("/extract_parameters", tags=["PDF Extraction"])
async def extract_parameters(report_unique_id: str, db: Session = Depends(get_db)):
    """
    Synchronous endpoint to extract health parameters from a PDF report.
    For testing: Given a report_unique_id, download the PDF from S3,
    parse it, and insert new HealthParameter rows (status 'pending')
    if the parameter is unique (or if an existing record is in rejected status).
    """
    # Lookup report by unique id
    report = db.query(Report).filter(Report.report_unique_id == report_unique_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    try:
        # Download the PDF to a temporary file.
        # (Assume s3_utils.download_pdf_from_s3 returns a local file path.)
        temp_file = s3_utils.download_pdf_from_s3(report.s3_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download PDF: {str(e)}")
    
    # Extract parameters using your parser.
    extracted_params = extract_health_parameters_from_pdf(temp_file)
    # For example, extracted_params might be:
    # {
    #    "HDL": {"value": "29", "unit": "mg/dL", "reference_range": "<40", "method": "calculated"},
    #    "LDL": {"value": "207", "unit": "mg/dL", "reference_range": "<100", "method": "calculated"},
    #    ...
    # }
    
    inserted = []
    for param_name, details in extracted_params.items():
        # Check if parameter exists in pending/approved status
        existing = db.query(HealthParameter).filter(
            HealthParameter.parameter_name == param_name,
            HealthParameter.status.in_([HealthParameterStatus.pending, HealthParameterStatus.approved])
        ).first()
        if existing:
            # Skip if already exists in pending or approved status.
            continue

        # Create new HealthParameter record.
        new_param = HealthParameter(
            report_id=report.id,
            parameter_name=param_name,
            value=details.get("value"),
            unit=details.get("unit"),
            reference_range=details.get("reference_range"),
            method=details.get("method"),
            status=HealthParameterStatus.pending
        )
        db.add(new_param)
        inserted.append(new_param)
    
    db.commit()
    return {"message": "Extraction complete", "extracted_parameters": [p.parameter_name for p in inserted]}
