# Embedd Type Functionality Tests

This directory contains comprehensive test cases for the embedd_type functionality implemented in the ML API integration.

## Test Files

### 1. `test_ml_service_embedd_type.py`
Tests for the ML service embedd_type functionality:
- `get_embedd_type_from_file_type()` function tests
- ML service API request tests with different embedd_type values
- Error handling tests (timeout, connection errors, API errors)
- Authentication tests (JWT token vs API key)

### 2. `test_datasources_embedd_type.py`
Tests for datasources endpoints with embedd_type logic:
- Bulk datasources creation with different file types
- Regenerate embedding endpoint tests
- Background processing tests
- Mixed file type handling tests

### 3. `test_database_schema.py`
Tests for database schema changes:
- File type column length validation (255 characters)
- Various MIME type acceptance tests
- Maximum length constraint tests
- NULL value handling tests

### 4. `conftest.py`
Pytest configuration and shared fixtures:
- Database session mocks
- User, channel, datasource mocks
- Test client setup

## Running Tests

### Run All Tests
```bash
python tests/run_tests.py
```

### Run Specific Test File
```bash
pytest tests/test_ml_service_embedd_type.py -v
pytest tests/test_datasources_embedd_type.py -v
pytest tests/test_database_schema.py -v
```

### Run with Coverage
```bash
pytest tests/ --cov=app --cov-report=html
```

## Test Coverage

The tests cover:

### File Type Detection
- ✅ Textual MIME types (text/plain, application/pdf, etc.)
- ✅ Tabular MIME types (application/vnd.ms-excel, text/csv, etc.)
- ✅ File extensions (txt, pdf, xlsx, csv, etc.)
- ✅ Edge cases (null, empty, unknown types)
- ✅ Case insensitive handling

### ML API Integration
- ✅ Payload format with embeddType field (camelCase)
- ✅ Different embedd_type values (textual, tabular)
- ✅ Authentication (JWT token, API key)
- ✅ Error handling (timeout, connection, API errors)
- ✅ Request/response validation

### Endpoint Integration
- ✅ Bulk datasources creation
- ✅ Regenerate embedding
- ✅ Background processing
- ✅ Mixed file type handling
- ✅ Default behavior (textual when uncertain)

### Database Schema
- ✅ Column length increase (50 → 255 characters)
- ✅ Long MIME type support
- ✅ Various MIME type acceptance
- ✅ Maximum length constraints
- ✅ NULL value handling

## Test Data

### Textual File Types
- `text/plain`
- `application/pdf`
- `application/msword`
- `application/vnd.openxmlformats-officedocument.wordprocessingml.document`
- `application/vnd.ms-powerpoint`
- `application/vnd.openxmlformats-officedocument.presentationml.presentation`
- `application/rtf`
- `txt`, `pdf`, `doc`, `docx`, `ppt`, `pptx`, `rtf`, `html`, `htm`

### Tabular File Types
- `application/vnd.ms-excel`
- `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- `text/csv`
- `application/csv`
- `application/json`
- `text/json`
- `xls`, `xlsx`, `csv`, `json`

## Expected Behavior

### Embedd Type Determination
1. **All tabular files** → `embeddType: "tabular"`
2. **Mixed or any textual files** → `embeddType: "textual"`
3. **No file types available** → `embeddType: "textual"` (default)

### ML API Payload
```json
{
  "channelId": "channel_id",
  "dataSourcesVaultTokens": ["vault_id"],
  "embeddedDataSourceVaultTokens": [],
  "userId": "user_id",
  "companyId": "company_id",
  "embeddType": "textual" | "tabular"
}
```

### Database Schema
- `file_type` column: `VARCHAR(255)` (increased from 50)
- Supports all common MIME types
- Allows NULL values
- Enforces maximum length constraint

## Notes

- Tests use mocks to avoid database dependencies
- Database schema tests require actual database connection
- All tests are designed to be run independently
- Error scenarios are thoroughly tested
- Edge cases are covered comprehensively