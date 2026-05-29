"""Authentication router - login and register endpoints."""
from __future__ import annotations
import logging
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, status, Depends

from db.connection import get_driver
from db.queries.users import create_user_with_password, get_user_by_name, is_user_admin, list_users, update_user_password, delete_user, merge_users, update_user_ai_keys
from services.auth import hash_password, verify_password, create_access_token, get_current_user
from services.user_ai_config import get_masked_ai_config

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str


class UpdatePasswordRequest(BaseModel):
    username: str
    new_password: str


class MergeUsersRequest(BaseModel):
    user_a: str
    user_b: str
    keep_user: str
    password_source_user: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    is_admin: bool = False


class UpdateAiKeysRequest(BaseModel):
    anthropic_api_key: str = ""
    anthropic_work_api_key: str = ""
    anthropic_work_base_url: str = ""


def _require_niklas_admin(current_user: str) -> None:
    """Restrict sensitive teammate administration actions to niklas."""
    if not is_user_admin(get_driver(), current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can perform this action"
        )
    if current_user.lower() != "niklas":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only user 'niklas' can perform this action"
        )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest):
    """Authenticate a user and return a JWT token."""
    # Get user from database
    user = get_user_by_name(get_driver(), body.username)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if user has a password hash (old users might not)
    password_hash = user.get("password_hash")
    if not password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This user account needs to be migrated. Please contact administrator.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password
    if not verify_password(body.password, password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create JWT token
    access_token = create_access_token(data={"sub": user["name"]})
    
    log.info(f"User '{body.username}' logged in successfully")
    
    return TokenResponse(
        access_token=access_token,
        username=user["name"],
        is_admin=user.get("is_admin", False)
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, current_user: str = Depends(get_current_user)):
    """Register a new user - ADMIN ONLY."""
    # Check if current user is admin
    if not is_user_admin(get_driver(), current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can create new users"
        )
    
    # Check if username already exists
    existing_user = get_user_by_name(get_driver(), body.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists"
        )
    
    # Validate password
    if len(body.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters"
        )
    
    # Hash password and create user
    password_hash = hash_password(body.password)
    user = create_user_with_password(get_driver(), body.username, password_hash, is_admin=False)
    
    log.info(f"Admin '{current_user}' created new user '{body.username}'")
    
    return {"message": f"User '{body.username}' created successfully"}


@router.post("/admin/create-user", status_code=status.HTTP_201_CREATED)
def admin_create_user(body: CreateUserRequest, current_user: str = Depends(get_current_user)):
    """Create a new user - ADMIN ONLY."""
    _require_niklas_admin(current_user)
    
    # Check if username already exists
    existing_user = get_user_by_name(get_driver(), body.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists"
        )
    
    # Validate password
    if len(body.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long"
        )
    
    # Hash password and create user
    password_hash = hash_password(body.password)
    user = create_user_with_password(get_driver(), body.username, password_hash, is_admin=False)
    
    log.info(f"Admin '{current_user}' created new user '{body.username}'")
    
    return {"message": "User created successfully", "username": user["name"]}


@router.post("/admin/update-password")
def admin_update_password(body: UpdatePasswordRequest, current_user: str = Depends(get_current_user)):
    """Update a user's password - ADMIN ONLY."""
    # Check if current user is admin
    if not is_user_admin(get_driver(), current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can update passwords"
        )
    
    # Check if user exists
    user = get_user_by_name(get_driver(), body.username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Validate password
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long"
        )
    
    # Hash and update password
    password_hash = hash_password(body.new_password)
    success = update_user_password(get_driver(), body.username, password_hash)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update password"
        )
    
    log.info(f"Admin '{current_user}' updated password for user '{body.username}'")
    
    return {"message": "Password updated successfully"}


@router.post("/admin/merge-users")
def admin_merge_users(body: MergeUsersRequest, current_user: str = Depends(get_current_user)):
    """Merge two users into one and preserve selected password source - NIKLAS ADMIN ONLY."""
    _require_niklas_admin(current_user)

    user_a = body.user_a.strip()
    user_b = body.user_b.strip()
    keep_user = body.keep_user.strip()
    password_source_user = body.password_source_user.strip()

    if not user_a or not user_b:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Both users are required")
    if user_a == user_b:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Choose two different users")
    if keep_user not in (user_a, user_b):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="keep_user must match one selected user")
    if password_source_user not in (user_a, user_b):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="password_source_user must match one selected user")

    try:
        result = merge_users(
            get_driver(),
            user_a=user_a,
            user_b=user_b,
            keep_name=keep_user,
            password_source_name=password_source_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    log.info(
        "Admin '%s' merged users '%s' and '%s'; kept '%s'; password source '%s'",
        current_user,
        user_a,
        user_b,
        keep_user,
        password_source_user,
    )

    return result


@router.get("/admin/users")
def admin_list_users(current_user: str = Depends(get_current_user)):
    """List all users - ADMIN ONLY."""
    # Check if current user is admin
    if not is_user_admin(get_driver(), current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can list users"
        )
    
    users = list_users(get_driver())
    _SENSITIVE = {"password_hash", "anthropic_api_key", "anthropic_work_api_key", "anthropic_work_base_url"}
    for user in users:
        for field in _SENSITIVE:
            user.pop(field, None)

    return users


@router.delete("/admin/users/{username}")
def admin_delete_user(username: str, current_user: str = Depends(get_current_user)):
    """Delete a user - ADMIN ONLY."""
    # Check if current user is admin
    if not is_user_admin(get_driver(), current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can delete users"
        )
    
    # Prevent deleting yourself
    if username == current_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )
    
    success = delete_user(get_driver(), username)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    log.info(f"Admin '{current_user}' deleted user '{username}'")
    
    return {"message": "User deleted successfully"}


@router.get("/me")
def get_me(current_user: str = Depends(get_current_user)):
    """Get current user info."""
    user = get_user_by_name(get_driver(), current_user)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return {
        "username": user["name"],
        "is_admin": user.get("is_admin", False)
    }


@router.get("/me/api-keys")
def get_my_ai_keys(current_user: str = Depends(get_current_user)):
    """Get masked AI key status for the current user (never returns raw keys)."""
    return get_masked_ai_config(current_user)


@router.put("/me/api-keys")
def update_my_ai_keys(body: UpdateAiKeysRequest, current_user: str = Depends(get_current_user)):
    """Update AI keys for current user. Empty values clear user-specific values."""
    success = update_user_ai_keys(
        get_driver(),
        name=current_user,
        anthropic_api_key=body.anthropic_api_key,
        anthropic_work_api_key=body.anthropic_work_api_key,
        anthropic_work_base_url=body.anthropic_work_base_url,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return get_masked_ai_config(current_user)
