# Datasource API Testing Guide

## Prerequisites
- Backend server running on `http://localhost:8000`
- Valid JWT token for authentication
- Test workspace and channel IDs

## Test Scenarios

### 1. File Upload APIs

#### 1.1 Single File Upload
```bash
# Test 1: Upload a text file
curl -X POST "http://localhost:8000/api/v1/datasources/upload" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@test_file.txt"

# Test 2: Upload a CSV file
curl -X POST "http://localhost:8000/api/v1/datasources/upload" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@data.csv"

# Test 3: Upload a large file (>10MB)
curl -X POST "http://localhost:8000/api/v1/datasources/upload" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@large_file.pdf"

# Test 4: Upload without file (should fail)
curl -X POST "http://localhost:8000/api/v1/datasources/upload" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: multipart/form-data"

# Test 5: Upload with invalid token (should fail)
curl -X POST "http://localhost:8000/api/v1/datasources/upload" \
  -H "Authorization: Bearer INVALID_TOKEN" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@test_file.txt"
```

#### 1.2 Bulk File Upload
```bash
# Test 1: Upload multiple files
curl -X POST "http://localhost:8000/api/v1/datasources/upload/bulk" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: multipart/form-data" \
  -F "files=@file1.txt" \
  -F "files=@file2.csv" \
  -F "files=@file3.json"

# Test 2: Upload mixed file types
curl -X POST "http://localhost:8000/api/v1/datasources/upload/bulk" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: multipart/form-data" \
  -F "files=@document.pdf" \
  -F "files=@spreadsheet.xlsx" \
  -F "files=@image.png"

# Test 3: Upload with no files (should fail)
curl -X POST "http://localhost:8000/api/v1/datasources/upload/bulk" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: multipart/form-data"

# Test 4: Upload with one invalid file
curl -X POST "http://localhost:8000/api/v1/datasources/upload/bulk" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: multipart/form-data" \
  -F "files=@valid_file.txt" \
  -F "files=@invalid_file.xyz"
```

### 2. Datasource Creation APIs

#### 2.1 Single Datasource Creation

**Local Storage:**
```bash
# Test 1: Create local datasource
curl -X POST "http://localhost:8000/api/v1/datasources/" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Local CSV Dataset",
    "description": "Customer data from local file",
    "filename": "customers_2024.csv",
    "storage_type": "local",
    "channel_id": "YOUR_CHANNEL_ID",
    "file_size": 2048576,
    "file_type": "csv",
    "file_url": "https://example.com/files/customers_2024.csv",
    "datasource_metadata": {
      "source": "manual_upload",
      "tags": ["customers", "csv"],
      "version": "1.0",
      "columns": ["id", "name", "email", "created_at"]
    }
  }'

# Test 2: Create local datasource with minimal data
curl -X POST "http://localhost:8000/api/v1/datasources/" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Simple Local File",
    "filename": "test.txt",
    "storage_type": "local",
    "channel_id": "YOUR_CHANNEL_ID"
  }'
```

**Cloud Storage (S3):**
```bash
# Test 3: Create S3 datasource
curl -X POST "http://localhost:8000/api/v1/datasources/" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "S3 Analytics Data",
    "description": "Analytics data from S3 bucket",
    "filename": "analytics_2024.json",
    "storage_type": "cloud",
    "provider": "s3",
    "channel_id": "YOUR_CHANNEL_ID",
    "config": {
      "bucket": "my-analytics-bucket",
      "key": "data/analytics_2024.json",
      "region": "us-east-1"
    },
    "datasource_metadata": {
      "source": "s3",
      "bucket": "my-analytics-bucket",
      "region": "us-east-1",
      "tags": ["analytics", "json"]
    }
  }'

# Test 4: Create Azure datasource
curl -X POST "http://localhost:8000/api/v1/datasources/" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Azure Blob Data",
    "description": "Data from Azure Blob Storage",
    "filename": "azure_data.csv",
    "storage_type": "cloud",
    "provider": "azure",
    "channel_id": "YOUR_CHANNEL_ID",
    "config": {
      "container": "data-container",
      "blob_name": "azure_data.csv",
      "account_name": "myaccount"
    },
    "datasource_metadata": {
      "source": "azure",
      "container": "data-container",
      "tags": ["azure", "csv"]
    }
  }'
```

