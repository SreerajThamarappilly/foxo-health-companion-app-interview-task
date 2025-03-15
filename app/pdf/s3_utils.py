# app/pdf/s3_utils.py
import tempfile
import boto3
import uuid
from datetime import datetime
from app.config import settings

def upload_pdf_to_s3(file_obj, client_phone, client_id, report_name):
    """
    Uploads a PDF file to S3 with a custom path:
    {bucket}/{client_phone}/{client_id}/{timestamp}/{unique_report_id}/{report_name}.pdf
    Returns: (s3_key, report_id, timestamp)
    """
    s3 = boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION
    )
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    report_id = str(uuid.uuid4())
    s3_key = f"{client_phone}/{client_id}/{timestamp}/{report_id}/{report_name}.pdf"
    s3.upload_fileobj(file_obj, settings.S3_BUCKET_NAME, s3_key)
    return s3_key, report_id, timestamp

def download_pdf_from_s3(s3_key: str) -> str:
    """
    Downloads the file from S3 and returns a local temporary file path.
    """
    s3 = boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION
    )
    bucket = settings.S3_BUCKET_NAME
    # Create a temporary file; do not delete immediately so it can be processed.
    tmp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp_file.close()  # Close it so boto3 can write to it.
    s3.download_file(bucket, s3_key, tmp_file.name)
    return tmp_file.name
