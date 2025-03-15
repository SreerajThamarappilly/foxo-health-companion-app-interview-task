# app/pdf/routes.py
from fastapi import APIRouter, File, UploadFile, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import Report, HealthParameter, HealthParameterStatus
from app.auth.routes import get_current_user
from app.pdf import s3_utils
from app.config import settings
from app.pdf.parser import extract_health_parameters_from_pdf, validate_health_parameters_with_openai
from celery_worker import extract_pdf_task
import boto3
import os

router = APIRouter()

@router.post("/upload", tags=["PDF Upload"])
async def upload_report(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
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
          * Convert the name to a normalized version (lowercase/strip) for DB lookup
          * If it doesn't exist in PostgreSQL for this report, insert it with pending status.
          * If it exists with 'rejected' status, update it to pending.
          * If it exists with 'approved' or 'pending', do nothing.
      - In DynamoDB, add or update items for each validated test name (one row per PDF upload).
      - Returns final "approved_parameters" and "pending_parameters" by reading from the DB
        and updating DynamoDB accordingly.
    """
    from sqlalchemy import func  # for case-insensitive matching

    # Lookup the report in PostgreSQL
    report = db.query(Report).filter(Report.report_unique_id == report_unique_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    # Download PDF from S3
    try:
        temp_file = s3_utils.download_pdf_from_s3(report.s3_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download PDF: {str(e)}")
    
    # Extract parameters from PDF
    extracted_params = extract_health_parameters_from_pdf(temp_file)
    if not extracted_params:
        raise HTTPException(status_code=400, detail="No health parameters extracted from the PDF.")
    
    # Validate parameters with OpenAI
    try:
        valid_params, _ = validate_health_parameters_with_openai(extracted_params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI validation failed: {str(e)}")
    
    # List of validated names from OpenAI
    validated_names = list(valid_params.keys())

    # Initialize DynamoDB
    dynamo_table_name = settings.DYNAMODB_HEALTH_TABLE
    if not dynamo_table_name:
        raise HTTPException(status_code=500, detail="DynamoDB table name not configured")
    dynamodb = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1"))
    table = dynamodb.Table(dynamo_table_name)

    # Step 1: Update PostgreSQL to avoid duplicates
    for validated_name in validated_names:
        details = valid_params[validated_name]

        # Use a normalized (lowercased, stripped) version for DB lookup
        normalized_name = validated_name.strip().lower()

        # Attempt to find an existing record for this parameter (case-insensitive)
        db_param = db.query(HealthParameter).filter(
            HealthParameter.report_id == report.id,
            func.lower(HealthParameter.parameter_name) == normalized_name
        ).first()

        if db_param:
            # If the record exists, update from 'rejected' to 'pending' if needed
            if db_param.status == HealthParameterStatus.rejected:
                db_param.status = HealthParameterStatus.pending
            # If it's already pending or approved, do nothing
        else:
            # If not found, insert a new record with pending status
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

    # Step 2: Query the final statuses in PostgreSQL and update DynamoDB
    approved_list = []
    pending_list = []

    for validated_name in validated_names:
        normalized_name = validated_name.strip().lower()

        db_param = db.query(HealthParameter).filter(
            HealthParameter.report_id == report.id,
            func.lower(HealthParameter.parameter_name) == normalized_name
        ).first()

        if db_param:
            # If param is found in DB, store item in DynamoDB with the correct status
            if db_param.status == HealthParameterStatus.approved:
                approved_list.append(db_param.parameter_name)  # use actual stored name
                table.put_item(
                    Item={
                        "report_id": report_unique_id,
                        "parameter_name": db_param.parameter_name,
                        "details": valid_params[validated_name],
                        "status": "approved"
                    }
                )
            else:
                pending_list.append(db_param.parameter_name)
                table.put_item(
                    Item={
                        "report_id": report_unique_id,
                        "parameter_name": db_param.parameter_name,
                        "details": valid_params[validated_name],
                        "status": "pending"
                    }
                )
        else:
            # Should not happen, but in case no DB record found
            pending_list.append(validated_name)
            table.put_item(
                Item={
                    "report_id": report_unique_id,
                    "parameter_name": validated_name,
                    "details": valid_params[validated_name],
                    "status": "pending"
                }
            )

    return {
        "message": "Extraction and validation complete",
        "approved_parameters": approved_list,
        "pending_parameters": pending_list
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
