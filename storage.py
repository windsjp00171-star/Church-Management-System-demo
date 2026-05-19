import boto3
from botocore.config import Config as BotoConfig
from config import Config

_s3 = None

def _get_s3():
    global _s3
    if _s3 is None:
        _s3 = boto3.client(
            's3',
            endpoint_url=Config.R2_ENDPOINT,
            aws_access_key_id=Config.R2_ACCESS_KEY_ID,
            aws_secret_access_key=Config.R2_SECRET_ACCESS_KEY,
            config=BotoConfig(signature_version='s3v4'),
            region_name='auto',
        )
    return _s3

BUCKET = Config.R2_BUCKET_NAME


def upload_file(file_obj, key, content_type='application/octet-stream'):
    _get_s3().upload_fileobj(
        file_obj,
        BUCKET,
        key,
        ExtraArgs={'ContentType': content_type},
    )


def get_presigned_url(key, expires=3600):
    return _get_s3().generate_presigned_url(
        'get_object',
        Params={'Bucket': BUCKET, 'Key': key},
        ExpiresIn=expires,
    )


def delete_file(key):
    _get_s3().delete_object(Bucket=BUCKET, Key=key)


def get_file_stream(key):
    response = _get_s3().get_object(Bucket=BUCKET, Key=key)
    return response['Body']
