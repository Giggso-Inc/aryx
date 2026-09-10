"""
S3-backed file reading for the cloud-storage validation path.

Split out of app/utils/file_validation.py — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.
"""

import logging
import boto3

logger = logging.getLogger(__name__)


def read_from_s3(bucket: str, object_name: str, access_key: str, secret_key: str) -> str:
    """
    Read the file from S3 and return the content
    """
    try:
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key
        )

        response = s3_client.get_object(Bucket=bucket, Key=object_name)
        return response["Body"].read().decode("utf-8")
    except Exception as e:
        logger.exception(f"Error reading from S3: {e}")
        raise
