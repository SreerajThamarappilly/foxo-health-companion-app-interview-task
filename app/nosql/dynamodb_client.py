# app/nosql/dynamodb_client.py
import boto3
from app.config import settings

# Create a DynamoDB resource using boto3
dynamodb = boto3.resource(
    "dynamodb",
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    region_name=settings.AWS_REGION
)

def get_table():
    return dynamodb.Table(settings.DYNAMODB_HEALTH_TABLE)

def insert_health_report(report_id, data):
    """
    Insert a document for a health report into DynamoDB.
    'data' is a dictionary of extracted health parameters.
    """
    table = get_table()  # e.g. dynamodb.Table(settings.DYNAMODB_HEALTH_TABLE)
    item = {
        "report_id": report_id,
        "parameters": data  # dictionary of param_name -> {value, reference_range, etc.}
    }
    table.put_item(Item=item)
