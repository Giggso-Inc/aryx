"""
Golden-master / characterization tests for app/services/vault_data_builder.py.

Purpose: vault_data_builder.py is 635 lines with ZERO existing test coverage.
It is about to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a). Before the split,
we capture the CURRENT observable behavior of every public function so the
split can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included. Notably:
- In `build_vault_credentials`'s "app" branch, Google Drive OAuth client
  fields are gated by `settings.GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`
  but the VALUES assigned come from `settings.CLIENT_ID` / `CLIENT_SECRET`
  (a different, unrelated config pair) — this is a pre-existing bug,
  characterized as-is here, not fixed.

No pytest-asyncio is installed; async functions are driven via
`asyncio.run()`, matching tests/test_channels_characterization.py's pattern.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

MODULE = "app.services.vault_data_builder"


def _settings_patch(**overrides):
    """Patch attributes directly on the live app.core.config.settings object."""
    from app.core.config import settings

    return patch.multiple(settings, **overrides)


# ---------------------------------------------------------------------------
# get_endpoint_url
# ---------------------------------------------------------------------------
def test_get_endpoint_url_known_providers():
    from app.services.vault_data_builder import get_endpoint_url

    assert get_endpoint_url("aws") == "https://s3.amazonaws.com"
    assert get_endpoint_url("azure") == "https://storage.blob.core.windows.net"
    assert get_endpoint_url("gcp") == "https://storage.googleapis.com"
    assert get_endpoint_url("oracle") == "https://objectstorage.oraclecloud.com"


def test_get_endpoint_url_unknown_provider_defaults_to_aws():
    from app.services.vault_data_builder import get_endpoint_url

    assert get_endpoint_url("unknown_provider") == "https://s3.amazonaws.com"


# ---------------------------------------------------------------------------
# build_vault_credentials — storage_type == "local"
# ---------------------------------------------------------------------------
def test_build_vault_credentials_local_file_system():
    from app.services.vault_data_builder import build_vault_credentials

    with _settings_patch(FILE_UPLOAD_ENV="local", CLOUD_PROVIDER=None):
        result = asyncio.run(build_vault_credentials(storage_type="local"))

    assert result == {
        "access_key": None,
        "secret_access_key": None,
        "region": None,
        "bucket_name": None,
        "localProvider": "file_system",
        "additional_config": None,
    }


def test_build_vault_credentials_local_cloud_env_aws():
    from app.services.vault_data_builder import build_vault_credentials

    with _settings_patch(
        FILE_UPLOAD_ENV="cloud",
        CLOUD_PROVIDER="aws",
        AWS_ACCESS_KEY_ID="ak",
        AWS_SECRET_ACCESS_KEY="sk",
        AWS_REGION="us-east-1",
        AWS_BUCKET_NAME="bucket",
    ):
        result = asyncio.run(build_vault_credentials(storage_type="local"))

    assert result["localProvider"] == "aws"
    assert result["access_key"] == "ak"
    assert result["additional_config"]["endpoint_url"] == "https://s3.amazonaws.com"
    assert result["additional_config"]["cloud_provider"] == "aws"


def test_build_vault_credentials_local_cloud_env_azure():
    from app.services.vault_data_builder import build_vault_credentials

    with _settings_patch(
        FILE_UPLOAD_ENV="cloud",
        CLOUD_PROVIDER="azure",
        AZURE_STORAGE_CONNECTION_STRING="conn-str",
        AZURE_CONTAINER_NAME="container",
    ):
        result = asyncio.run(build_vault_credentials(storage_type="local"))

    assert result["access_key"] == "conn-str"
    assert result["secret_access_key"] is None
    assert result["bucket_name"] == "container"
    assert result["localProvider"] == "azure"


def test_build_vault_credentials_local_cloud_env_oracle():
    from app.services.vault_data_builder import build_vault_credentials

    with _settings_patch(
        FILE_UPLOAD_ENV="cloud",
        CLOUD_PROVIDER="oracle",
        ORACLE_NAMESPACE="ns",
        ORACLE_BUCKET_NAME="bucket",
    ):
        result = asyncio.run(build_vault_credentials(storage_type="local"))

    assert result["access_key"] == "ns"
    assert result["bucket_name"] == "bucket"
    assert result["localProvider"] == "oracle"


def test_build_vault_credentials_local_cloud_env_unrecognized_defaults_aws():
    from app.services.vault_data_builder import build_vault_credentials

    with _settings_patch(
        FILE_UPLOAD_ENV="cloud",
        CLOUD_PROVIDER="not_a_real_provider",
        AWS_ACCESS_KEY_ID="ak",
        AWS_SECRET_ACCESS_KEY="sk",
        AWS_REGION="us-east-1",
        AWS_BUCKET_NAME="bucket",
    ):
        result = asyncio.run(build_vault_credentials(storage_type="local"))

    assert result["localProvider"] == "aws"
    assert result["additional_config"]["cloud_provider"] == "aws"


# ---------------------------------------------------------------------------
# build_vault_credentials — storage_type == "cloud"
# ---------------------------------------------------------------------------
def test_build_vault_credentials_cloud_no_config_returns_all_none():
    from app.services.vault_data_builder import build_vault_credentials

    result = asyncio.run(build_vault_credentials(storage_type="cloud", config=None))
    assert result == {
        "access_key": None,
        "secret_access_key": None,
        "region": None,
        "bucket_name": None,
        "localProvider": None,
        "additional_config": None,
    }


def test_build_vault_credentials_cloud_gcp():
    from app.services.vault_data_builder import build_vault_credentials

    config = {
        "region": "us-central1",
        "bucket_name": "gcp-bucket",
        "file_path": "/path",
        "service_account_json": {"type": "service_account"},
        "project_id": "proj-1",
    }
    result = asyncio.run(
        build_vault_credentials(storage_type="cloud", provider="gcp", config=config)
    )

    assert result["access_key"] is None
    assert result["secret_access_key"] is None
    assert result["region"] == "us-central1"
    assert result["bucket_name"] == "gcp-bucket"
    assert result["file_path"] == "/path"
    assert result["service_account_json"] == {"type": "service_account"}
    assert result["project_id"] == "proj-1"
    assert result["localProvider"] is None
    assert result["additional_config"]["provider"] == "gcp"


def test_build_vault_credentials_cloud_aws_with_alt_keys():
    from app.services.vault_data_builder import build_vault_credentials

    config = {
        "access_key": "ak",
        "secret_key": "sk-alt",
        "location": "us-west-2",
        "container_name": "alt-bucket",
    }
    result = asyncio.run(
        build_vault_credentials(storage_type="cloud", provider="aws", config=config)
    )

    assert result["access_key"] == "ak"
    assert result["secret_access_key"] == "sk-alt"
    assert result["region"] == "us-west-2"
    assert result["bucket_name"] == "alt-bucket"
    assert result["additional_config"]["provider"] == "aws"


# ---------------------------------------------------------------------------
# build_vault_credentials — storage_type == "database"
# ---------------------------------------------------------------------------
def test_build_vault_credentials_database_no_config_returns_all_none():
    from app.services.vault_data_builder import build_vault_credentials

    result = asyncio.run(build_vault_credentials(storage_type="database", config=None))
    assert result == {
        "access_key": None,
        "secret_access_key": None,
        "region": None,
        "bucket_name": None,
        "localProvider": None,
        "additional_config": None,
    }


def test_build_vault_credentials_database_full_fields_with_fallback_aliases():
    from app.services.vault_data_builder import build_vault_credentials

    config = {
        "user": "bob",
        "pass": "secret",
        "host": "db.example.com",
        "port": 5432,
        "database": "mydb",
        "schema": "public",
        "tableName": "users",
        "collectionName": "coll",
        "service": "ORCL",
        "account": "snow-acct",
        "warehouse": "wh1",
        "region": "us-east-1",
        "access_key_id": "akid",
        "secret_access_key": "sakid",
    }
    result = asyncio.run(
        build_vault_credentials(storage_type="database", provider="snowflake", config=config)
    )

    assert result["username"] == "bob"
    assert result["password"] == "secret"
    assert result["hostname"] == "db.example.com"
    assert result["port"] == "5432"  # converted to string
    assert result["databaseName"] == "mydb"
    assert result["schemaName"] == "public"
    assert result["tableName"] == "users"
    assert result["collectionName"] == "coll"
    assert result["serviceName"] == "ORCL"
    assert result["accountId"] == "snow-acct"
    assert result["warehouse"] == "wh1"
    assert result["regionName"] == "us-east-1"
    assert result["accessKeyId"] == "akid"
    assert result["secretAccessKey"] == "sakid"
    assert result["additional_config"]["database_type"] == "snowflake"


def test_build_vault_credentials_database_provider_defaults_mysql():
    from app.services.vault_data_builder import build_vault_credentials

    result = asyncio.run(
        build_vault_credentials(storage_type="database", config={"username": "u"})
    )
    assert result["additional_config"]["database_type"] == "mysql"
    assert result["username"] == "u"


# ---------------------------------------------------------------------------
# build_vault_credentials — storage_type == "app"
# ---------------------------------------------------------------------------
def test_build_vault_credentials_app_no_app_type_returns_fallback():
    from app.services.vault_data_builder import build_vault_credentials

    result = asyncio.run(build_vault_credentials(storage_type="app", app_type=None))
    assert result == {
        "access_key": None,
        "secret_access_key": None,
        "region": None,
        "bucket_name": None,
        "localProvider": None,
        "additional_config": None,
    }


def test_build_vault_credentials_app_google_drive_no_connection_settings():
    from app.services.vault_data_builder import build_vault_credentials

    config = {"app_id": "app-1"}
    result = asyncio.run(
        build_vault_credentials(storage_type="app", provider="google", config=config, app_type="google_drive")
    )
    assert result["additional_config"]["app_type"] == "googleDrive"
    assert result["additional_config"]["app_id"] == "app-1"
    assert result["additional_config"]["oauth_configured"] is True
    assert "localProvider" not in result


def test_build_vault_credentials_app_google_drive_refresh_token_fetched_from_db():
    """Characterizes the DB-lookup branch: when connection_settings.account has
    no secret_key but a connection_id + db are supplied, the code executes a raw
    SQL SELECT against gg_app_accounts and, if found and channel matches, injects
    the app_account's connection_settings.refresh_token as account.secret_key."""
    from app.services.vault_data_builder import build_vault_credentials

    mock_db = AsyncMock()
    row = ("conn-id-1", "app-1", "chan-1", None, None, None, {"refresh_token": "rt-123"}, None, None, None, None, None, None, None, None, None, None, None)
    mock_result = MagicMock()
    mock_result.first.return_value = row
    mock_db.execute = AsyncMock(return_value=mock_result)

    config = {
        "connection_id": "conn-id-1",
        "connection_settings": {"account": {}},
    }
    with _settings_patch(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET=""):
        result = asyncio.run(
            build_vault_credentials(
                storage_type="app",
                config=config,
                app_type="google_drive",
                db=mock_db,
                channel_id="chan-1",
            )
        )

    mock_db.execute.assert_awaited_once()
    assert result["additional_config"]["secret_key"] == "rt-123"


