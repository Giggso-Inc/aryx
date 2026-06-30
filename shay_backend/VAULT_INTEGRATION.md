# Vault Integration for Datasource Metadata

## Overview

The vault integration system provides secure storage for datasource metadata. Instead of storing sensitive configuration data directly in the database, the system sends the complete datasource metadata (after cleanup) to an external vault service and stores only a reference to it in the database.

## Architecture

### Key Components

1. **GiggsoVault Model** (`app/models/giggso_vault.py`)
   - Table: `gg_vault`
   - Stores vault references with UUID primary keys
   - Tracks vault entries with metadata about the stored data

2. **VaultService** (`app/services/vault_service.py`)
   - Generic service for interacting with external vault API
   - No data transformation - sends data as-is to vault
   - Handles vault unique ID generation

3. **Datasource Routes** (`app/routes/datasources.py`)
   - Integrates vault logic into datasource creation/update
   - Generates complete metadata, cleans it, sends to vault
   - Stores only vault reference in database

## Configuration

### Environment Variables

```bash
# Vault Integration
CREDENTIALS_MGMT_KV_ENDPOINT="https://your-vault-endpoint.com"
CREDENTIALS_MGMT_VAULT_TOKEN="your-vault-token"
GIGGSO_CONNECTIONS_PATH_PARAM="giggso-connections"
```

### Database Schema

```sql
CREATE TABLE gg_vault (
    giggso_vault_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_id UUID NULL,
    vault_label VARCHAR(50) NULL,
    vault_unique_id VARCHAR(50) NULL UNIQUE,
    created_datetime TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    created_by UUID NULL,
    updated_datetime TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by UUID NULL,
    company_id UUID NULL,
    vault_type VARCHAR(50) NULL
);
```

## Data Flow

### 1. Metadata Generation
- `generate_datasource_metadata()` creates complete metadata structure
- Includes all necessary fields for the datasource type
- Handles different storage types (local, cloud, app)

### 2. Metadata Cleanup
- `clean_metadata()` removes null, empty, and default values
- Keeps only meaningful data for vault storage
- Reduces storage footprint and improves security

### 3. Vault Integration
- `handle_vault_integration()` sends cleaned metadata to vault
- Generates unique vault ID for the entry
- Creates vault record in database
- Returns vault unique ID for reference

### 4. Database Storage
- Stores only `{"vault_unique_id": "..."}` in `datasource_metadata`
- Original config remains in `config` field
- Sensitive data is completely separated from database

## API Integration

### Vault Service Methods

```python
# Generate unique vault ID
vault_unique_id = vault_service.generate_vault_unique_id(user_id, "datasource")

# Save data to vault (no transformation)
saved_id = await vault_service.save_to_vault(metadata, vault_unique_id)
```

### Datasource Creation Flow

```python
# 1. Generate complete metadata
metadata = generate_datasource_metadata(...)

# 2. Clean metadata
cleaned_metadata = clean_metadata(metadata)

# 3. Send to vault
vault_unique_id = await handle_vault_integration(
    datasource_metadata=cleaned_metadata,
    user_id=user_id,
    company_id=company_id,
    db=db
)

# 4. Store only vault reference
final_metadata = {"vault_unique_id": vault_unique_id} if vault_unique_id else cleaned_metadata
```

## Security Benefits

1. **Separation of Concerns**: Sensitive data is stored in dedicated vault service
2. **No Data Transformation**: Vault service is generic and doesn't modify data
3. **Audit Trail**: Vault entries are tracked in database with metadata
4. **Access Control**: Vault can implement its own access controls
5. **Compliance**: Meets security requirements for sensitive data storage

## Error Handling

### Vault Not Configured
- If vault environment variables are not set, system continues without vault
- Metadata is stored directly in database as fallback
- No errors are thrown, graceful degradation

### Vault API Failures
- Vault API errors are logged but don't stop datasource creation
- System falls back to storing metadata directly
- User experience is not impacted

### Database Errors
- Vault record creation failures are handled gracefully
- Datasource creation continues even if vault record fails
- Error messages are logged for debugging

## Usage Examples

### Creating Datasource with Vault Integration

```python
# The system automatically handles vault integration
datasource_data = DatasourceCreate(
    name="My Azure Datasource",
    storage_type="cloud",
    provider="azure",
    config={
        "account_name": "mystorage",
        "container_name": "logs",
        "secret_access_key": "sensitive-key"
    },
    channel_id="channel-uuid"
)

# Vault integration happens automatically
response = await create_datasource(datasource_data, request, db)
```

### Retrieving Vault Data

```python
# To retrieve the actual metadata from vault
vault_unique_id = datasource.datasource_metadata.get("vault_unique_id")
if vault_unique_id:
    # Use vault service to retrieve data
    metadata = await vault_service.retrieve_from_vault(vault_unique_id)
```

## Migration

### Creating Vault Table

```bash
python create_vault_table.py
```

### Testing Vault Integration

```bash
python test_vault_integration.py
```

## Monitoring

### Key Metrics to Monitor

1. **Vault API Response Times**: Track vault service performance
2. **Vault Success Rate**: Monitor vault save/retrieve success rates
3. **Database Storage**: Track metadata storage patterns
4. **Error Rates**: Monitor vault integration failures

### Logging

```python
# Vault operations are logged
print(f"Vault API error: {response.status_code} - {response.text}")
print(f"Error saving to vault: {str(e)}")
```

## Troubleshooting

### Common Issues

1. **Vault Not Configured**
   - Check environment variables
   - Verify vault endpoint is accessible
   - Ensure vault token is valid

2. **Vault API Errors**
   - Check network connectivity
   - Verify API endpoint format
   - Review vault service logs

3. **Database Schema Issues**
   - Run vault table creation script
   - Verify UUID columns are properly configured
   - Check database permissions

### Debug Commands

```bash
# Test vault integration
python test_vault_integration.py

# Check vault table
python -c "from app.models.giggso_vault import GiggsoVault; print('Vault model loaded successfully')"

# Verify environment variables
python -c "import os; print('Vault endpoint:', os.environ.get('CREDENTIALS_MGMT_KV_ENDPOINT'))"
```

## Future Enhancements

1. **Vault Data Retrieval**: Add methods to retrieve data from vault
2. **Vault Data Updates**: Support updating vault entries
3. **Vault Data Deletion**: Implement vault entry cleanup
4. **Vault Encryption**: Add encryption layer for vault data
5. **Vault Backup**: Implement vault data backup strategies 