import asyncio
import sys
import os

# Ensure the script can find the core modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.auth.user_manager import UserManager
from core.utils.audit_logger import AuditLogger
from core.utils.cache_manager import CacheManager
from core.auth.permission_manager import PermissionManager

async def create_users():
    """Create two users with different access levels"""
    # Initialize managers
    audit_logger = AuditLogger()
    cache_manager = CacheManager()
    permission_manager = PermissionManager()
    
    user_manager = UserManager(
        audit_logger=audit_logger,
        cache_manager=cache_manager,
        permission_manager=permission_manager
    )
    
    # User 1: Pull access
    pull_user_data = {
        'username': 'soham',
        'password': 'soham@123',
        'email': 'soham@example.com',
        'role': 'user',
        'access_level': 'pull',
        'folder_access': ['public/', 'shared/']
    }
    
    # User 2: Push access
    push_user_data = {
        'username': 'uid',
        'password': 'uid/pwd',
        'email': 'uid@example.com',
        'role': 'user', 
        'access_level': 'push',
        'folder_access': ['users/uid/', 'uploads/']
    }
    
    try:
        # Create pull access user
        pull_result = await user_manager.create_user(pull_user_data)
        print("Pull Access User Creation Result:")
        print(pull_result)
        
        # Create push access user
        push_result = await user_manager.create_user(push_user_data)
        print("\nPush Access User Creation Result:")
        print(push_result)
        
    except Exception as e:
        print(f"Error creating users: {e}")

def main():
    # Run the async function
    asyncio.run(create_users())

if __name__ == '__main__':
    main()