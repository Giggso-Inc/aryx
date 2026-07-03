# Vault Dev Setup Issue and Solution

## Problem Description

The bulk datasource API was working in dev, but vault data was not being stored properly. The logs showed:

```
INFO:     172.18.0.13:54892 - "POST /api/v1/datasources/upload/bulk HTTP/1.1" 200 OK
External vault save successful, created database record with ID: 5d97b1ed/919158f8
INFO:     172.18.0.13:54894 - "POST /api/v1/datasources/bulk HTTP/1.1" 200 OK
```

**The Issue**: The vault service was connecting to **localhost:8200** (your local vault) instead of the **dev vault** where it should be storing data.

## Root Cause

The vault service had hardcoded fallback values that pointed to localhost:8200:

```python
# OLD CODE (PROBLEMATIC)
vault_endpoint_encoded = os.environ.get("CREDENTIALS_MGMT_KV_ENDPOINT","aHR0cDovL2xvY2FsaG9zdDo4MjAwL3YxL2N1YmJ5aG9sZQ==")
vault_token_encoded = os.environ.get("CREDENTIALS_MGMT_VAULT_TOKEN","aHZzLklGWmN4M3F3Sk96emk3MldPNmREd2hXVQ==")
```

When decoded, these values are:
- **Endpoint**: `http://localhost:8200/v1/cubbyhole`
- **Token**: `hvs.IFZcx3qwJOzzi72WO6dDwhWU`

This means:
1. **In local environment**: ✅ Works correctly (connects to your local vault)
2. **In dev environment**: ❌ Wrong! Still connects to localhost instead of dev vault

## Solution

### Option 1: Set Environment Variables (Recommended)

Set these environment variables in your dev environment:

```bash
# For dev vault (replace with actual dev vault endpoint and token)
CREDENTIALS_MGMT_KV_ENDPOINT="<base64-encoded-dev-vault-endpoint>"
CREDENTIALS_MGMT_VAULT_TOKEN="<base64-encoded-dev-vault-token>"
GIGGSO_CONNECTIONS_PATH_PARAM="giggso/connections"
```

### Option 2: Use the Setup Script

Run the provided setup script to help configure dev vault:

```bash
python scripts/setup_dev_vault.py
```

The script will:
1. Show current vault configuration
2. Help you encode dev vault details
3. Test the vault connection

### Option 3: Manual Base64 Encoding

If you know your dev vault details, encode them manually:

```bash
# Encode endpoint
echo -n "https://dev-vault.example.com/v1/secret" | base64

# Encode token
echo -n "your-dev-vault-token" | base64
```

## What Was Fixed

### 1. Removed Hardcoded Localhost Fallbacks

**Before:**
```python
# Hardcoded localhost fallbacks
vault_endpoint_encoded = os.environ.get("CREDENTIALS_MGMT_KV_ENDPOINT","aHR0cDovL2xvY2FsaG9zdDo4MjAwL3YxL2N1YmJ5aG9sZQ==")
```

**After:**
```python
# No hardcoded fallbacks - must be explicitly configured
vault_endpoint_encoded = os.environ.get("CREDENTIALS_MGMT_KV_ENDPOINT")
```

### 2. Better Error Handling

**Before:**
```python
# Would always try to connect to localhost
if not self.vault_endpoint or not self.vault_token:
    return vault_unique_id  # Fallback behavior
```

**After:**
```python
# Fails gracefully when not configured
if not self.vault_endpoint or not self.vault_token:
    print("Vault not configured - cannot save data")
    return None
```

### 3. Improved Logging

The vault service now provides clear feedback:
- When vault is not configured
- When vault connection fails
- When vault operations succeed

## Environment Variables Reference

| Variable | Description | Example |
|----------|-------------|---------|
| `CREDENTIALS_MGMT_KV_ENDPOINT` | Base64 encoded vault API endpoint | `aHR0cHM6Ly9kZXYtdmF1bHQuZXhhbXBsZS5jb20vdjEvc2VjcmV0` |
| `CREDENTIALS_MGMT_VAULT_TOKEN` | Base64 encoded vault authentication token | `eW91ci1kZXYtdmF1bHQtdG9rZW4=` |
| `GIGGSO_CONNECTIONS_PATH_PARAM` | Path for vault connections (plain text) | `giggso/connections` |

## Testing

After setting up the environment variables:

1. **Restart your application**
2. **Check logs** for vault configuration messages
3. **Test bulk upload** - should now connect to dev vault
4. **Verify data storage** in dev vault

## Expected Log Output

**When properly configured:**
```
Vault service configured successfully for endpoint: https://dev-vault.example.com/v1/secret
Attempting to save to vault at: https://dev-vault.example.com/v1/secret/giggso/connections/5d97b1ed/abc12345
Successfully saved to vault with ID: 5d97b1ed/abc12345
External vault save successful, created database record with ID: 5d97b1ed/abc12345
```

**When not configured:**
```
Vault service not configured - environment variables not set
Set CREDENTIALS_MGMT_KV_ENDPOINT and CREDENTIALS_MGMT_VAULT_TOKEN to enable vault integration
Vault not configured - cannot save data with ID: 5d97b1ed/abc12345
```

## Troubleshooting

### Issue: "Vault not configured" messages
**Solution**: Set the required environment variables

### Issue: "Vault API error" messages
**Solution**: Check dev vault endpoint and token are correct

### Issue: Still connecting to localhost
**Solution**: Ensure environment variables are set and application is restarted

### Issue: Base64 decoding errors
**Solution**: Verify environment variables contain valid base64 encoded strings

## Security Notes

- Vault tokens are sensitive - never commit them to version control
- Use base64 encoding for environment variables in CI/CD
- Rotate vault tokens regularly
- Monitor vault access logs