def test_build_vault_credentials_app_google_drive_channel_mismatch_skips_refresh_token(capsys):
    from app.services.vault_data_builder import build_vault_credentials

    mock_db = AsyncMock()
    row = ("conn-id-1", "app-1", "chan-OTHER", None, None, None, {"refresh_token": "rt-123"}, None, None, None, None, None, None, None, None, None, None, None)
    mock_result = MagicMock()
    mock_result.first.return_value = row
    mock_db.execute = AsyncMock(return_value=mock_result)

    config = {
        "connection_id": "conn-id-1",
        "connection_settings": {"account": {}},
    }
    result = asyncio.run(
        build_vault_credentials(
            storage_type="app",
            config=config,
            app_type="google_drive",
            db=mock_db,
            channel_id="chan-MINE",
        )
    )

    assert "secret_key" not in result["additional_config"]


def test_build_vault_credentials_app_google_drive_account_not_found(capsys):
    from app.services.vault_data_builder import build_vault_credentials

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.first.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    config = {
        "connection_id": "conn-id-missing",
        "connection_settings": {"account": {}},
    }
    result = asyncio.run(
        build_vault_credentials(
            storage_type="app", config=config, app_type="google_drive", db=mock_db
        )
    )
    assert "secret_key" not in result["additional_config"]


