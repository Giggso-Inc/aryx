"""
Authentication utilities and JWT token management
"""

import logging
import uuid
import warnings
from datetime import datetime, timedelta
from typing import Optional, Union
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import settings

logger = logging.getLogger(__name__)

# Suppress bcrypt version warning from passlib
warnings.filterwarnings('ignore', message='.*bcrypt version.*', category=UserWarning)
warnings.filterwarnings('ignore', message='.*trapped.*error reading bcrypt version.*', category=UserWarning)

# Direct bcrypt import as fallback
try:
    import bcrypt
    BCrypt_AVAILABLE = True
    logger.debug("Direct bcrypt import successful")
except ImportError:
    BCrypt_AVAILABLE = False
    logger.warning("Direct bcrypt import failed")

# Fix bcrypt version detection for passlib compatibility
# This prevents the AttributeError warning when passlib tries to read bcrypt.__about__.__version__
try:
    import bcrypt
    # Add __about__ attribute if missing (for bcrypt 4.x compatibility with passlib)
    if not hasattr(bcrypt, '__about__'):
        class _BcryptAbout:
            __version__ = getattr(bcrypt, '__version__', '4.3.0')
        bcrypt.__about__ = _BcryptAbout()
except Exception:
    pass  # If this fails, passlib will handle it

# Password hashing with bcrypt compatibility
try:
    # Check bcrypt version and configure accordingly
    import bcrypt
    bcrypt_version = getattr(bcrypt, '__version__', 'unknown')
    # Try to get version from __about__ if available
    if hasattr(bcrypt, '__about__'):
        bcrypt_version = getattr(bcrypt.__about__, '__version__', bcrypt_version)
    logger.debug("Detected bcrypt version: %s", bcrypt_version)
    
    if bcrypt_version.startswith('5.'):
        # bcrypt 5.x configuration
        pwd_context = CryptContext(
            schemes=["bcrypt"], 
            deprecated="auto",
            bcrypt__default_rounds=12,
            bcrypt__min_rounds=4,
            bcrypt__max_rounds=31,
            bcrypt__truncate_error=False
        )
        logger.debug("Bcrypt 5.x context initialized successfully")
    else:
        # bcrypt 4.x configuration
        pwd_context = CryptContext(
            schemes=["bcrypt"], 
            deprecated="auto",
            bcrypt__default_rounds=12,
            bcrypt__min_rounds=4,
            bcrypt__max_rounds=31
        )
        logger.debug("Bcrypt 4.x context initialized successfully")
        
except Exception as e:
    logger.warning("Error initializing bcrypt context: %s", e)
    # Fallback to basic configuration
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    logger.warning("Using fallback bcrypt configuration")

# JWT token security
security = HTTPBearer()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """Create JWT refresh token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    """Verify JWT token and return payload"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None


def decode_access_token(token: str) -> dict:
    """Decode JWT access token and return payload (alias for verify_token)"""
    payload = verify_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


def get_current_user_payload(credentials: HTTPAuthorizationCredentials = security) -> dict:
    """Get current user from JWT token"""
    token = credentials.credentials
    payload = verify_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return payload


def hash_password(password: str) -> str:
    """Hash password using bcrypt with length validation"""
    # Validate and truncate password to bcrypt's 72-byte limit
    password = validate_password_length(password)
    
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash with length validation"""
    try:
        # Validate and truncate password to bcrypt's 72-byte limit
        plain_password = validate_password_length(plain_password)
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.warning("Passlib password verification failed; trying direct bcrypt fallback: %s", e)
        # Try direct bcrypt as fallback
        if BCrypt_AVAILABLE:
            try:
                # Ensure password is bytes for direct bcrypt
                password_bytes = plain_password.encode('utf-8')
                hash_bytes = hashed_password.encode('utf-8')
                return bcrypt.checkpw(password_bytes, hash_bytes)
            except Exception as bcrypt_error:
                logger.warning("Direct bcrypt verification failed: %s", bcrypt_error)
                raise
        else:
            raise


def get_password_hash(password: str) -> str:
    """Get password hash (alias for hash_password)"""
    return hash_password(password)


def validate_password_length(password: str) -> str:
    """
    Validate and truncate password to bcrypt's 72-byte limit.
    
    Args:
        password: The password to validate
        
    Returns:
        str: Password truncated to 72 bytes if necessary
        
    Raises:
        ValueError: If password is empty or None
    """
    if not password:
        raise ValueError("Password cannot be empty")
    
    # Convert to bytes to check actual byte length
    password_bytes = password.encode('utf-8')
    
    if len(password_bytes) > 72:
        # Truncate to 72 bytes, but be careful with UTF-8 character boundaries
        truncated_bytes = password_bytes[:72]
        # Find the last complete UTF-8 character
        while truncated_bytes and truncated_bytes[-1] & 0x80 and not (truncated_bytes[-1] & 0x40):
            truncated_bytes = truncated_bytes[:-1]
        password = truncated_bytes.decode('utf-8', errors='ignore')
        logger.warning("Password exceeded bcrypt's 72-byte limit and was truncated before verification")
    
    return password


def generate_user_id() -> str:
    """Generate unique user ID"""
    return str(uuid.uuid4())


def generate_company_id() -> str:
    """Generate unique company ID"""
    return str(uuid.uuid4())


def generate_workspace_id() -> str:
    """Generate unique workspace ID"""
    return str(uuid.uuid4())


def generate_message_id() -> str:
    """Generate unique message ID"""
    return str(uuid.uuid4())


def generate_approval_id() -> str:
    """
    Generate a unique approval ID.
    
    This function creates a new UUID and converts it to a string for use
    as an approval identifier in the database.
    
    Returns:
        str: A unique UUID string for the approval
        
    Author: Karthick Chandrasekar
    Date: 19-08-2025
    Version: 1.0.0
    """
    return str(uuid.uuid4())


def generate_attachment_id() -> str:
    """Generate unique attachment ID"""
    return str(uuid.uuid4())


def generate_channel_id() -> str:
    """Generate unique channel ID"""
    return str(uuid.uuid4())


def generate_ai_response_id() -> str:
    """Generate unique AI response ID"""
    return str(uuid.uuid4())


class TokenData:
    """Token data model"""
    def __init__(self, user_id: str, email: str, role: str, company_id: Optional[str] = None):
        self.user_id = user_id
        self.email = email
        self.role = role
        self.company_id = company_id


def create_token_data(user_id: str, email: str, role: str, company_id: Optional[str] = None) -> dict:
    """Create token data dictionary"""
    return {
        "sub": user_id,
        "email": email,
        "role": role,
        "company_id": company_id,
        "type": "access"
    } 
