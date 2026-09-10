"""
File storage service for handling local and cloud file uploads.

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md): this used to be a single
395-line app/services/file_storage.py. It is now a package split one
provider per module, with every name any route module imported re-exported
here so `from app.services.file_storage import X` needs zero changes
anywhere else in the app.

  base.py    - FileStorageProvider ABC + generate_structured_path
  local.py   - LocalFileStorage (disk)
  aws.py     - AWSFileStorage (S3), BOTO3_AVAILABLE
  azure.py   - AzureFileStorage (Blob), AZURE_AVAILABLE
  oracle.py  - OracleFileStorage (Object Storage), OCI_AVAILABLE
  service.py - FileStorageService (provider selection facade) +
               get_file_storage_service() singleton accessor
"""

from .base import FileStorageProvider, generate_structured_path
from .local import LocalFileStorage
from .aws import AWSFileStorage, BOTO3_AVAILABLE
from .azure import AzureFileStorage, AZURE_AVAILABLE
from .oracle import OracleFileStorage, OCI_AVAILABLE
from .service import FileStorageService, get_file_storage_service

__all__ = [
    "FileStorageProvider",
    "generate_structured_path",
    "LocalFileStorage",
    "AWSFileStorage",
    "BOTO3_AVAILABLE",
    "AzureFileStorage",
    "AZURE_AVAILABLE",
    "OracleFileStorage",
    "OCI_AVAILABLE",
    "FileStorageService",
    "get_file_storage_service",
]
