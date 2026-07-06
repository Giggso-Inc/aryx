# Environment Setup Guide

This guide explains how to configure environment variables for the Log Analyzer Backend in different deployment environments.

## Environment Variables

The application now uses environment variables directly instead of `.env` files for better security and DevOps practices.

### Required Environment Variables

```bash
# Security
SECRET_KEY=your-super-secret-key-change-this-in-production

# Database
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/log_analyzer

# OAuth2 (Google)
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/sso/google/callback

# File Storage
LOCAL_FILES_URL=https://your-domain.com/staticFiles/contentfile/
```

### Optional Environment Variables

```bash
# Application
DEBUG=false
APP_NAME="Log Analyzer Backend"
APP_VERSION="1.0.0"

# Database Settings
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20

# CORS
ALLOWED_ORIGINS=["http://localhost:3000", "http://localhost:8000"]
ALLOWED_HOSTS=["localhost", "127.0.0.1"]

# File Upload
MAX_FILE_SIZE=104857600  # 100MB
ALLOWED_FILE_TYPES=[".log", ".txt", ".json", ".xml"]
UPLOAD_DIR="uploads"

# AI Integration
OPENAI_API_KEY=your-openai-api-key
ANTHROPIC_API_KEY=your-anthropic-api-key
N8N_WEBHOOK_URL=https://your-n8n-instance.com/webhook/log-analysis
PIPEDREAM_WEBHOOK_URL=https://your-pipedream-url.com

# Logging
LOG_LEVEL="INFO"
```

## Deployment Environments

### Development

For local development, you can set environment variables in your shell:

```bash
export SECRET_KEY="dev-secret-key"
export DATABASE_URL="postgresql+asyncpg://postgres:password@localhost:5432/log_analyzer"
export GOOGLE_CLIENT_ID="your-google-client-id"
export GOOGLE_CLIENT_SECRET="your-google-client-secret"
export GOOGLE_REDIRECT_URI="http://localhost:8000/api/v1/sso/google/callback"
export LOCAL_FILES_URL="https://dev.example.com/staticFiles/contentfile/"
```

### Docker Compose

For Docker Compose, set environment variables in the `docker-compose.yml`:

```yaml
environment:
  - DATABASE_URL=postgresql+asyncpg://postgres:password@postgres:5432/log_analyzer
  - SECRET_KEY=your-super-secret-key-change-this-in-production
  - GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
  - GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}
  - GOOGLE_REDIRECT_URI=${GOOGLE_REDIRECT_URI}
  - LOCAL_FILES_URL=${LOCAL_FILES_URL:-https://dev.example.com/staticFiles/contentfile/}
```

### Kubernetes

For Kubernetes, create a ConfigMap and Secret:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: log-analyzer-config
data:
  DATABASE_URL: "postgresql+asyncpg://postgres:password@postgres:5432/log_analyzer"
  LOCAL_FILES_URL: "https://prod.example.com/staticFiles/contentfile/"
  DEBUG: "false"
  LOG_LEVEL: "INFO"
---
apiVersion: v1
kind: Secret
metadata:
  name: log-analyzer-secrets
type: Opaque
data:
  SECRET_KEY: <base64-encoded-secret>
  GOOGLE_CLIENT_ID: <base64-encoded-client-id>
  GOOGLE_CLIENT_SECRET: <base64-encoded-client-secret>
  GOOGLE_REDIRECT_URI: <base64-encoded-redirect-uri>
```

### Production Deployment

For production deployments, work with your DevOps team to set these environment variables:

1. **Required for all environments:**
   - `SECRET_KEY` - Unique secret key for JWT tokens
   - `DATABASE_URL` - PostgreSQL connection string
   - `GOOGLE_CLIENT_ID` - Google OAuth client ID
   - `GOOGLE_CLIENT_SECRET` - Google OAuth client secret
   - `GOOGLE_REDIRECT_URI` - OAuth redirect URI
   - `LOCAL_FILES_URL` - Base URL for static file serving

2. **Environment-specific values:**
   - Development: `LOCAL_FILES_URL=https://dev.example.com/staticFiles/contentfile/`
   - UAT: `LOCAL_FILES_URL=https://uat.example.com/staticFiles/contentfile/`
   - Production: `LOCAL_FILES_URL=https://prod.example.com/staticFiles/contentfile/`

## Security Best Practices

1. **Never commit secrets to version control**
2. **Use different secrets for each environment**
3. **Rotate secrets regularly**
4. **Use environment-specific URLs for file storage**
5. **Limit database access to application servers only**

## Testing Environment Variables

You can test that environment variables are loaded correctly by checking the `/health` endpoint or adding debug logging to the application startup. 