def test_build_vault_credentials_app_google_drive_db_exception_is_non_fatal():
    from app.services.vault_data_builder import build_vault_credentials

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=RuntimeError("db down"))

    config = {
        "connection_id": "conn-id-1",
        "connection_settings": {"account": {}},
    }
    result = asyncio.run(
        build_vault_credentials(
            storage_type="app", config=config, app_type="google_drive", db=mock_db
        )
    )
    # Exception is swallowed; function still returns credentials dict.
    assert result["additional_config"]["oauth_configured"] is True


def test_build_vault_credentials_app_google_drive_client_id_bug_characterized():
    """Pre-existing bug: gate checks settings.GOOGLE_CLIENT_ID/SECRET but the
    values ASSIGNED come from settings.CLIENT_ID/CLIENT_SECRET (unrelated
    config keys). Characterized as-is."""
    from app.services.vault_data_builder import build_vault_credentials

    config = {
        "connection_settings": {
            "account": {"secret_key": "already-set", "file_id": "f1"}
        }
    }
    with _settings_patch(
        GOOGLE_CLIENT_ID="google-cid",
        GOOGLE_CLIENT_SECRET="google-secret",
        CLIENT_ID="other-cid",
        CLIENT_SECRET="other-secret",
    ):
        result = asyncio.run(
            build_vault_credentials(storage_type="app", config=config, app_type="google_drive")
        )

    assert result["additional_config"]["client_id"] == "other-cid"
    assert result["additional_config"]["client_secret"] == "other-secret"
    assert result["additional_config"]["file_id"] == "f1"
    assert result["additional_config"]["secret_key"] == "already-set"