**App Storage (Google Drive):**
```bash
# Test 5: Create Google Drive datasource
curl -X POST "http://localhost:8000/api/v1/datasources/" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Google Drive Document",
    "description": "Shared document from Google Drive",
    "filename": "shared_document.docx",
    "storage_type": "app",
    "app_type": "googleDrive",
    "channel_id": "YOUR_CHANNEL_ID",
    "config": {
      "file_id": "1ABC123DEF456GHI789JKL",
      "folder_id": "1XYZ789ABC123DEF456GHI"
    },
    "datasource_metadata": {
      "source": "googleDrive",
      "file_id": "1ABC123DEF456GHI789JKL",
      "tags": ["document", "shared"]
    }
  }'

# Test 6: Create SharePoint datasource
curl -X POST "http://localhost:8000/api/v1/datasources/" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "SharePoint List",
    "description": "SharePoint list data",
    "filename": "sharepoint_list.xlsx",
    "storage_type": "app",
    "app_type": "sharePoint",
    "channel_id": "YOUR_CHANNEL_ID",
    "config": {
      "site_url": "https://company.sharepoint.com/sites/department",
      "list_name": "Project Tasks",
      "item_id": "123"
    },
    "datasource_metadata": {
      "source": "sharePoint",
      "site_url": "https://company.sharepoint.com/sites/department",
      "tags": ["sharepoint", "list"]
    }
  }'
```

#### 2.2 Bulk Datasource Creation

```bash
# Test 1: Create multiple datasources of different types
curl -X POST "http://localhost:8000/api/v1/datasources/bulk" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "datasources": [
      {
        "name": "Local CSV File",
        "filename": "data1.csv",
        "storage_type": "local",
        "channel_id": "YOUR_CHANNEL_ID",
        "datasource_metadata": {"source": "local", "tags": ["csv"]}
      },
      {
        "name": "S3 JSON Data",
        "filename": "data2.json",
        "storage_type": "cloud",
        "provider": "s3",
        "channel_id": "YOUR_CHANNEL_ID",
        "config": {"bucket": "my-bucket", "key": "data2.json"},
        "datasource_metadata": {"source": "s3", "tags": ["json"]}
      },
      {
        "name": "Google Drive Doc",
        "filename": "document.docx",
        "storage_type": "app",
        "app_type": "googleDrive",
        "channel_id": "YOUR_CHANNEL_ID",
        "config": {"file_id": "1ABC123DEF456GHI789JKL"},
        "datasource_metadata": {"source": "googleDrive", "tags": ["document"]}
      }
    ]
  }'

# Test 2: Create bulk with validation errors (should fail)
curl -X POST "http://localhost:8000/api/v1/datasources/bulk" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "datasources": [
      {
        "name": "Valid Datasource",
        "filename": "valid.csv",
        "storage_type": "local",
        "channel_id": "YOUR_CHANNEL_ID"
      },
      {
        "name": "",  # Invalid: empty name
        "filename": "invalid.csv",
        "storage_type": "invalid_type",  # Invalid storage type
        "channel_id": "YOUR_CHANNEL_ID"
      }
    ]
  }'
```

### 3. Datasource from Upload APIs

#### 3.1 Single Datasource from Upload
```bash
# Test 1: Create datasource from uploaded file
curl -X POST "http://localhost:8000/api/v1/datasources/from-upload" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@customer_data.csv" \
  -F "name=Customer Dataset" \
  -F "description=Customer data from uploaded file" \
  -F "channel_id=YOUR_CHANNEL_ID" \
  -F "datasource_metadata={\"source\": \"upload\", \"tags\": [\"customers\", \"csv\"]}"

# Test 2: Create datasource with minimal data
curl -X POST "http://localhost:8000/api/v1/datasources/from-upload" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@simple.txt" \
  -F "name=Simple File" \
  -F "channel_id=YOUR_CHANNEL_ID"

# Test 3: Create datasource with invalid channel (should fail)
curl -X POST "http://localhost:8000/api/v1/datasources/from-upload" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@test.csv" \
  -F "name=Test File" \
  -F "channel_id=INVALID_CHANNEL_ID"
```

