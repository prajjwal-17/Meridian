import os
from pathlib import Path

import boto3
from botocore.config import Config
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT.parent / ".env")

# Connect to the local S3-compatible SeaweedFS service
s3_client = boto3.client(
    "s3",
    endpoint_url=os.getenv("S3_ENDPOINT_URL"),
    aws_access_key_id=os.getenv("S3_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("S3_SECRET_KEY"),
    region_name=os.getenv("S3_REGION", "us-east-1"),
    config=Config(signature_version="s3v4"),
)

BUCKET_NAME = os.getenv("S3_BUCKET_NAME")


def upload_file(file_obj, object_key, content_type):
    """Upload a file to SeaweedFS."""
    s3_client.upload_fileobj(
        file_obj,
        BUCKET_NAME,
        object_key,
        ExtraArgs={"ContentType": content_type},
    )

    return object_key


def download_file(object_key, destination):
    """Download a file from SeaweedFS."""
    s3_client.download_file(
        BUCKET_NAME,
        object_key,
        str(destination),
    )