def test_build_vault_credentials_app_pipedream_provider_adds_app_id():
    from app.services.vault_data_builder import build_vault_credentials

    config = {"app_id": "pd-app-1"}
    result = asyncio.run(
        build_vault_credentials(
            storage_type="app", provider="pipedream", config=config, app_type="sharepoint"
        )
    )
    assert result["app_id"] == "pd-app-1"


# ---------------------------------------------------------------------------
# build_vault_credentials — unrecognized storage_type
# ---------------------------------------------------------------------------
def test_build_vault_credentials_unrecognized_storage_type_returns_fallback():
    from app.services.vault_data_builder import build_vault_credentials

    result = asyncio.run(build_vault_credentials(storage_type="something_else"))
    assert result == {
        "access_key": None,
        "secret_access_key": None,
        "region": None,
        "bucket_name": None,
        "localProvider": None,
        "additional_config": None,
    }


# ---------------------------------------------------------------------------
# enhance_datasource_metadata
# ---------------------------------------------------------------------------
def test_enhance_metadata_local():
    from app.services.vault_data_builder import enhance_datasource_metadata

    with _settings_patch(FILE_UPLOAD_ENV="local", CLOUD_PROVIDER=None):
        result = asyncio.run(
            enhance_datasource_metadata(
                existing_metadata={"filename": "f.csv"}, storage_type="local"
            )
        )

    assert result["localProvider"] == "file_system"
    assert result["storageType"] == "local"
    assert result["localFiles"] == ["f.csv"]
    assert result["credentials"]["access_key"] is None


def test_enhance_metadata_cloud_gcp():
    from app.services.vault_data_builder import enhance_datasource_metadata

    config = {"region": "us-central1", "bucket_name": "b", "project_id": "p1"}
    result = asyncio.run(
        enhance_datasource_metadata(
            existing_metadata={},
            storage_type="cloud",
            provider="gcp",
            config=config,
            location="loc-1",
            accessToken="tok-1",
        )
    )

    assert result["storageType"] == "cloud"
    assert result["cloudProvider"] == "gcp"
    assert result["location"] == "loc-1"
    assert result["accessToken"] == "tok-1"
    assert result["credentials"]["bucket_name"] == "b"
    assert result["credentials"]["project_id"] == "p1"


def test_enhance_metadata_cloud_aws():
    from app.services.vault_data_builder import enhance_datasource_metadata

    config = {"access_key": "ak", "secret_key": "sk", "region": "us-east-1", "bucket_name": "b"}
    result = asyncio.run(
        enhance_datasource_metadata(
            existing_metadata={}, storage_type="cloud", provider="aws", config=config
        )
    )
    assert result["credentials"]["access_key"] == "ak"
    assert result["cloudProvider"] == "aws"


def test_enhance_metadata_app_no_app_type_identity_characterization():
    """The 'no app_type' branch returns `existing_metadata` itself (not a
    copy) because the check happens before `existing_metadata.copy()`."""
    from app.services.vault_data_builder import enhance_datasource_metadata

    existing = {"foo": "bar"}
    result = asyncio.run(
        enhance_datasource_metadata(existing_metadata=existing, storage_type="app", app_type=None)
    )
    assert result is existing


def test_enhance_metadata_app_google_drive():
    from app.services.vault_data_builder import enhance_datasource_metadata

    result = asyncio.run(
        enhance_datasource_metadata(
            existing_metadata={}, storage_type="app", provider="google", app_type="google_drive"
        )
    )
    assert result["storageType"] == "app"
    assert result["appType"] == "googleDrive"
    assert result["databaseType"] == "app"
    assert result["googleDriveConfigured"] is True