#### 3.2 Bulk Datasource from Upload
```bash
# Test 1: Create multiple datasources from uploaded files
curl -X POST "http://localhost:8000/api/v1/datasources/from-upload/bulk" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: multipart/form-data" \
  -F "files=@file1.csv" \
  -F "files=@file2.json" \
  -F "files=@file3.txt" \
  -F "datasources=[{\"name\": \"CSV Data\", \"channel_id\": \"YOUR_CHANNEL_ID\", \"datasource_metadata\": {\"tags\": [\"csv\"]}}, {\"name\": \"JSON Data\", \"channel_id\": \"YOUR_CHANNEL_ID\", \"datasource_metadata\": {\"tags\": [\"json\"]}}, {\"name\": \"Text Data\", \"channel_id\": \"YOUR_CHANNEL_ID\", \"datasource_metadata\": {\"tags\": [\"text\"]}}]"

# Test 2: Mismatch between files and datasource configs (should fail)
curl -X POST "http://localhost:8000/api/v1/datasources/from-upload/bulk" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: multipart/form-data" \
  -F "files=@file1.csv" \
  -F "files=@file2.json" \
  -F "datasources=[{\"name\": \"CSV Data\", \"channel_id\": \"YOUR_CHANNEL_ID\"}]"  # Only 1 config for 2 files
```

### 4. Duplicate Prevention Tests

```bash
# Test 1: Try to create datasource with same name in same channel (should fail)
curl -X POST "http://localhost:8000/api/v1/datasources/" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Duplicate Test",
    "filename": "test.csv",
    "storage_type": "local",
    "channel_id": "YOUR_CHANNEL_ID"
  }'

# Run the same request again - should get 409 Conflict error

# Test 2: Create datasource with same name in different channel (should succeed)
curl -X POST "http://localhost:8000/api/v1/datasources/" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Duplicate Test",
    "filename": "test.csv",
    "storage_type": "local",
    "channel_id": "DIFFERENT_CHANNEL_ID"
  }'
```

### 5. List and Retrieve APIs

#### 5.1 List Datasources
```bash
# Test 1: List all datasources
curl -X GET "http://localhost:8000/api/v1/datasources/" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Test 2: List with pagination
curl -X GET "http://localhost:8000/api/v1/datasources/?page=1&size=10" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Test 3: Filter by storage type
curl -X GET "http://localhost:8000/api/v1/datasources/?storage_type=local" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Test 4: Filter by provider
curl -X GET "http://localhost:8000/api/v1/datasources/?provider=s3" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Test 5: Search by name
curl -X GET "http://localhost:8000/api/v1/datasources/?search=customer" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Test 6: Filter by processing status
curl -X GET "http://localhost:8000/api/v1/datasources/?processing_status=pending" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Test 7: Filter by channel
curl -X GET "http://localhost:8000/api/v1/datasources/?channel_id=YOUR_CHANNEL_ID" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Test 8: Multiple filters
curl -X GET "http://localhost:8000/api/v1/datasources/?storage_type=local&processing_status=completed&page=1&size=5" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### 5.2 Get Datasource Statistics
```bash
# Test 1: Get overall statistics
curl -X GET "http://localhost:8000/api/v1/datasources/stats" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Test 2: Get statistics for specific channel
curl -X GET "http://localhost:8000/api/v1/datasources/stats?channel_id=YOUR_CHANNEL_ID" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### 5.3 Get Single Datasource
```bash
# Test 1: Get existing datasource
curl -X GET "http://localhost:8000/api/v1/datasources/DATASOURCE_ID" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Test 2: Get non-existent datasource (should fail)
curl -X GET "http://localhost:8000/api/v1/datasources/INVALID_ID" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 6. Update and Delete APIs

#### 6.1 Update Datasource
```bash
# Test 1: Update datasource name and description
curl -X PUT "http://localhost:8000/api/v1/datasources/DATASOURCE_ID" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Updated Datasource Name",
    "description": "Updated description",
    "datasource_metadata": {
      "source": "updated",
      "tags": ["updated", "test"],
      "version": "2.0"
    }
  }'

