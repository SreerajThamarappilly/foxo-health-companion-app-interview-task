# app/config.py
import os
from dotenv import load_dotenv

load_dotenv()  # Load variables from .env

class Settings:
    # General settings
    APP_NAME = os.getenv("APP_NAME", "HealthApp")
    SECRET_KEY = os.getenv("SECRET_KEY", "your-very-secret-key")
    ALGORITHM = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))

    # PostgreSQL settings
    SQLALCHEMY_DATABASE_URL = os.getenv("SQLALCHEMY_DATABASE_URL")

    # AWS S3 settings
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

    # DynamoDB table name
    DYNAMODB_HEALTH_TABLE = os.getenv("DYNAMODB_HEALTH_TABLE", "HealthReports")

    # Celery settings – add these new variables:
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//")
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "rpc://")

    #OpenAI API Key
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

settings = Settings()
