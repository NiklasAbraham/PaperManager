"""Authentication router - login and register endpoints."""
from __future__ import annotations
import logging
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, status, Depends

from db.connection import get_driver
from db.queries.users import create_user_with_password, get_user_by_name, is_user_admin, list_users, update_user_password, delete_user
from services.auth import hash_password, verify_password, create_access_token, get_current_user

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


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    is_admin: bool = False


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


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
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
    user = create_user_with_password(driver, body.username, password_hash, is_admin=False)
    
    log.info(f"Admin '{current_user}' created new user '{body.username}'")
    
    return {"message": f"User '{body.username}' created successfully"}


# Admin endpoint: Update any user's password
@router.post("/auth/admin/update-password", dependencies=[Depends(get_current_user)])


@router.post("/admin/create-user", status_code=status.HTTP_201_CREATED)
def admin_create_user(body: CreateUserRequest, current_user: str = Depends(get_current_user)):
    """Create a new user - ADMIN ONLY."""
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
        "is_admin": user.get("is_admin", False),
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
    # Remove password hashes from response
    for user in users:
        user.pop("password_hash", None)
    
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
    
    return {"message": "User deleted successfully"}ccess_token = create_access_token(data={"sub": user["name"]})
    
    log.info(f"New user '{body.username}' registered successfully")
    
    return TokenResponse(
        access_token=access_token,
        username=user["name"]
    )


@router.get("/me")
def get_current_user_info(username: str = Depends(get_current_user)):
    """Get information about the currently authenticated user."""
    user = get_user_by_name(get_driver(), username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Remove sensitive information
    user_info = {
        "id": user.get("id"),
        "name": user.get("name"),
        "created_at": user.get("created_at"),
    }
    
    return user_info