# Test 2: Update with duplicate name in same channel (should fail)
curl -X PUT "http://localhost:8000/api/v1/datasources/DATASOURCE_ID" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Existing Datasource Name"
  }'
```

#### 6.2 Delete Datasource
```bash
# Test 1: Delete existing datasource
curl -X DELETE "http://localhost:8000/api/v1/datasources/DATASOURCE_ID" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Test 2: Delete non-existent datasource (should fail)
curl -X DELETE "http://localhost:8000/api/v1/datasources/INVALID_ID" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 7. Processing APIs

#### 7.1 Process Datasources
```bash
# Test 1: Process multiple datasources
curl -X POST "http://localhost:8000/api/v1/datasources/process" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "datasource_ids": ["DATASOURCE_ID_1", "DATASOURCE_ID_2", "DATASOURCE_ID_3"]
  }'

# Test 2: Process with invalid IDs (should fail)
curl -X POST "http://localhost:8000/api/v1/datasources/process" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "datasource_ids": ["INVALID_ID_1", "INVALID_ID_2"]
  }'
```

### 8. Error Handling Tests

```bash
# Test 1: Invalid storage type
curl -X POST "http://localhost:8000/api/v1/datasources/" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Invalid Storage",
    "filename": "test.csv",
    "storage_type": "invalid_type",
    "channel_id": "YOUR_CHANNEL_ID"
  }'

# Test 2: Missing required fields
curl -X POST "http://localhost:8000/api/v1/datasources/" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Missing Fields"
  }'

# Test 3: Invalid channel ID
curl -X POST "http://localhost:8000/api/v1/datasources/" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Invalid Channel",
    "filename": "test.csv",
    "storage_type": "local",
    "channel_id": "INVALID_CHANNEL_ID"
  }'

# Test 4: Unauthorized access
curl -X POST "http://localhost:8000/api/v1/datasources/" \
  -H "Authorization: Bearer INVALID_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Unauthorized",
    "filename": "test.csv",
    "storage_type": "local",
    "channel_id": "YOUR_CHANNEL_ID"
  }'
```

## PowerShell Testing Script

For Windows users, here's a PowerShell script to test the APIs:

```powershell
# Set variables
$BASE_URL = "http://localhost:8000"
$TOKEN = "YOUR_JWT_TOKEN"
$CHANNEL_ID = "YOUR_CHANNEL_ID"

# Test single file upload
$body = @{
    file = Get-Item "test_file.txt"
}
$headers = @{
    "Authorization" = "Bearer $TOKEN"
}
Invoke-RestMethod -Uri "$BASE_URL/api/v1/datasources/upload" -Method POST -Headers $headers -Form $body

# Test single datasource creation
$body = @{
    name = "Test Local File"
    description = "A test local file datasource"
    filename = "test_file_userId_20241205.txt"
    storage_type = "local"
    channel_id = $CHANNEL_ID
    file_size = 1024
    file_type = "txt"
    file_url = "https://example.com/files/test.txt"
} | ConvertTo-Json

$headers = @{
    "Authorization" = "Bearer $TOKEN"
    "Content-Type" = "application/json"
}
Invoke-RestMethod -Uri "$BASE_URL/api/v1/datasources/" -Method POST -Headers $headers -Body $body
```

## Expected Responses

### Success Responses
- **200 OK**: For GET requests
- **201 Created**: For successful creation
- **204 No Content**: For successful deletion

### Error Responses
- **400 Bad Request**: Invalid data or missing required fields
- **401 Unauthorized**: Invalid or missing token
- **403 Forbidden**: Access denied to channel
- **404 Not Found**: Resource not found
- **409 Conflict**: Duplicate datasource name in same channel
- **422 Unprocessable Entity**: Validation errors

## Notes
- Replace `YOUR_TOKEN`, `YOUR_CHANNEL_ID`, and `DATASOURCE_ID` with actual values
- Test files should be created in the same directory as the curl commands
- Monitor server logs for detailed error messages
- Test both positive and negative scenarios
- Verify database records after successful operations 