from app.storage import s3_client, BUCKET_NAME

try:
    response = s3_client.head_bucket(Bucket=BUCKET_NAME)
    print("SeaweedFS connection successful!")
    print("Bucket:", BUCKET_NAME)

except Exception as error:
    print("Storage connection failed:")
    print(error)