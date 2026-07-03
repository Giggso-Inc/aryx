# Datasource Upload and Management Guide

## Overview

The datasource system now supports file uploads from users with comprehensive metadata management and duplicate prevention. The system integrates with the existing file storage service to handle uploads based on environment configuration.

## New Features

### 1. File Upload APIs
- **Single File Upload**: Upload individual files to the system
- **Bulk File Upload**: Upload multiple files in a single request
- **Datasource from Upload**: Create datasources directly from uploaded files
- **Bulk Datasource from Upload**: Create multiple datasources from uploaded files

### 2. Metadata Management
- **datasource_metadata**: JSONB field for storing configuration details and additional metadata
- **Flexible Configuration**: Support for custom metadata fields
- **Version Control**: Track metadata versions and changes

### 3. Duplicate Prevention
- **Channel-level Uniqueness**: Prevent same datasource name in the same channel
- **Company-level Isolation**: Datasources are isolated by company
- **Validation**: Automatic validation during creation

## API Endpoints

### 1. Single File Upload
```bash
POST /api/v1/datasources/upload
```

**Request:**
- Method: `POST`
- Content-Type: `multipart/form-data`
- Body: `file` (file upload)

**Response:**
```json
{
  "filename": "original_filename.txt",
  "file_size": 1024,
  "file_type": "text/plain",
  "file_url": "https://storage.example.com/files/uuid.txt",
  "storage_path": "/uploads/uuid.txt",
  "provider": "local"
}
```

### 2. Bulk File Upload
```bash
POST /api/v1/datasources/upload/bulk
```

**Request:**
- Method: `POST`
- Content-Type: `multipart/form-data`
- Body: `files` (multiple file uploads)

**Response:**
```json
{
  "uploaded_files": [
    {
      "filename": "file1.txt",
      "file_size": 512,
      "file_type": "text/plain",
      "file_url": "https://storage.example.com/files/uuid1.txt",
      "storage_path": "/uploads/uuid1.txt",
      "provider": "local"
    }
  ],
  "failed_files": [],
  "total_uploaded": 1,
  "total_failed": 0
}
```

### 3. Create Datasource from Upload
```bash
POST /api/v1/datasources/from-upload
```

**Request:**
- Method: `POST`
- Content-Type: `multipart/form-data`
- Body:
  - `file` (file upload)
  - `name` (string)
  - `description` (string, optional)
  - `channel_id` (string)
  - `datasource_metadata` (JSON string, optional)

**Response:**
```json
{
  "id": "uuid",
  "name": "My Datasource",
  "description": "Description",
  "filename": "original_filename.txt",
  "storage_type": "local",
  "provider": "local",
  "config": {
    "file_path": "/uploads/uuid.txt",
    "original_filename": "original_filename.txt"
  },
  "datasource_metadata": {
    "source": "file_upload",
    "tags": ["test"],
    "version": "1.0"
  },
  "file_size": 1024,
  "file_type": "text/plain",
  "file_url": "https://storage.example.com/files/uuid.txt",
  "channel_id": "channel_uuid",
  "workspace_id": "workspace_uuid",
  "company_id": "company_uuid",
  "added_by": "user_uuid",
  "is_active": true,
  "is_processed": false,
  "processing_status": "pending",
  "error_message": null,
  "last_processed_at": null,
  "processing_time": null,
  "record_count": 0,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

### 4. Bulk Datasource from Upload
```bash
POST /api/v1/datasources/from-upload/bulk
```

**Request:**
- Method: `POST`
- Content-Type: `multipart/form-data`
- Body:
  - `files` (multiple file uploads)
  - `datasources` (JSON string with array of datasource configurations)

**Response:**
```json
{
  "created_datasources": [...],
  "failed_datasources": [...],
  "total_created": 2,
  "total_failed": 0
}
```

## Metadata Examples

### 1. CSV File Metadata
```json
{
  "datasource_metadata": {
    "source": "file_upload",
    "tags": ["csv", "data", "analytics"],
    "version": "1.0",
    "encoding": "utf-8",
    "delimiter": ",",
    "has_header": true,
    "total_rows": 1000,
    "columns": ["name", "age", "city"],
    "custom_fields": {
      "department": "engineering",
      "project": "data_analysis",
      "data_quality": "high"
    }
  }
}
```

### 2. Excel File Metadata
```json
{
  "datasource_metadata": {
    "source": "file_upload",
    "tags": ["excel", "financial", "reports"],
    "version": "1.0",
    "sheet_name": "Sheet1",
    "total_rows": 500,
    "total_columns": 10,
    "has_formulas": true,
    "custom_fields": {
      "quarter": "Q4",
      "year": "2024",
      "department": "finance"
    }
  }
}
```

### 3. JSON File Metadata
```json
{
  "datasource_metadata": {
    "source": "file_upload",
    "tags": ["json", "api", "logs"],
    "version": "1.0",
    "schema_version": "2.0",
    "data_type": "application_logs",
    "log_levels": ["INFO", "ERROR", "WARNING"],
    "custom_fields": {
      "application": "web_service",
      "environment": "production"
    }
  }
}
```

## Testing Instructions

### 1. Run Migration
```bash
python run_migration.py migrations/add_datasources_table.py
```

### 2. Test File Upload
```bash
# Single file upload
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@test_file.txt" \
  http://localhost:8000/api/v1/datasources/upload

