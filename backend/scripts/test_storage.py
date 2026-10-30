
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

s3 = boto3.client(
    "s3",
    endpoint_url="http://localhost:8333",
    aws_access_key_id="admin",
    aws_secret_access_key="meridian-local-secret",
    region_name="us-east-1",
    config=Config(signature_version="s3v4")
)

bucket_name = "meridian-documents"

try:
    s3.create_bucket(Bucket=bucket_name)
    print("Bucket created successfully.")

except ClientError as error:
    code = error.response["Error"]["Code"]

    if code in ["BucketAlreadyOwnedByYou", "BucketAlreadyExists"]:
        print("Bucket already exists.")
    else:
        raise

# Verify bucket access directly
try:
    s3.head_bucket(Bucket=bucket_name)
    print("SUCCESS: Bucket is accessible!")

except ClientError as error:
    print("Bucket verification failed:")
    print(error.response["Error"])
