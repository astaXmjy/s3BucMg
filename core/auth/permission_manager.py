from enum import Enum
import os
from typing import List, Dict, Optional
import logging
from datetime import datetime
import json
import uuid
import boto3
from ..aws.config import get_aws_config
logger = logging.getLogger(__name__)

class UserRole(Enum):
   SUPER_ADMIN = "super_admin"
   ADMIN = "admin" 
   MANAGER = "manager"
   USER = "user"

class AccessLevel(Enum):
   FULL = "full"
   READ_WRITE = "read_write"
   READ_ONLY = "read_only"
   NONE = "none"

class ResourceType(Enum):
   BUCKET = "bucket"
   FOLDER = "folder"
   FILE = "file"

class PermissionManager:
   def __init__(self):
       self.dynamodb = boto3.resource('dynamodb', **get_aws_config())
       self.permissions_table = self.dynamodb.Table('permissions')
       self.audit_table = self.dynamodb.Table('permission_audit')
       self._init_role_hierarchy()
       self._init_permission_cache()

   def _init_role_hierarchy(self):
       self.role_hierarchy = {
           UserRole.SUPER_ADMIN: [],
           UserRole.ADMIN: [UserRole.SUPER_ADMIN],
           UserRole.MANAGER: [UserRole.ADMIN],
           UserRole.USER: [UserRole.MANAGER]
       }

   def _init_permission_cache(self):
       self.permission_cache = {}
       self.cache_expiry = 300  # 5 minutes

   async def get_permissions(self, user_id: str, resource_type: ResourceType, 
                           resource_path: Optional[str] = None) -> Dict:
       cache_key = f"{user_id}:{resource_type}:{resource_path}"
       cached = self._get_cached_permissions(cache_key)
       if cached:
           return cached

       try:
           user = await self._get_user(user_id)
           if not user:
               return self._get_default_permissions()

           permissions = await self._calculate_effective_permissions(
               user, resource_type, resource_path
           )
           self._cache_permissions(cache_key, permissions)
           return permissions

       except Exception as e:
           logger.error(f"Error getting permissions: {str(e)}")
           return self._get_default_permissions()

   async def check_permission(self, user_id: str, action: str,
                            resource_type: ResourceType,
                            resource_path: Optional[str] = None) -> bool:
       try:
           permissions = await self.get_permissions(
               user_id, resource_type, resource_path
           )
           
           allowed = self._evaluate_permission(permissions, action)
           
           await self._audit_access(
               user_id, action, resource_type,
               resource_path, allowed
           )
           
           return allowed

       except Exception as e:
           logger.error(f"Permission check error: {str(e)}")
           return False
       
    # Fix for permission_manager.py

   async def _audit_permission_change(self, actor_id: str, target_id: str, 
                                     action: str, permissions: Dict,
                                     resource_type: ResourceType,
                                     resource_path: Optional[str]) -> None:
        """
        Audit permission changes (grant, revoke)

        Args:
            actor_id: ID of user making the change
            target_id: ID of user affected by the change
            action: 'grant' or 'revoke'
            permissions: Permission data being changed
            resource_type: Type of resource
            resource_path: Path to the resource
        """
        try:
            audit_record = {
                'audit_id': str(uuid.uuid4()),
                'timestamp': datetime.utcnow().isoformat(),
                'actor_id': actor_id,
                'target_id': target_id,
                'action': f'permission_{action}',
                'resource_type': resource_type.value,
                'resource_path': resource_path,
                'details': {
                    'permissions': permissions
                }
            }
            await self.audit_table.put_item(Item=audit_record)
        except Exception as e:
            logger.error(f"Audit permission change error: {str(e)}")   
       

   async def grant_permission(self, granter_id: str, grantee_id: str,
                            permissions: Dict, resource_type: ResourceType,
                            resource_path: Optional[str] = None) -> bool:
       try:
           # Verify granter has permission
           if not await self.check_permission(
               granter_id, 'grant_permission',
               resource_type, resource_path
           ):
               return False

           # Create permission record
           permission_id = str(uuid.uuid4())
           permission_record = {
               'permission_id': permission_id,
               'grantee_id': grantee_id,
               'resource_type': resource_type.value,
               'resource_path': resource_path,
               'permissions': permissions,
               'granted_by': granter_id,
               'granted_at': datetime.utcnow().isoformat(),
           }

           await self.permissions_table.put_item(Item=permission_record)
           self._invalidate_cache(grantee_id)
           
           await self._audit_permission_change(
               granter_id, grantee_id, 'grant',
               permissions, resource_type, resource_path
           )

           return True

       except Exception as e:
           logger.error(f"Error granting permission: {str(e)}")
           return False

   async def revoke_permission(self, revoker_id: str, grantee_id: str,
                             permission_id: str) -> bool:
       try:
           permission = await self._get_permission(permission_id)
           if not permission:
               return False

           if not await self.check_permission(
               revoker_id, 'revoke_permission',
               ResourceType(permission['resource_type']),
               permission.get('resource_path')
           ):
               return False

           await self.permissions_table.delete_item(
               Key={'permission_id': permission_id}
           )
           self._invalidate_cache(grantee_id)

           await self._audit_permission_change(
               revoker_id, grantee_id, 'revoke',
               permission['permissions'],
               ResourceType(permission['resource_type']),
               permission.get('resource_path')
           )

           return True

       except Exception as e:
           logger.error(f"Error revoking permission: {str(e)}")
           return False

   async def _calculate_effective_permissions(self, user: Dict,
                                           resource_type: ResourceType,
                                           resource_path: Optional[str]) -> Dict:
       effective_permissions = self._get_default_permissions()

       # Get role-based permissions
       role_permissions = await self._get_role_permissions(
           UserRole(user['role']), resource_type, resource_path
       )
       effective_permissions.update(role_permissions)

       # Get explicit permissions
       explicit_permissions = await self._get_explicit_permissions(
           user['user_id'], resource_type, resource_path
       )
       effective_permissions.update(explicit_permissions)

       # Handle inheritance
       if resource_path:
           parent_permissions = await self._get_inherited_permissions(
               user['user_id'], resource_type, resource_path
           )
           effective_permissions.update(parent_permissions)

       return effective_permissions

   def _evaluate_permission(self, permissions: Dict, action: str) -> bool:
       if permissions.get('full_access'):
           return True

       action_map = {
           'read': 'can_read',
           'write': 'can_write',
           'delete': 'can_delete',
           'share': 'can_share',
           'grant_permission': 'can_grant'
       }

       permission_key = action_map.get(action)
       if not permission_key:
           return False

       return permissions.get(permission_key, False)

   async def _audit_access(self, user_id: str, action: str,
                         resource_type: ResourceType,
                         resource_path: Optional[str],
                         allowed: bool) -> None:
       try:
           audit_record = {
               'audit_id': str(uuid.uuid4()),
               'timestamp': datetime.utcnow().isoformat(),
               'user_id': user_id,
               'action': action,
               'resource_type': resource_type.value,
               'resource_path': resource_path,
               'allowed': allowed
           }
           await self.audit_table.put_item(Item=audit_record)
       except Exception as e:
           logger.error(f"Audit logging error: {str(e)}")

   def _get_cached_permissions(self, cache_key: str) -> Optional[Dict]:
       if cache_key in self.permission_cache:
           cache_entry = self.permission_cache[cache_key]
           if datetime.utcnow().timestamp() - cache_entry['timestamp'] < self.cache_expiry:
               return cache_entry['permissions']
       return None

   def _cache_permissions(self, cache_key: str, permissions: Dict) -> None:
       self.permission_cache[cache_key] = {
           'permissions': permissions,
           'timestamp': datetime.utcnow().timestamp()
       }

   def _invalidate_cache(self, user_id: str) -> None:
       keys_to_remove = [k for k in self.permission_cache if k.startswith(f"{user_id}:")]
       for key in keys_to_remove:
           self.permission_cache.pop(key, None)

   def _get_default_permissions(self) -> Dict:
       return {
           'full_access': False,
           'can_read': False,
           'can_write': False,
           'can_delete': False,
           'can_share': False,
           'can_grant': False
       }
       
    # Add to permission_manager.py after _get_default_permissions method
   async def _get_user(self, user_id: str) -> Optional[Dict]:
        """Get user by ID from the users table"""
        try:
            response = await self.dynamodb.Table('users').get_item(
                Key={
                    'uuid': user_id,
                    'sk': '#USER'
                }
            )
            return response.get('Item')
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {str(e)}")
            return None

   async def _get_role_permissions(self, role: UserRole, 
                                  resource_type: ResourceType,
                                  resource_path: Optional[str]) -> Dict:
        """Get permissions based on user role"""
        try:
            response = await self.permissions_table.query(
                IndexName='RolePermissionsIndex',
                KeyConditionExpression='role = :role',
                ExpressionAttributeValues={
                    ':role': role.value
                }
            )
            permissions = response.get('Items', [])
            return self._combine_permissions(permissions)
        except Exception as e:
            logger.error(f"Error getting role permissions: {str(e)}")
            return self._get_default_permissions()

   async def _get_explicit_permissions(self, user_id: str,
                                      resource_type: ResourceType,
                                      resource_path: Optional[str]) -> Dict:
        """Get explicitly granted permissions"""
        try:
            response = await self.permissions_table.query(
                IndexName='UserPermissionsIndex',
                KeyConditionExpression='user_id = :user_id',
                ExpressionAttributeValues={
                    ':user_id': user_id
                }
            )
            permissions = response.get('Items', [])
            return self._combine_permissions(permissions)
        except Exception as e:
            logger.error(f"Error getting explicit permissions: {str(e)}")
            return self._get_default_permissions()

   async def _get_inherited_permissions(self, user_id: str,
                                       resource_type: ResourceType,
                                       resource_path: str) -> Dict:
        """Get inherited permissions from parent resources"""
        try:
            parent_path = os.path.dirname(resource_path)
            if not parent_path:
                return self._get_default_permissions()

            return await self.get_permissions(user_id, resource_type, parent_path)
        except Exception as e:
            logger.error(f"Error getting inherited permissions: {str(e)}")
            return self._get_default_permissions()

   def _combine_permissions(self, permission_list: List[Dict]) -> Dict:
        """Combine multiple permission sets with precedence rules"""
        combined = self._get_default_permissions()
        for perm in permission_list:
            if perm.get('full_access'):
                return {'full_access': True}
            combined.update(perm)
        return combined   
    
   def get_default_folder_access(self, access_level: str) -> List[str]:
        """
        Get default folders based on user's access level

        Args:
            access_level (str): User's access level (pull/push/both/full)

        Returns:
            List[str]: List of folders user can access
        """
        if access_level == 'full' or access_level == 'admin':
            return ['/']  # Admin gets access to all folders

        # Default structure provides specific areas based on access level
        common_folders = ['/public/']

        if access_level == 'pull' or access_level == 'read_only':
            return common_folders + ['/downloads/', '/shared/']
        elif access_level == 'push' or access_level == 'write_only':
            return common_folders + ['/uploads/', '/temp/']
        elif access_level == 'both' or access_level == 'read_write':
            return common_folders + ['/downloads/', '/uploads/', '/shared/', '/temp/']
        else:
            return common_folders

   async def check_folder_access(self, user_id: str, folder_path: str, action: str) -> bool:
        """
        Check if user has access to a specific folder for a specific action
    
        Args:
            user_id (str): User's UUID
            folder_path (str): Path to folder
            action (str): Action type (read/write/delete)

        Returns:
            bool: Whether access is allowed
        """
        try:
            # Get user
            user = await self._get_user(user_id)
            if not user:
                logger.warning(f"User {user_id} not found for folder access check")
                return False

                # Admin always has access
            if user.get('role') == 'admin' or user.get('access_level') == 'full':
                logger.debug(f"Admin user {user_id} granted {action} access to {folder_path}")
                return True

            # Check folder access
            folder_access = user.get('folder_access', [])

            # Handle root folder
            if folder_path == '/' and '/' in folder_access:
                return self._check_action_allowed(action, user.get('access_level'))

            # Check if user has access to this folder or any parent folder
            for allowed_folder in folder_access:
                if folder_path == allowed_folder or folder_path.startswith(f"{allowed_folder.rstrip('/')}/"):
                    return self._check_action_allowed(action, user.get('access_level'))

            # Check default folder access
            default_folders = self.get_default_folder_access(user.get('access_level'))
            for allowed_folder in default_folders:
                if folder_path == allowed_folder or folder_path.startswith(f"{allowed_folder.rstrip('/')}/"):
                    return self._check_action_allowed(action, user.get('access_level'))

            logger.warning(f"User {user_id} denied {action} access to {folder_path}")
            return False

        except Exception as e:
            logger.error(f"Folder access check error: {str(e)}")
            return False

   def _check_action_allowed(self, action: str, access_level: str) -> bool:
        """
        Check if action is allowed based on access level

        Args:
            action (str): Action to check (read/write/delete)
            access_level (str): User's access level

        Returns:
            bool: Whether action is allowed
        """
        if access_level == 'full' or access_level == 'admin':
            return True

        if action == 'read':
            return access_level in ['pull', 'both', 'read_only', 'read_write']
        elif action == 'write':
            return access_level in ['push', 'both', 'write_only', 'read_write']
        elif action == 'delete':
            return access_level in ['both', 'full', 'read_write']
        else:
            return False