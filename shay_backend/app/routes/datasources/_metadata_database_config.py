"""
Config-field extraction for database-storage datasource metadata.

Private module: called only by _metadata_database.build_database_metadata.
Split out of that file (Raven style-compliance, wave B4) — pulling the
various db_* aliases out of a datasource's config dict is independent of
the metadata dict literal it feeds.
"""

from typing import Any, Dict, Optional


def extract_database_config_fields(config: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Return the individual db_* fields pulled from a database datasource's config."""
    fields = {
        "username": "", "password": "", "hostname": "", "port": "",
        "database_name": "", "schema_name": "", "table_name": "",
        "collection_name": "", "service_name": "", "account_id": "",
        "warehouse": "", "region_name": "", "access_key_id": "", "secret_access_key": "",
    }
    if config:
        fields["username"] = config.get("username") or config.get("user") or ""
        fields["password"] = config.get("password") or config.get("pass") or ""
        fields["hostname"] = config.get("hostname") or config.get("host") or config.get("endpoint") or ""
        fields["port"] = str(config.get("port", "")) if config.get("port") else ""
        fields["database_name"] = config.get("databaseName") or config.get("database") or config.get("dbname") or ""
        fields["schema_name"] = config.get("schemaName") or config.get("schema") or ""
        fields["table_name"] = config.get("tableName") or ""
        fields["collection_name"] = config.get("collectionName") or ""
        fields["service_name"] = config.get("serviceName") or config.get("service") or ""
        fields["account_id"] = config.get("accountId") or config.get("account") or ""
        fields["warehouse"] = config.get("warehouse") or ""
        fields["region_name"] = config.get("regionName") or config.get("region") or ""
        fields["access_key_id"] = config.get("accessKeyId") or config.get("access_key_id") or ""
        fields["secret_access_key"] = config.get("secretAccessKey") or config.get("secret_access_key") or ""
    return fields
