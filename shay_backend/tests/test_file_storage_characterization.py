"""
Golden-master / characterization tests for app/services/file_storage.py.

Purpose: this file had ZERO dedicated test coverage before this pass. It is
about to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Before the split, we capture
the CURRENT observable behavior of every public class/function so the split
can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included.

Pattern follows tests/test_channels_characterization.py: no real filesystem
beyond a tmp_path fixture for LocalFileStorage, no real cloud SDK calls
(mocked at the exact import path used inside the module under test),
`asyncio.run()` instead of pytest-asyncio (no async plugin installed).

Do not modify app/services/file_storage.py from this file's tests.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest


MODPATH = "app.services.file_storage"


# ---------------------------------------------------------------------------
# generate_structured_path
# ---------------------------------------------------------------------------

def test_generate_structured_path_basic():
    from app.services.file_storage import generate_structured_path
    result = generate_structured_path(
        company_name="Acme Corp",
        company_id="123",
        file_type="datasource",
        original_filename="report.csv",
        base_filename="report",
        file_extension=".csv",
        current_date="20260101",
    )
    assert result == "Acme_Corp_123/datasource/report_20260101.csv"


def test_generate_structured_path_strips_special_chars_and_collapses_underscores():
    from app.services.file_storage import generate_structured_path
    result = generate_structured_path(
        company_name="Acme!! -- Corp...",
        company_id="42",
        file_type="attachment",
        original_filename="f.txt",
        base_filename="f",
        file_extension=".txt",
        current_date="20260101",
    )
    assert result == "Acme_Corp_42/attachment/f_20260101.txt"


def test_generate_structured_path_leading_trailing_underscores_stripped():
    from app.services.file_storage import generate_structured_path
    result = generate_structured_path(
        company_name="---Acme---",
        company_id="1",
        file_type="commentfile",
        original_filename="f.txt",
        base_filename="f",
        file_extension=".txt",
        current_date="d",
    )
    assert result == "Acme_1/commentfile/f_d.txt"


# ---------------------------------------------------------------------------
# LocalFileStorage
# ---------------------------------------------------------------------------

def test_local_file_storage_upload_download_delete_roundtrip(tmp_path):
    from app.services.file_storage import LocalFileStorage

    storage = LocalFileStorage(base_dir=str(tmp_path))

    with patch(f"{MODPATH}.local.settings") as mock_settings:
        mock_settings.LOCAL_FILES_URL = "http://files.example.com/"
        result = asyncio.run(storage.upload_file(b"hello world", "sub/dir/file.txt", "file.txt"))

    assert result["provider"] == "local"
    assert result["size"] == 11
    assert result["file_url"] == "http://files.example.com/sub/dir/file.txt"
    full_path = os.path.join(str(tmp_path), "sub/dir/file.txt")
    assert result["storage_path"] == full_path
    assert os.path.exists(full_path)

    downloaded = asyncio.run(storage.download_file(full_path))
    assert downloaded == b"hello world"

    deleted = asyncio.run(storage.delete_file(full_path))
    assert deleted is True
    assert not os.path.exists(full_path)


def test_local_file_storage_delete_nonexistent_returns_true():
    from app.services.file_storage import LocalFileStorage
    storage = LocalFileStorage(base_dir="/tmp/does-not-matter")
    result = asyncio.run(storage.delete_file("/nonexistent/path/file.txt"))
    assert result is True


# ---------------------------------------------------------------------------
# AWSFileStorage
# ---------------------------------------------------------------------------

def test_aws_file_storage_requires_boto3_when_unavailable():
    from app.services.file_storage import AWSFileStorage
    with patch(f"{MODPATH}.aws.BOTO3_AVAILABLE", False):
        with pytest.raises(ImportError, match="boto3"):
            AWSFileStorage("my-bucket")


def test_aws_file_storage_upload_success():
    from app.services.file_storage import AWSFileStorage

    fake_client = MagicMock()
    fake_client.meta.region_name = "us-east-1"

    with patch(f"{MODPATH}.aws.BOTO3_AVAILABLE", True), \
         patch(f"{MODPATH}.aws.boto3") as mock_boto3, \
         patch(f"{MODPATH}.aws.settings") as mock_settings:
        mock_settings.AWS_ACCESS_KEY_ID = "key"
        mock_settings.AWS_SECRET_ACCESS_KEY = "secret"
        mock_boto3.client = MagicMock(return_value=fake_client)

        storage = AWSFileStorage("my-bucket", "us-east-1")
        result = asyncio.run(storage.upload_file(b"data", "path/f.txt", "f.txt"))

    assert result["provider"] == "aws"
    assert result["bucket_name"] == "my-bucket"
    assert result["file_url"] == "https://my-bucket.s3.amazonaws.com/path/f.txt"
    fake_client.put_object.assert_called_once()


def test_aws_file_storage_upload_failure_wraps_exception():
    from app.services.file_storage import AWSFileStorage

    fake_client = MagicMock()
    fake_client.put_object.side_effect = RuntimeError("boom")

    with patch(f"{MODPATH}.aws.BOTO3_AVAILABLE", True), \
         patch(f"{MODPATH}.aws.boto3") as mock_boto3, \
         patch(f"{MODPATH}.aws.settings") as mock_settings:
        mock_settings.AWS_ACCESS_KEY_ID = "key"
        mock_settings.AWS_SECRET_ACCESS_KEY = "secret"
        mock_boto3.client = MagicMock(return_value=fake_client)

        storage = AWSFileStorage("my-bucket")
        with pytest.raises(Exception, match="AWS upload failed"):
            asyncio.run(storage.upload_file(b"data", "path/f.txt", "f.txt"))


def test_aws_file_storage_content_type_lookup():
    from app.services.file_storage import AWSFileStorage
    with patch(f"{MODPATH}.aws.BOTO3_AVAILABLE", True), \
         patch(f"{MODPATH}.aws.boto3") as mock_boto3, \
         patch(f"{MODPATH}.aws.settings") as mock_settings:
        mock_settings.AWS_ACCESS_KEY_ID = "key"
        mock_settings.AWS_SECRET_ACCESS_KEY = "secret"
        mock_boto3.client = MagicMock(return_value=MagicMock())
        storage = AWSFileStorage("my-bucket")

    assert storage._get_content_type("a.json") == "application/json"
    assert storage._get_content_type("a.unknownext") == "application/octet-stream"


def test_aws_file_storage_delete_failure_returns_false():
    from app.services.file_storage import AWSFileStorage
    fake_client = MagicMock()
    fake_client.delete_object.side_effect = RuntimeError("boom")
    with patch(f"{MODPATH}.aws.BOTO3_AVAILABLE", True), \
         patch(f"{MODPATH}.aws.boto3") as mock_boto3, \
         patch(f"{MODPATH}.aws.settings") as mock_settings:
        mock_settings.AWS_ACCESS_KEY_ID = "key"
        mock_settings.AWS_SECRET_ACCESS_KEY = "secret"
        mock_boto3.client = MagicMock(return_value=fake_client)
        storage = AWSFileStorage("my-bucket")
        result = asyncio.run(storage.delete_file("path/f.txt"))
    assert result is False


# ---------------------------------------------------------------------------
# AzureFileStorage
# ---------------------------------------------------------------------------

def test_azure_file_storage_requires_sdk_when_unavailable():
    from app.services.file_storage import AzureFileStorage
    with patch(f"{MODPATH}.azure.AZURE_AVAILABLE", False):
        with pytest.raises(ImportError, match="azure-storage-blob"):
            AzureFileStorage("conn-str", "container")


def test_azure_file_storage_upload_success():
    from app.services.file_storage import AzureFileStorage

    fake_blob_client = MagicMock()
    fake_blob_client.url = "https://acct.blob.core.windows.net/container/f.txt"
    fake_service_client = MagicMock()
    fake_service_client.get_blob_client = MagicMock(return_value=fake_blob_client)
    fake_service_client.account_name = "acct"

    with patch(f"{MODPATH}.azure.AZURE_AVAILABLE", True), \
         patch(f"{MODPATH}.azure.BlobServiceClient") as mock_bsc:
        mock_bsc.from_connection_string = MagicMock(return_value=fake_service_client)
        storage = AzureFileStorage("conn-str", "container")
        result = asyncio.run(storage.upload_file(b"data", "f.txt", "f.txt"))

    assert result["provider"] == "azure"
    assert result["container_name"] == "container"
    assert result["account_name"] == "acct"
    assert result["file_url"] == "https://acct.blob.core.windows.net/container/f.txt"


def test_azure_file_storage_download_failure_wraps_exception():
    from app.services.file_storage import AzureFileStorage

    fake_blob_client = MagicMock()
    fake_blob_client.download_blob.side_effect = RuntimeError("boom")
    fake_service_client = MagicMock()
    fake_service_client.get_blob_client = MagicMock(return_value=fake_blob_client)

    with patch(f"{MODPATH}.azure.AZURE_AVAILABLE", True), \
         patch(f"{MODPATH}.azure.BlobServiceClient") as mock_bsc:
        mock_bsc.from_connection_string = MagicMock(return_value=fake_service_client)
        storage = AzureFileStorage("conn-str", "container")
        with pytest.raises(Exception, match="Azure download failed"):
            asyncio.run(storage.download_file("f.txt"))


# ---------------------------------------------------------------------------
# OracleFileStorage
# ---------------------------------------------------------------------------

def test_oracle_file_storage_requires_sdk_when_unavailable():
    from app.services.file_storage import OracleFileStorage
    with patch(f"{MODPATH}.oracle.OCI_AVAILABLE", False):
        with pytest.raises(ImportError, match="oci"):
            OracleFileStorage("ns", "bucket", "compartment")


def test_oracle_file_storage_upload_success():
    from app.services.file_storage import OracleFileStorage

    fake_os_client = MagicMock()

    with patch(f"{MODPATH}.oracle.OCI_AVAILABLE", True), \
         patch(f"{MODPATH}.oracle.from_file", return_value={"config": True}), \
         patch(f"{MODPATH}.oracle.ObjectStorageClient", return_value=fake_os_client):
        storage = OracleFileStorage("myns", "mybucket", "compartment-1")
        result = asyncio.run(storage.upload_file(b"data", "f.txt", "f.txt"))

    assert result["provider"] == "oracle"
    assert result["namespace"] == "myns"
    assert result["bucket_name"] == "mybucket"
    assert result["compartment_id"] == "compartment-1"
    assert "objectstorage.myns.oraclecloud.com" in result["file_url"]


def test_oracle_file_storage_delete_success():
    from app.services.file_storage import OracleFileStorage

    fake_os_client = MagicMock()

    with patch(f"{MODPATH}.oracle.OCI_AVAILABLE", True), \
         patch(f"{MODPATH}.oracle.from_file", return_value={"config": True}), \
         patch(f"{MODPATH}.oracle.ObjectStorageClient", return_value=fake_os_client):
        storage = OracleFileStorage("myns", "mybucket", "compartment-1")
        result = asyncio.run(storage.delete_file("f.txt"))

    assert result is True
    fake_os_client.delete_object.assert_called_once()


# ---------------------------------------------------------------------------
# FileStorageService._initialize_provider + get_file_storage_service
# ---------------------------------------------------------------------------

def test_file_storage_service_local_env():
    from app.services.file_storage import FileStorageService, LocalFileStorage
    with patch(f"{MODPATH}.service.settings") as mock_settings:
        mock_settings.FILE_UPLOAD_ENV = "local"
        mock_settings.UPLOAD_DIR = "uploads"
        service = FileStorageService()
    assert isinstance(service.provider, LocalFileStorage)
    assert service.provider.base_dir == "uploads"


def test_file_storage_service_cloud_aws_missing_bucket_raises():
    from app.services.file_storage import FileStorageService
    with patch(f"{MODPATH}.service.settings") as mock_settings:
        mock_settings.FILE_UPLOAD_ENV = "cloud"
        mock_settings.CLOUD_PROVIDER = "aws"
        mock_settings.AWS_BUCKET_NAME = None
        with pytest.raises(ValueError, match="AWS_BUCKET_NAME"):
            FileStorageService()


def test_file_storage_service_cloud_aws_success():
    from app.services.file_storage import FileStorageService, AWSFileStorage
    with patch(f"{MODPATH}.service.settings") as mock_settings, \
         patch(f"{MODPATH}.aws.BOTO3_AVAILABLE", True), \
         patch(f"{MODPATH}.aws.boto3") as mock_boto3:
        mock_settings.FILE_UPLOAD_ENV = "cloud"
        mock_settings.CLOUD_PROVIDER = "aws"
        mock_settings.AWS_BUCKET_NAME = "my-bucket"
        mock_settings.AWS_REGION = "us-west-2"
        mock_settings.AWS_ACCESS_KEY_ID = "key"
        mock_settings.AWS_SECRET_ACCESS_KEY = "secret"
        mock_boto3.client = MagicMock(return_value=MagicMock())
        service = FileStorageService()
    assert isinstance(service.provider, AWSFileStorage)
    assert service.provider.bucket_name == "my-bucket"


def test_file_storage_service_unsupported_cloud_provider_raises():
    from app.services.file_storage import FileStorageService
    with patch(f"{MODPATH}.service.settings") as mock_settings:
        mock_settings.FILE_UPLOAD_ENV = "cloud"
        mock_settings.CLOUD_PROVIDER = "not-a-real-provider"
        with pytest.raises(ValueError, match="Unsupported cloud provider"):
            FileStorageService()


def test_file_storage_service_unsupported_env_raises():
    from app.services.file_storage import FileStorageService
    with patch(f"{MODPATH}.service.settings") as mock_settings:
        mock_settings.FILE_UPLOAD_ENV = "not-a-real-env"
        with pytest.raises(ValueError, match="Unsupported storage environment"):
            FileStorageService()


def test_file_storage_service_delegates_to_provider(tmp_path):
    from app.services.file_storage import FileStorageService
    with patch(f"{MODPATH}.service.settings") as mock_settings:
        mock_settings.FILE_UPLOAD_ENV = "local"
        mock_settings.UPLOAD_DIR = str(tmp_path)
        service = FileStorageService()

    fake_provider = MagicMock()
    fake_provider.upload_file = MagicMock(return_value=asyncio.sleep(0, result={"ok": True}))
    fake_provider.download_file = MagicMock(return_value=asyncio.sleep(0, result=b"data"))
    fake_provider.delete_file = MagicMock(return_value=asyncio.sleep(0, result=True))
    service.provider = fake_provider

    assert asyncio.run(service.upload_file(b"x", "p", "f")) == {"ok": True}
    assert asyncio.run(service.download_file("p")) == b"data"
    assert asyncio.run(service.delete_file("p")) is True


def test_get_file_storage_service_returns_singleton():
    import app.services.file_storage as mod
    import app.services.file_storage.service as service_mod
    service_mod._file_storage_service = None
    with patch(f"{MODPATH}.service.settings") as mock_settings:
        mock_settings.FILE_UPLOAD_ENV = "local"
        mock_settings.UPLOAD_DIR = "uploads"
        first = mod.get_file_storage_service()
        second = mod.get_file_storage_service()
    assert first is second
    service_mod._file_storage_service = None
