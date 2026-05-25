#!/usr/bin/env python3
"""Create the default 'niklas' user with a password."""
import sys
import os
from getpass import getpass

# Add parent directory to path so we can import from backend
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.connection import get_driver
from db.queries.users import create_user_with_password, get_user_by_name, update_user_password
from services.auth import hash_password


def create_default_user():
    """Create or update the default niklas user."""
    driver = get_driver()
    
    username = "niklas"
    
    # Check if user already exists
    existing_user = get_user_by_name(driver, username)
    
    if existing_user:
        print(f"User '{username}' already exists.")
        update = input("Do you want to update the password? (y/N): ").lower().strip()
        if update != 'y':
            print("Aborted.")
            return
        
        # Update password
        password = getpass("Enter new password: ")
        password_confirm = getpass("Confirm password: ")
        
        if password != password_confirm:
            print("Error: Passwords do not match!")
            sys.exit(1)
        
        if len(password) < 8:
            print("Error: Password must be at least 8 characters long!")
            sys.exit(1)
        
        password_hash = hash_password(password)
        update_user_password(driver, username, password_hash)
        print(f"✓ Password updated for user '{username}'")
    else:
        # Create new user
        print(f"Creating user '{username}'...")
        password = getpass("Enter password: ")
        password_confirm = getpass("Confirm password: ")
        
        if password != password_confirm:
            print("Error: Passwords do not match!")
            sys.exit(1)
        
        if len(password) < 8:
            print("Error: Password must be at least 8 characters long!")
            sys.exit(1)
        
        password_hash = hash_password(password)
        user = create_user_with_password(driver, username, password_hash)
        print(f"✓ User '{username}' created successfully!")
        print(f"  User ID: {user['id']}")


if __name__ == "__main__":
    try:
        create_default_user()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