def test_enhance_metadata_app_sharepoint_with_connection_settings():
    from app.services.vault_data_builder import enhance_datasource_metadata

    config = {
        "connection_settings": {
            "client_id": "cid",
            "client_secret": "csecret",
            "tenant_id": "tid",
            "site_url": "https://sp.example.com",
            "file_path": "/f",
            "file_name": "f.docx",
            "refresh_token": "rtok",
            "access_token": "atok",
            "email_id": "a@b.com",
            "scope": "Files.Read",
            "oauth_provider": "microsoft",
            "connection_method": "oauth",
        }
    }
    result = asyncio.run(
        enhance_datasource_metadata(
            existing_metadata={}, storage_type="app", provider="microsoft", config=config, app_type="sharepoint"
        )
    )
    assert result["sharePointConfigured"] is True
    assert result["clientId"] == "cid"
    assert result["tenantId"] == "tid"
    assert result["emailId"] == "a@b.com"
    assert result["oauthProvider"] == "microsoft"


def test_enhance_metadata_app_dropbox_and_onedrive_flags():
    from app.services.vault_data_builder import enhance_datasource_metadata

    dropbox_result = asyncio.run(
        enhance_datasource_metadata(existing_metadata={}, storage_type="app", app_type="dropbox")
    )
    assert dropbox_result["dropboxConfigured"] is True

    onedrive_result = asyncio.run(
        enhance_datasource_metadata(existing_metadata={}, storage_type="app", app_type="oneDrive")
    )
    assert onedrive_result["oneDriveConfigured"] is True


def test_enhance_metadata_app_pipedream_app_id_from_config_wins():
    from app.services.vault_data_builder import enhance_datasource_metadata

    config = {"app_id": "config-app-id"}
    result = asyncio.run(
        enhance_datasource_metadata(
            existing_metadata={}, storage_type="app", provider="pipedream", config=config, app_type="sharepoint"
        )
    )
    assert result["credentials"]["app_id"] == "config-app-id"


def test_enhance_metadata_database():
    from app.services.vault_data_builder import enhance_datasource_metadata

    config = {
        "username": "u",
        "password": "p",
        "hostname": "h",
        "port": 1521,
        "databaseName": "db1",
        "serviceName": "ORCL",
    }
    result = asyncio.run(
        enhance_datasource_metadata(
            existing_metadata={}, storage_type="database", provider="oracle", config=config
        )
    )
    assert result["storageType"] == "database"
    assert result["databaseType"] == "oracle"
    assert result["credentials"]["username"] == "u"
    assert result["credentials"]["port"] == "1521"
    assert result["credentials"]["serviceName"] == "ORCL"


def test_enhance_metadata_unrecognized_storage_type_returns_existing_metadata():
    from app.services.vault_data_builder import enhance_datasource_metadata

    existing = {"a": 1}
    result = asyncio.run(
        enhance_datasource_metadata(existing_metadata=existing, storage_type="weird")
    )
    assert result == existing


# ---------------------------------------------------------------------------
# get_environment_info
# ---------------------------------------------------------------------------
def test_get_environment_info_local():
    from app.services.vault_data_builder import get_environment_info

    with _settings_patch(FILE_UPLOAD_ENV="local", CLOUD_PROVIDER=None):
        result = get_environment_info()

    assert result["FILE_UPLOAD_ENV"] == "local"
    assert result["current_configuration"] == "local"
    assert "AWS_ACCESS_KEY_ID" not in result


def test_get_environment_info_cloud_aws():
    from app.services.vault_data_builder import get_environment_info

    with _settings_patch(
        FILE_UPLOAD_ENV="cloud",
        CLOUD_PROVIDER="aws",
        AWS_ACCESS_KEY_ID="ak",
        AWS_REGION="us-east-1",
        AWS_BUCKET_NAME="bucket",
    ):
        result = get_environment_info()

    assert result["current_configuration"] == "cloud-aws"
    assert result["AWS_ACCESS_KEY_ID"] == "ak"
    assert result["AWS_REGION"] == "us-east-1"


def test_get_environment_info_cloud_azure():
    from app.services.vault_data_builder import get_environment_info

    with _settings_patch(
        FILE_UPLOAD_ENV="cloud",
        CLOUD_PROVIDER="azure",
        AZURE_STORAGE_CONNECTION_STRING="conn",
        AZURE_CONTAINER_NAME="container",
    ):
        result = get_environment_info()

    assert result["current_configuration"] == "cloud-azure"
    assert result["AZURE_CONTAINER_NAME"] == "container"


def test_get_environment_info_cloud_oracle():
    from app.services.vault_data_builder import get_environment_info

    with _settings_patch(
        FILE_UPLOAD_ENV="cloud",
        CLOUD_PROVIDER="oracle",
        ORACLE_NAMESPACE="ns",
        ORACLE_BUCKET_NAME="bucket",
    ):
        result = get_environment_info()

    assert result["current_configuration"] == "cloud-oracle"
    assert result["ORACLE_NAMESPACE"] == "ns"
