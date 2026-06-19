"""Authentication service - password hashing and JWT token management."""
from datetime import datetime, timedelta, timezone
from contextvars import ContextVar, Token
from typing import Optional
import logging
import re
from jose import JWTError, jwt
import bcrypt
from fastapi import HTTPException, Request, Response, Security, status
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

# Name of the httpOnly cookie that carries the session JWT for browser clients.
# Keeping the token in an httpOnly cookie (instead of localStorage) means it is
# never readable from JavaScript, so an XSS bug cannot exfiltrate the session.
ACCESS_COOKIE_NAME = "pm_session"

# auto_error=False so requests without a bearer header fall through to the cookie.
security = HTTPBearer(auto_error=False)
_request_user_ctx: ContextVar[Optional[str]] = ContextVar("request_user", default=None)

# Password policy: minimum length plus required character classes.
PASSWORD_MIN_LENGTH = 8
_PASSWORD_REQUIREMENTS = [
    (re.compile(r"[a-z]"), "a lowercase letter"),
    (re.compile(r"[A-Z]"), "an uppercase letter"),
    (re.compile(r"[0-9]"), "a digit"),
]


def validate_password_strength(password: str) -> None:
    """Raise HTTP 400 if the password does not meet the strength policy."""
    problems: list[str] = []
    if len(password) < PASSWORD_MIN_LENGTH:
        problems.append(f"at least {PASSWORD_MIN_LENGTH} characters")
    for pattern, description in _PASSWORD_REQUIREMENTS:
        if not pattern.search(password):
            problems.append(description)
    if problems:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain " + ", ".join(problems) + ".",
        )


def _cookie_is_secure() -> bool:
    """Mark the session cookie Secure when the app is served over HTTPS."""
    return settings.frontend_url.strip().lower().startswith("https")


def set_auth_cookie(response: Response, token: str) -> None:
    """Store the session JWT in an httpOnly, SameSite=Lax cookie."""
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=_cookie_is_secure(),
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    """Remove the session cookie (logout)."""
    response.delete_cookie(
        key=ACCESS_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=_cookie_is_secure(),
        samesite="lax",
    )


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


def extract_user_from_request(request: Request) -> Optional[str]:
    """Resolve the request user from the Authorization header or session cookie."""
    user = extract_user_from_auth_header(request.headers.get("Authorization"))
    if user:
        return user
    cookie_token = request.cookies.get(ACCESS_COOKIE_NAME)
    if not cookie_token:
        return None
    payload = decode_token_optional(cookie_token)
    return payload.get("sub") if payload else None


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> str:
    """Extract the current user from the bearer token or the session cookie."""
    if credentials and credentials.credentials:
        token = credentials.credentials
    else:
        token = request.cookies.get(ACCESS_COOKIE_NAME)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(token)
    username: str = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username
