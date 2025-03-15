# celery_worker.py
import tempfile
import boto3
from celery import Celery
from app.config import settings
from app.db.session import SessionLocal
from app.db.models import Report, HealthParameter, HealthParameterStatus
from app.pdf.parser import extract_health_parameters_from_pdf  # Your PDF parser function

celery_app = Celery(
    "worker",
    broker=settings.CELERY_BROKER_URL,         # e.g. "amqp://guest:guest@localhost:5672//"
    backend=settings.CELERY_RESULT_BACKEND      # e.g. "rpc://"
)

@celery_app.task
def extract_pdf_task(s3_key: str):
    db = SessionLocal()
    try:
        # Download the file from S3
        s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION
        )
        bucket = settings.S3_BUCKET_NAME

        # Create a temporary file to save the PDF
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
            temp_path = tmp_file.name

        s3.download_file(bucket, s3_key, temp_path)

        # Extract health parameters from the PDF
        extracted_params = extract_health_parameters_from_pdf(temp_path)
        # Example return: {"HDL": {"value": "29", "unit": "mg/dL", "reference_range": "<40", "method": "calculated"}, ...}

        # Find the associated report record by matching the S3 key
        report = db.query(Report).filter(Report.s3_path == s3_key).first()
        if not report:
            # Log error or simply return if report not found
            return

        # For each parameter extracted, check if it exists (pending/approved) and if not, insert it.
        for param_name, details in extracted_params.items():
            # Check if parameter exists in pending/approved status
            existing = db.query(HealthParameter).filter(
                HealthParameter.parameter_name == param_name,
                HealthParameter.status.in_([HealthParameterStatus.pending, HealthParameterStatus.approved])
            ).first()
            if existing:
                # Skip if already present
                continue

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
        db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()
