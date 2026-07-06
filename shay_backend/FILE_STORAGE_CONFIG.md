# File Storage Configuration

This document explains how to configure file storage for the Log Analyzer Backend.

## Environment Variables

### Basic Configuration

```bash
# Set to 'local' for local storage or 'cloud' for cloud storage
FILE_UPLOAD_ENV=local
```

### Local Storage Configuration

When `FILE_UPLOAD_ENV=local`:

```bash
# Directory where files will be stored locally
UPLOAD_DIR=uploads
```

### Cloud Storage Configuration

When `FILE_UPLOAD_ENV=cloud`, you need to specify a cloud provider:

```bash
# Cloud provider (aws, azure, oracle)
CLOUD_PROVIDER=aws
```

#### AWS S3 Configuration

```bash
CLOUD_PROVIDER=aws
AWS_ACCESS_KEY_ID=your_aws_access_key_id
AWS_SECRET_ACCESS_KEY=your_aws_secret_access_key
AWS_BUCKET_NAME=your_s3_bucket_name
AWS_REGION=us-east-1
```

#### Azure Blob Storage Configuration

```bash
CLOUD_PROVIDER=azure
AZURE_STORAGE_CONNECTION_STRING=your_azure_storage_connection_string
AZURE_CONTAINER_NAME=your_container_name
```

#### Oracle Cloud Object Storage Configuration

```bash
CLOUD_PROVIDER=oracle
ORACLE_NAMESPACE=your_oracle_namespace
ORACLE_BUCKET_NAME=your_oracle_bucket_name
ORACLE_COMPARTMENT_ID=your_oracle_compartment_id
```

**Note:** For Oracle Cloud, you need to configure the OCI CLI and have a `~/.oci/config` file.

## Usage Examples

### Local Storage
```bash
FILE_UPLOAD_ENV=local
UPLOAD_DIR=uploads
```

### AWS S3
```bash
FILE_UPLOAD_ENV=cloud
CLOUD_PROVIDER=aws
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_BUCKET_NAME=my-log-analyzer-bucket
AWS_REGION=us-east-1
```

### Azure Blob Storage
```bash
FILE_UPLOAD_ENV=cloud
CLOUD_PROVIDER=azure
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=myaccount;AccountKey=mykey;EndpointSuffix=core.windows.net
AZURE_CONTAINER_NAME=log-files
```

### Oracle Cloud Object Storage
```bash
FILE_UPLOAD_ENV=cloud
CLOUD_PROVIDER=oracle
ORACLE_NAMESPACE=my-namespace
ORACLE_BUCKET_NAME=log-files-bucket
ORACLE_COMPARTMENT_ID=ocid1.compartment.oc1..example
```

## Dependencies

For cloud storage, you need to install additional packages:

```bash
# For AWS
pip install boto3

# For Azure
pip install azure-storage-blob

# For Oracle
pip install oci
```

## File Storage Service

The file storage service automatically handles:
- File uploads to the configured storage provider
- File downloads from the configured storage provider
- File deletion from the configured storage provider
- Storage metadata tracking (provider, URL, etc.)

## API Endpoints

The attachment upload API (`/api/v1/attachments/upload`) now uses the configured storage provider:

- **Local**: Files stored in the local filesystem
- **Cloud**: Files stored in the configured cloud provider

The system automatically handles the storage provider selection based on your environment configuration. 