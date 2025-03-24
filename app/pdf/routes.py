# app/pdf/routes.py
from fastapi import APIRouter, File, UploadFile, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import Report, HealthParameter, HealthParameterStatus
from app.auth.routes import get_current_user
from app.pdf import s3_utils, parser
from app.config import settings
from app.pdf.parser import PDFExtractor, DefaultPDFExtractionStrategy, validate_health_parameters_with_openai
from celery_worker import extract_pdf_task
import boto3
import os
import re

router = APIRouter()

@router.post("/upload", tags=["PDF Upload"])
async def upload_report(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Endpoint to upload the health test report uploaded by the client.
    """
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are accepted")

    client_phone = current_user.get("phone_number")
    client_id = current_user.get("user_id")
    report_name = file.filename.split('.')[0]

    try:
        s3_key, report_id, timestamp = s3_utils.upload_pdf_to_s3(file.file, client_phone, client_id, report_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"S3 upload failed: {str(e)}")

    new_report = Report(
        client_id=client_id,
        s3_path=s3_key,
        report_unique_id=report_id,
        processing_status="pending"
    )
    db.add(new_report)
    db.commit()
    db.refresh(new_report)

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
    For a given report_unique_id:
      - Downloads the PDF from S3.
      - Extracts parameters using the dynamic parser.
      - Validates parameters with OpenAI (sending only non-sensitive details).
      - For each validated health test name (from OpenAI):
            * Normalize the name for comparison.
            * If it doesn't exist in PostgreSQL for this report, insert it with pending status.
            * If it exists with 'rejected' status, update it to pending.
            * If it exists with 'approved' or 'pending', do nothing.
      - In DynamoDB, update (or create) a single document for the PDF upload that contains a list of validated health test parameters and their statuses.
      - Returns a response with "approved_parameters" and "pending_parameters" as determined by PostgreSQL.
    """
    # Lookup report in PostgreSQL.
    report = db.query(Report).filter(Report.report_unique_id == report_unique_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    # Download PDF from S3.
    try:
        temp_file = s3_utils.download_pdf_from_s3(report.s3_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download PDF: {str(e)}")
    
    # Extract parameters from PDF.
    extractor = PDFExtractor(DefaultPDFExtractionStrategy())
    extracted_params = extractor.extract_parameters(temp_file)
    if not extracted_params:
        raise HTTPException(status_code=400, detail="No health parameters extracted from the PDF.")
    
    # Validate parameters with OpenAI.
    try:
        valid_params, _ = validate_health_parameters_with_openai(extracted_params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI validation failed: {str(e)}")
    
    # Get the list of validated health test names from OpenAI.
    validated_names = list(valid_params.keys())
    
    # Fetch all existing health parameters for this report from PostgreSQL.
    existing_params = db.query(HealthParameter).filter(
        HealthParameter.report_id == report.id
    ).all()
    existing_map = { parser.normalize_parameter_name(p.parameter_name): p for p in existing_params }

    # Update PostgreSQL: Insert new records or update rejected ones.
    for validated_name in validated_names:
        details = valid_params[validated_name]
        norm_name = parser.normalize_parameter_name(validated_name)
        db_param = existing_map.get(norm_name)
        if db_param:
            # If record exists and is rejected, update it to pending.
            if db_param.status == HealthParameterStatus.rejected:
                db_param.status = HealthParameterStatus.pending
            # Else, if already pending or approved, do nothing.
        else:
            # Insert new record with pending status.
            new_param = HealthParameter(
                report_id=report.id,
                parameter_name=validated_name.strip(),  # store original validated name
                value=details.get("value"),
                unit=details.get("unit"),
                reference_range=details.get("reference_range"),
                method=details.get("method"),
                status=HealthParameterStatus.pending
            )
            db.add(new_param)
    db.commit()
    
    # Rebuild the mapping from DB after commit.
    existing_params = db.query(HealthParameter).filter(
        HealthParameter.report_id == report.id
    ).all()
    
    # Build DynamoDB document: create a single document for this PDF upload that includes
    # a list of validated parameters with their statuses (approved or pending).
    dynamo_table_name = settings.DYNAMODB_HEALTH_TABLE
    if not dynamo_table_name:
        raise HTTPException(status_code=500, detail="DynamoDB table name not configured")
    dynamodb = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1"))
    table = dynamodb.Table(dynamo_table_name)
    
    dynamo_document = {
        "report_id": report_unique_id,
        "parameters": []  # List of dicts: each with parameter_name and status.
    }
    
    # We use the same validation from OpenAI: consider only parameters in validated_names.
    validated_norm_names = [parser.normalize_parameter_name(name) for name in validated_names]
    
    for param in existing_params:
        norm_db = parser.normalize_parameter_name(param.parameter_name)
        if norm_db in validated_norm_names:
            # At this point, any parameter with status 'rejected' was updated to 'pending'.
            status_str = "approved" if param.status == HealthParameterStatus.approved else "pending"
            dynamo_document["parameters"].append({
                "parameter_name": param.parameter_name,
                "status": status_str
            })
    
    # Extract approved and pending keys from the DynamoDB document.
    approved_keys = [item["parameter_name"] for item in dynamo_document["parameters"] if item["status"] == "approved"]
    pending_keys = [item["parameter_name"] for item in dynamo_document["parameters"] if item["status"] == "pending"]
    
    # Upsert (update or insert) the document in DynamoDB.
    table.put_item(Item=dynamo_document)
    
    # Return the final API response, ensuring that the lists match the values in the DynamoDB document.
    return {
        "message": "Extraction and validation complete",
        "approved_parameters": approved_keys,
        "pending_parameters": pending_keys
    }

@router.get("/admin/pending_parameters", tags=["Admin Dashboard"])
async def get_pending_parameters():
    """
    Retrieves pending (or rejected) health parameters from DynamoDB for admin review.
    """
    dynamo_table_name = os.getenv("DYNAMO_TABLE_NAME")
    if not dynamo_table_name:
        raise HTTPException(status_code=500, detail="DynamoDB table name not configured")
    
    dynamodb = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1"))
    table = dynamodb.Table(dynamo_table_name)
    
    response = table.scan(
        FilterExpression="status = :status",
        ExpressionAttributeValues={":status": "pending"}
    )
    items = response.get("Items", [])
    return {"pending_parameters": items}