# Bulk file upload
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "files=@file1.txt" \
  -F "files=@file2.csv" \
  -F "files=@file3.json" \
  http://localhost:8000/api/v1/datasources/upload/bulk
```

### 3. Test Datasource Creation from Upload
```bash
# Single datasource from upload
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@data.csv" \
  -F "name=My CSV Data" \
  -F "description=CSV file with user data" \
  -F "channel_id=CHANNEL_UUID" \
  -F "datasource_metadata={\"source\":\"file_upload\",\"tags\":[\"csv\",\"data\"]}" \
  http://localhost:8000/api/v1/datasources/from-upload

# Bulk datasource from upload
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "files=@file1.csv" \
  -F "files=@file2.xlsx" \
  -F "datasources=[{\"name\":\"File 1\",\"channel_id\":\"CHANNEL_UUID\"},{\"name\":\"File 2\",\"channel_id\":\"CHANNEL_UUID\"}]" \
  http://localhost:8000/api/v1/datasources/from-upload/bulk
```

### 4. Test Duplicate Prevention
```bash
# First attempt - should succeed
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Datasource",
    "description": "Test description",
    "filename": "test.csv",
    "storage_type": "local",
    "channel_id": "CHANNEL_UUID",
    "datasource_metadata": {"test": "duplicate_prevention"}
  }' \
  http://localhost:8000/api/v1/datasources/

# Second attempt - should fail with 409 Conflict
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Datasource",
    "description": "Test description",
    "filename": "test.csv",
    "storage_type": "local",
    "channel_id": "CHANNEL_UUID",
    "datasource_metadata": {"test": "duplicate_prevention"}
  }' \
  http://localhost:8000/api/v1/datasources/
```

## Environment Configuration

The file upload functionality uses the existing file storage service configuration:

### Local Storage
```bash
FILE_STORAGE_PROVIDER=local
LOCAL_FILES_URL=https://your-domain.com/staticFiles/contentfile/
```

### Cloud Storage (S3)
```bash
FILE_STORAGE_PROVIDER=s3
S3_BUCKET_NAME=your-bucket
S3_REGION=us-east-1
S3_ACCESS_KEY=your-access-key
S3_SECRET_KEY=your-secret-key
```

## Error Handling

### Common Error Responses

1. **Duplicate Datasource (409 Conflict)**
```json
{
  "detail": "Datasource with name 'Test Datasource' already exists in this channel"
}
```

2. **File Upload Error (500 Internal Server Error)**
```json
{
  "detail": "File upload failed: Storage service error"
}
```

3. **Invalid File (400 Bad Request)**
```json
{
  "detail": "File name is required"
}
```

4. **Permission Error (403 Forbidden)**
```json
{
  "detail": "Access denied to channel"
}
```

## Best Practices

### 1. File Upload
- Always validate file types and sizes
- Use unique filenames to prevent conflicts
- Implement proper error handling
- Consider file compression for large uploads

### 2. Metadata Management
- Use consistent metadata structure
- Include version information
- Add relevant tags for categorization
- Store processing configuration in metadata

### 3. Duplicate Prevention
- Use descriptive, unique names
- Implement naming conventions
- Consider adding timestamps to names
- Validate before upload

### 4. Security
- Validate file types and content
- Implement file size limits
- Use secure file storage
- Sanitize metadata input

## Integration Examples

### Frontend Integration (JavaScript)
```javascript
// Single file upload
async function uploadFile(file) {
  const formData = new FormData();
  formData.append('file', file);
  
  const response = await fetch('/api/v1/datasources/upload', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`
    },
    body: formData
  });
  
  return response.json();
}

// Create datasource from upload
async function createDatasourceFromUpload(file, datasourceConfig) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('name', datasourceConfig.name);
  formData.append('description', datasourceConfig.description);
  formData.append('channel_id', datasourceConfig.channelId);
  formData.append('datasource_metadata', JSON.stringify(datasourceConfig.metadata));
  
  const response = await fetch('/api/v1/datasources/from-upload', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`
    },
    body: formData
  });
  
  return response.json();
}
```

### Python Integration
```python
import requests

def upload_file_with_metadata(file_path, datasource_config, token):
    with open(file_path, 'rb') as f:
        files = {'file': f}
        data = {
            'name': datasource_config['name'],
            'description': datasource_config['description'],
            'channel_id': datasource_config['channel_id'],
            'datasource_metadata': json.dumps(datasource_config['metadata'])
        }
        
        response = requests.post(
            'http://localhost:8000/api/v1/datasources/from-upload',
            headers={'Authorization': f'Bearer {token}'},
            files=files,
            data=data
        )
        
        return response.json()
```

This implementation provides a comprehensive file upload and datasource management system with proper metadata handling, duplicate prevention, and integration with the existing file storage infrastructure. 