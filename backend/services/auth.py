"""Authentication service - password hashing and JWT token management."""
from datetime import datetime, timedelta, timezone
from contextvars import ContextVar, Token
from typing import Optional
import logging
from jose import JWTError, jwt
import bcrypt
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import secrets
from config import settings

# Secret key for JWT.
# Configure JWT_SECRET_KEY in production to keep sessions valid across restarts.
SECRET_KEY = settings.jwt_secret_key.strip() or secrets.token_hex(32)
log = logging.getLogger(__name__)
if not settings.jwt_secret_key.strip():
    log.warning(
        "JWT_SECRET_KEY is not set. Tokens will be invalid after backend restart."
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

security = HTTPBearer()
_request_user_ctx: ContextVar[Optional[str]] = ContextVar("request_user", default=None)


def hash_password(password: str) -> str:
    """Hash a plain password using bcrypt."""
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def decode_token_optional(token: str) -> Optional[dict]:
    """Decode token and return None instead of raising on invalid/expired tokens."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def set_request_user(username: Optional[str]) -> Token:
    """Store request user in context for downstream services."""
    return _request_user_ctx.set(username)


def reset_request_user(token: Token) -> None:
    """Reset request user context after request completes."""
    _request_user_ctx.reset(token)


def get_request_user() -> Optional[str]:
    """Get request user from context (None outside request scope)."""
    return _request_user_ctx.get()


def extract_user_from_auth_header(authorization_header: Optional[str]) -> Optional[str]:
    """Extract username from Authorization header without raising exceptions."""
    if not authorization_header:
        return None
    prefix = "Bearer "
    if not authorization_header.startswith(prefix):
        return None
    payload = decode_token_optional(authorization_header[len(prefix):].strip())
    if not payload:
        return None
    return payload.get("sub")


def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)) -> str:
    """Extract the current user from the JWT token."""
    token = credentials.credentials
    payload = decode_token(token)
    username: str = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username
