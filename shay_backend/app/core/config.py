"""
Configuration settings for the Log Analyzer Backend
"""

import os
import json
from typing import List, Optional, Union
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
import base64


def _decode_base64_env_or_passthrough(name: str, default: str = "") -> str:
    """Return a UTF-8 decoded base64 env value, or the raw value when it is plain text."""
    value = os.getenv(name, default)
    if not value:
        return value

    normalized = value.strip()
    padded = normalized + ("=" * (-len(normalized) % 4))
    try:
        decoded_bytes = base64.b64decode(padded, validate=True)
        decoded = decoded_bytes.decode("utf-8")
    except Exception:
        return value

    round_trip = base64.b64encode(decoded.encode("utf-8")).decode("utf-8").rstrip("=")
    if round_trip == normalized.rstrip("="):
        return decoded
    return value


class Settings(BaseSettings):
    """Application settings"""
    
    # Application
    APP_NAME: str = "Log Analyzer Backend"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = os.environ.get("DEBUG", "false").lower() == "true"

    # Default identifiers for workspace/channel scoped operations
    DEFAULT_WORKSPACE_ID: Optional[str] =  '47472d9b-3070-4184-b805-0c37f2f79995'
    DEFAULT_CHANNEL_ID: Optional[str] = 'ef48a45f-de2c-4f58-a56d-bb080f317bec'
    
    # Platform Configuration
    PLATFORM_NAME: str = os.environ.get("PLATFORM_NAME","Prism 7")
    PLATFORM_URL: str = os.environ.get("PLATFORM_URL", "http://localhost:3000")
    FRONTEND_URL: str = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    # Public-facing base URL of shay_backend. Must be set in prod — request.base_url
    # resolves to the internal Docker hostname when behind a reverse proxy.
    SHAY_BE_PUBLIC_URL: str = os.environ.get("SHAY_BE_PUBLIC_URL", "")
    # Comma-separated app keys to exclude; from env EXCLUDED_APP_KEYS (use .EXCLUDED_APP_KEYS for list)
    EXCLUDED_APP_KEYS: str = os.environ.get("EXCLUDED_APP_KEYS", "gmail,outlook")

    # Shay View Channel link base URL; if set, used for channel member email when platform is Accsell, else PLATFORM_URL
    SHAY_PLATFORM_URL: Optional[str] = os.environ.get("SHAY_PLATFORM_URL", None)
    
    # Platform logo URLs for email headers (channel member notification). Only used when platform_name is accsell or zaptag; 
    SHAY_LOGO_URL: str = os.environ.get("SHAY_LOGO_URL", "xxxxxxxxxxxxxxxxxx")
    ZAPTAG_LOGO_URL: str = os.environ.get("ZAPTAG_LOGO_URL", "xxxxxxxxxxxxxxxxxxxx")
    
    APP_URL: str = os.environ.get("APP_URL", "http://localhost:8000/app")
    BASE_URL: str = os.environ.get("BASE_URL", "http://localhost:8000")
    ARYX_API_URL_INTERNAL: str = os.environ.get("ARYX_API_URL_INTERNAL", "http://localhost:8088")

    # Marketplace platform: when True, subscription validation uses CHANNEL_COUNT and MESSAGE_COUNT from env
    IS_MARKETPLACE: bool = os.environ.get("IS_MARKETPLACE", "false").lower() == "true"
    CHANNEL_COUNT: int = int(os.environ.get("CHANNEL_COUNT", "1"))
    MESSAGE_COUNT: int = int(os.environ.get("MESSAGE_COUNT", "50"))
    # Per-channel storage limit in MB for marketplace (attachments + datasources); default 200MB
    MARKETPLACE_STORAGE_LIMIT_MB: int = int(os.environ.get("MARKETPLACE_STORAGE_LIMIT_MB", "200"))

    # Default GPT token for automatic gg_vault on company sign-up (dev/prod). Set in env; used when non-empty.
    GPT_TOKEN_TYPE: str = os.environ.get("GPT_TOKEN_TYPE", "")
    GPT_API_KEY: str = os.environ.get("GPT_API_KEY", "")
    GPT_MODEL: str = os.environ.get("GPT_MODEL", "")
    GPT_EMBEDDING_MODEL: str = os.environ.get("GPT_EMBEDDING_MODEL", "")
    GPT_TOKEN_NAME: str = os.environ.get("GPT_TOKEN_NAME", "")
    # Azure: endpoint, deploymentVersion, deploymentName (used when GPT_TOKEN_TYPE is azure)
    GPT_ENDPOINT: str = os.environ.get("GPT_ENDPOINT", "")
    GPT_DEPLOYMENT_VERSION: str = os.environ.get("GPT_DEPLOYMENT_VERSION", "")
    GPT_DEPLOYMENT_NAME: str = os.environ.get("GPT_DEPLOYMENT_NAME", "")
    #client_ID
    CLIENT_ID: str = os.environ.get("CLIENT_ID", "xxxxxxxxxxxxxxxxxxx")
    #client_secret
    CLIENT_SECRET: str = os.environ.get("CLIENT_SECRET", "xxxxxxxxxxxxxxxxx")
    # Security
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "your-super-secret-key-change-this-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JIRA_CLIENT_ID: str = os.environ.get("JIRA_CLIENT_ID", "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
    JIRA_CLIENT_SECRET: str = os.environ.get("JIRA_CLIENT_SECRET", "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
    
    # Database - Updated for PostgreSQL. Set DATABASE_URL in env with correct credentials.
    # Password special chars must be URL-encoded (e.g. @ -> %40, ! -> %21).
    DATABASE_URL: str = os.environ.get(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./log_analyzer.db"
    )
    
    DATABASE_POOL_SIZE: int = int(os.environ.get("DATABASE_POOL_SIZE", "10"))
    DATABASE_MAX_OVERFLOW: int = int(os.environ.get("DATABASE_MAX_OVERFLOW", "20"))
    
    # PostgreSQL Specific Settings
    POSTGRES_USE_NATIVE_UUID: bool = os.environ.get("POSTGRES_USE_NATIVE_UUID", "true").lower() == "true"
    POSTGRES_USE_JSONB: bool = os.environ.get("POSTGRES_USE_JSONB", "true").lower() == "true"
    POSTGRES_ENABLE_PARTITIONING: bool = os.environ.get("POSTGRES_ENABLE_PARTITIONING", "true").lower() == "true"
    POSTGRES_USE_HASH_INDEXES: bool = os.environ.get("POSTGRES_USE_HASH_INDEXES", "true").lower() == "true"
    
    # OAuth2 (Google)
    GOOGLE_CLIENT_ID: str = os.environ.get("GOOGLE_CLIENT_ID", "your-google-client-id")
    GOOGLE_CLIENT_SECRET: str = os.environ.get("GOOGLE_CLIENT_SECRET", "your-google-client-secret")
    GOOGLE_REDIRECT_URI: str = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/sso/google/callback")
    # Separate redirect URI for Gmail workspace connectivity (MCP proxy flow).
    # Must be registered in Google Cloud Console as an authorized redirect URI.
    GOOGLE_GMAIL_REDIRECT_URI: str = os.environ.get(
        "GOOGLE_GMAIL_REDIRECT_URI",
        "http://localhost:8000/api/v1/gmail/connect/callback",
    )

    MICROSOFT_CLIENT_ID: str = os.environ.get("MICROSOFT_CLIENT_ID", "your-microsoft-client-id")
    MICROSOFT_CLIENT_SECRET: str = os.environ.get("MICROSOFT_CLIENT_SECRET", "your-microsoft-client-secret")
    MICROSOFT_TENANT_ID: str = os.environ.get("MICROSOFT_TENANT_ID", "common")
    MICROSOFT_REDIRECT_URI: str = os.environ.get("MICROSOFT_REDIRECT_URI", "http://localhost:8000/api/v1/sso/microsoft/callback")

    # SSO Security
    SSO_STATE_SECRET: str = os.environ.get("SSO_STATE_SECRET", "Xj6QJ2riXqJymGewJ1EYpKMUzI6Tj2IFHhqxpUjatzU")
    
    # CORS
    ALLOWED_ORIGINS: List[str] = [
    o.strip().rstrip("/")   # ← strip trailing slashes
    for o in os.environ.get(
        "ALLOWED_ORGS",
        "http://localhost:3000,http://localhost:8000,http://127.0.0.1:3000,"
        "http://127.0.0.1:8000,https://dev-fourd.shay-ai.com,https://dev-accell.shay-ai.com,"
        "https://dev-zaptag.shay-ai.com,https://alb.accsell.ai,https://app.accsell.ai",
    ).split(",")
    if o.strip()
]  
    ALLOWED_HOSTS: List[str] = os.environ.get("ALLOWED_HST", "localhost,127.0.0.1,*").split(",")
    
    # File Upload
    # Allowed file types matching datasources supported formats: csv, xlsx, xls, json, pdf, docx, doc, txt, pptx, ppt
    # Plus common image formats: png, jpg, jpeg, gif, webp, svg, bmp, ico
    MAX_FILE_SIZE: int = int(os.environ.get("MAX_FILE_SIZE", str(100 * 1024 * 1024)))  # 100MB
    # Store as string to avoid Pydantic Settings JSON parsing issues
    # Will be converted to list via property
    ALLOWED_FILE_TYPES_RAW: Optional[str] = Field(
        default=None,
        alias="ALLOWED_FILE_TYPES",
        exclude=True
    )
    UPLOAD_DIR: str = os.environ.get("UPLOAD_DIR", "uploads")
    
    # Template Configuration
    TEMPLATE_DIR: str = os.environ.get("TEMPLATE_DIR", "\\v1\\template")
    ALLOWED_TEMPLATE_TYPES: List[str] = os.environ.get("ALLOWED_TEMPLATE_TYPES", ".html,.txt,.json").split(",")

    # Customer support email (notifications for API failures and user support requests)
    SUPPORT_EMAIL: str = os.environ.get("SUPPORT_EMAIL", "support@giggso.com")

    #System user config
    SYSTEM_USER_EMAIL: str = os.environ.get("SYSTEM_USER_EMAIL", "xxxxxxxx")
    SYSTEM_USER_NAME: str = os.environ.get("SYSTEM_USER_NAME", "xxxxxxxx")
    SYSTEM_USER_ROLE: str = os.environ.get("SYSTEM_USER_ROLE", "xxxxxxx")
    
    # File Storage URLs
    LOCAL_FILES_URL: str = os.environ.get(
        "LOCAL_FILES_URL", 
        "https://shaydev-mk.giggso.com/staticFiles/contentfile/"
    )
    
    # File Storage Environment
    FILE_UPLOAD_ENV: str = os.environ.get("FILE_UPLOAD_ENV", "local").lower()
    
    # for cloud storage
    CLOUD_PROVIDER: Optional[str] = os.environ.get("CLOUD_PROVIDER")
    
    # AWS S3 Configuration
    AWS_ACCESS_KEY_ID: Optional[str] = os.environ.get("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY: Optional[str] = os.environ.get("AWS_SECRET_ACCESS_KEY")
    AWS_BUCKET_NAME: Optional[str] = os.environ.get("AWS_BUCKET_NAME")
    AWS_REGION: str = os.environ.get("AWS_REGION", "us-east-1")
    
    # Azure Blob Storage Configuration
    AZURE_STORAGE_CONNECTION_STRING: Optional[str] = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    AZURE_CONTAINER_NAME: Optional[str] = os.environ.get("AZURE_CONTAINER_NAME")
    
    # Oracle Cloud Object Storage Configuration
    ORACLE_NAMESPACE: Optional[str] = os.environ.get("ORACLE_NAMESPACE")
    ORACLE_BUCKET_NAME: Optional[str] = os.environ.get("ORACLE_BUCKET_NAME")
    ORACLE_COMPARTMENT_ID: Optional[str] = os.environ.get("ORACLE_COMPARTMENT_ID")
    
    # AI Integration
    OPENAI_API_KEY: Optional[str] = os.environ.get("OPENAI_API_KEY")
    ANTHROPIC_API_KEY: Optional[str] = os.environ.get("ANTHROPIC_API_KEY")
    N8N_WEBHOOK_URL: Optional[str] = os.environ.get("N8N_WEBHOOK_URL")
    PIPEDREAM_WEBHOOK_URL: Optional[str] = os.environ.get("PIPEDREAM_WEBHOOK_URL")
    
    # Email Configuration
    EMAIL_HOST: str = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
    EMAIL_PORT: int = int(os.environ.get("EMAIL_PORT", "587"))
    EMAIL_USERNAME: str = os.environ.get("EMAIL_USERNAME", "email_id")
    EMAIL_PASSWORD: str = os.environ.get("EMAIL_PASSWORD", "app_password")
    EMAIL_FROM: str = os.environ.get("EMAIL_FROM", "email_id")
    EMAIL_USE_TLS: bool = os.environ.get("EMAIL_USE_TLS", "true").lower() == "true"

    # Salesforce CRM workspace connect OAuth proxy
    SF_CONNECT_CLIENT_ID: str = os.environ.get("SF_CONNECT_CLIENT_ID", "")
    SF_CONNECT_CLIENT_SECRET: str = os.environ.get("SF_CONNECT_CLIENT_SECRET", "")
    SF_CONNECT_REDIRECT_URI: str = os.environ.get(
        "SF_CONNECT_REDIRECT_URI",
        "http://localhost:8000/api/v1/sf/connect/callback",
    )

    # Zoho CRM workspace connect OAuth proxy (used by MCP to connect client Zoho accounts)
    ZOHO_CRM_CONNECT_CLIENT_ID: str = os.environ.get("ZOHO_CRM_CONNECT_CLIENT_ID", "")
    ZOHO_CRM_CONNECT_CLIENT_SECRET: str = os.environ.get("ZOHO_CRM_CONNECT_CLIENT_SECRET", "")
    ZOHO_CRM_CONNECT_REDIRECT_URI: str = os.environ.get(
        "ZOHO_CRM_CONNECT_REDIRECT_URI",
        "http://localhost:8000/api/v1/zoho/connect/callback",
    )

    # Zoho Configuration
    ZOHO_BASE_URL: str = os.environ.get("ZOHO_BASE_URL", "XXXXXXXXXX")
    ZOHO_CLIENT_ID: str = os.environ.get("ZOHO_CLIENT_ID", "XXXXXXXXXX")
    ZOHO_CLIENT_SECRET: str = os.environ.get("ZOHO_CLIENT_SECRET", "XXXXXXXXXX")
    ZOHO_REDIRECT_URI: str = os.environ.get("ZOHO_REDIRECT_URI", "XXXXXXXXXX")
    ZOHO_REFRESH_TOKEN: str = os.environ.get("ZOHO_REFRESH_TOKEN", "XXXXXXXXXX")
    ZOHO_TOKEN_URL: str = os.environ.get("ZOHO_TOKEN_URL", "XXXXXXXXXX")
    PRODUCT_ID: str = os.environ.get("PRODUCT_ID", "XXXXXXXXXX")
    ZOHO_ORGANIZATION_ID: str = os.environ.get("ZOHO_ORGANIZATION_ID", "XXXXXXXXXX")
    
    # PRISM Zoho Configuration (for prism7 platform)
    PRISM_ZOHO_BASE_URL: str = os.environ.get("PRISM_ZOHO_BASE_URL", "XXXXXXXXXX")
    PRISM_ZOHO_CLIENT_ID: str = os.environ.get("PRISM_ZOHO_CLIENT_ID", "XXXXXXXXXX")
    PRISM_ZOHO_CLIENT_SECRET: str = os.environ.get("PRISM_ZOHO_CLIENT_SECRET", "XXXXXXXXXX")
    PRISM_ZOHO_REDIRECT_URI: str = os.environ.get("PRISM_ZOHO_REDIRECT_URI", "XXXXXXXXXX")
    PRISM_ZOHO_REFRESH_TOKEN: str = os.environ.get("PRISM_ZOHO_REFRESH_TOKEN", "XXXXXXXXXX")
    PRISM_ZOHO_TOKEN_URL: str = os.environ.get("PRISM_ZOHO_TOKEN_URL", "XXXXXXXXXX")
    PRISM_PRODUCT_ID: str = os.environ.get("PRISM_PRODUCT_ID", "XXXXXXXXXX")
    PRISM_ZOHO_ORGANIZATION_ID: str = os.environ.get("PRISM_ZOHO_ORGANIZATION_ID", "XXXXXXXXXX")

    # Shay Zoho Configuration (for accsell platform)
    SHAY_ZOHO_BASE_URL: str = os.environ.get("SHAY_ZOHO_BASE_URL", "XXXXXXXXXX")
    SHAY_ZOHO_CLIENT_ID: str = os.environ.get("SHAY_ZOHO_CLIENT_ID", "XXXXXXXXXX")
    SHAY_ZOHO_CLIENT_SECRET: str = os.environ.get("SHAY_ZOHO_CLIENT_SECRET", "XXXXXXXXXX")
    SHAY_ZOHO_REDIRECT_URI: str = os.environ.get("SHAY_ZOHO_REDIRECT_URI", "XXXXXXXXXX")
    SHAY_ZOHO_REFRESH_TOKEN: str = os.environ.get("SHAY_ZOHO_REFRESH_TOKEN", "XXXXXXXXXX")
    SHAY_ZOHO_TOKEN_URL: str = os.environ.get("SHAY_ZOHO_TOKEN_URL", "XXXXXXXXXX")
    SHAY_PRODUCT_ID: str = os.environ.get("SHAY_PRODUCT_ID", "XXXXXXXXXX")
    SHAY_ZOHO_ORGANIZATION_ID: str = os.environ.get("SHAY_ZOHO_ORGANIZATION_ID", "XXXXXXXXXX")

    # ZAPTAG Zoho Configuration (for zaptag platform)
    ZAPTAG_ZOHO_BASE_URL: str = os.environ.get("ZAPTAG_ZOHO_BASE_URL", "XXXXXXXXXX")
    ZAPTAG_ZOHO_CLIENT_ID: str = os.environ.get("ZAPTAG_ZOHO_CLIENT_ID", "XXXXXXXXXX")
    ZAPTAG_ZOHO_CLIENT_SECRET: str = os.environ.get("ZAPTAG_ZOHO_CLIENT_SECRET", "XXXXXXXXXX")
    ZAPTAG_ZOHO_REDIRECT_URI: str = os.environ.get("ZAPTAG_ZOHO_REDIRECT_URI", "XXXXXXXXXX")
    ZAPTAG_ZOHO_REFRESH_TOKEN: str = os.environ.get("ZAPTAG_ZOHO_REFRESH_TOKEN", "XXXXXXXXXX")
    ZAPTAG_ZOHO_TOKEN_URL: str = os.environ.get("ZAPTAG_ZOHO_TOKEN_URL", "XXXXXXXXXX")
    ZAPTAG_PRODUCT_ID: str = os.environ.get("ZAPTAG_PRODUCT_ID", "XXXXXXXXXX")
    ZAPTAG_ZOHO_ORGANIZATION_ID: str = os.environ.get("ZAPTAG_ZOHO_ORGANIZATION_ID", "XXXXXXXXXX")

    # SMTP Email Configuration
    SMTP_HOST: str = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USER: str = os.environ.get("SMTP_USER", "email_id")
    SMTP_PASS: str = os.environ.get("SMTP_PASS", "app_password")
    SMTP_FROM: str = os.environ.get("SMTP_FROM", "email_id")
    SMTP_SECURE: bool = os.environ.get("SMTP_SECURE", "true").lower() == "true"  # Default to true for Gmail

    # Logging
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # Log Type Configuration
    SUPPORTED_LOG_TYPES: List[str] = os.environ.get(
        "SUPPORTED_LOG_TYPES",
        "android"
    ).split(",")
    
    # Orchestrator URL (used by Odoo connect proxy to verify credentials).
    # shay_backend forwards the user's Bearer token to the orchestrator on authenticated calls.
    ORCHESTRATOR_URL: str = os.environ.get("ORCHESTRATOR_URL", "http://localhost:9000")

    # ML API Integration
    ML_API_URL: str = os.environ.get("ML_API_URL", "xxxxxxxxxxxxxxx")
    ML_API_KEY: str = _decode_base64_env_or_passthrough("ML_API_KEY", "")
    

    @property
    def is_oracle(self) -> bool:
        """True when DATABASE_URL is Oracle (this environment uses Oracle as the only DB)."""
        return self.DATABASE_URL.strip().lower().startswith("oracle")
        
    @property
    def ALLOWED_FILE_TYPES(self) -> List[str]:
        """
        Parse ALLOWED_FILE_TYPES from environment variable.
        Handles both JSON array format and comma-separated string format.
        """
        # Get the raw value from environment or the field
        raw_value = self.ALLOWED_FILE_TYPES_RAW or os.environ.get(
            "ALLOWED_FILE_TYPES",
            ".csv,.xlsx,.xls,.json,.pdf,.docx,.doc,.txt,.pptx,.ppt,.png,.jpg,.jpeg,.gif,.webp,.svg,.bmp,.ico"
        )
        
        if isinstance(raw_value, list):
            # Already a list, return as-is (normalize by stripping whitespace)
            return [ext.strip() for ext in raw_value if ext.strip()]
        
        if isinstance(raw_value, str):
            # Try to parse as JSON first (for JSON array strings)
            try:
                parsed = json.loads(raw_value)
                if isinstance(parsed, list):
                    return [ext.strip() for ext in parsed if ext.strip()]
            except (json.JSONDecodeError, ValueError):
                pass
            # If not JSON, treat as comma-separated string
            return [ext.strip() for ext in raw_value.split(",") if ext.strip()]
        
        # Default fallback
        return [".csv", ".xlsx", ".xls", ".json", ".pdf", ".docx", ".doc", ".txt", ".pptx", ".ppt", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"]
    
    @field_validator('SUPPORTED_LOG_TYPES')
    @classmethod
    def validate_supported_log_types(cls, v):
        """Validate that supported log types are not empty"""
        if not v or not any(v):
            raise ValueError("SUPPORTED_LOG_TYPES cannot be empty")
        return [log_type.strip().lower() for log_type in v if log_type.strip()]
    
    # Socket Configuration
    SOCKET_SERVER_URL: str = os.environ.get("SOCKET_SERVER_URL", "wss://dev-fourd.shay-ai.com/socket.io/")
    SOCKET_TIMEOUT: int = int(os.environ.get("SOCKET_TIMEOUT", "10000"))
    SOCKET_RECONNECTION: bool = os.environ.get("SOCKET_RECONNECTION", "true").lower() == "true"
    SOCKET_RECONNECTION_ATTEMPTS: int = int(os.environ.get("SOCKET_RECONNECTION_ATTEMPTS", "10"))
    SOCKET_RECONNECTION_DELAY: int = int(os.environ.get("SOCKET_RECONNECTION_DELAY", "1000"))
    SOCKET_RECONNECTION_DELAY_MAX: int = int(os.environ.get("SOCKET_RECONNECTION_DELAY_MAX", "5000"))
    SOCKET_AUTO_CONNECT: bool = os.environ.get("SOCKET_AUTO_CONNECT", "true").lower() == "true"
    SOCKET_TRANSPORTS: str = "websocket,polling"
    SOCKET_NAMESPACE: Optional[str] = os.environ.get("SOCKET_NAMESPACE")
    SOCKET_HEARTBEAT_INTERVAL: int = int(os.environ.get("SOCKET_HEARTBEAT_INTERVAL", "30000"))
    SOCKET_HEARTBEAT_TIMEOUT: int = int(os.environ.get("SOCKET_HEARTBEAT_TIMEOUT", "60000"))
    SOCKET_AUTH_TOKEN: Optional[str] = os.environ.get("SOCKET_AUTH_TOKEN")
    SOCKET_DEBUG: bool = os.environ.get("SOCKET_DEBUG", "false").lower() == "true"
    
    class Config:
        # Remove env_file to use environment variables directly
        case_sensitive = True


# Create settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get application settings"""
    return settings


def is_postgresql() -> bool:
    """True when DATABASE_URL is PostgreSQL (default flow unchanged)."""
    url = (settings.DATABASE_URL or "").strip().lower()
    return url.startswith("postgresql") or "postgresql+" in url


def is_oracle() -> bool:
    """True when DATABASE_URL is Oracle."""
    url = (settings.DATABASE_URL or "").strip().lower()
    return url.startswith("oracle") or "oracle+" in url


def is_sqlite() -> bool:
    """True when DATABASE_URL is SQLite."""
    url = (settings.DATABASE_URL or "").strip().lower()
    return url.startswith("sqlite")
