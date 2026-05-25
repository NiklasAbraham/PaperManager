#!/usr/bin/env python3
"""Mark niklas as admin."""
import sys
sys.path.insert(0, '/app')

from db.connection import get_driver
from db.queries.users import set_user_admin

def make_niklas_admin():
    """Set niklas as admin user."""
    driver = get_driver()
    success = set_user_admin(driver, "niklas", True)
    
    if success:
        print("✓ User 'niklas' is now an admin")
    else:
        print("Error: Failed to set admin status")
        sys.exit(1)

if __name__ == "__main__":
    try:
        make_niklas_admin()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
