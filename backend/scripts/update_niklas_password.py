#!/usr/bin/env python3
"""Update password for user niklas."""
import sys
import os

# Add parent directory to path
sys.path.insert(0, '/app')

from db.connection import get_driver
from db.queries.users import get_user_by_name, update_user_password
from services.auth import hash_password

def update_niklas_password():
    """Update password for niklas user."""
    driver = get_driver()
    
    username = "niklas"
    new_password = "obdasneguteIdee?2"
    
    # Check if user exists
    user = get_user_by_name(driver, username)
    
    if not user:
        print(f"Error: User '{username}' does not exist!")
        sys.exit(1)
    
    # Hash the new password
    password_hash = hash_password(new_password)
    
    # Update in database
    success = update_user_password(driver, username, password_hash)
    
    if success:
        print(f"✓ Password updated successfully for user '{username}'")
        print(f"  New password: {new_password}")
    else:
        print(f"Error: Failed to update password for user '{username}'")
        sys.exit(1)

if __name__ == "__main__":
    try:
        update_niklas_password()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
