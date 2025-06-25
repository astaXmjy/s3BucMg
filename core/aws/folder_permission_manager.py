from typing import List, Dict, Optional
from datetime import datetime
import uuid
import boto3
from core.aws.config import get_aws_config
from models.permission import PermissionManager, ResourceType, AccessLevel
from core.utils.audit_logger import AuditLogger

class FolderPermissionManager:
    def __init__(self, permission_manager: PermissionManager, audit_logger: AuditLogger):
        self.permission_manager = permission_manager
        self.audit_logger = audit_logger
        self.dynamodb = boto3.resource('dynamodb', **get_aws_config())
        self.folder_permissions_table = self.dynamodb.Table('folder_permissions')
        
    async def grant_folder_access(self, admin_id: str, user_id: str, 
                                folder_path: str, access_level: AccessLevel) -> bool:
        """Grant folder access to a user"""
        try:
            # Check if admin has permission to grant access
            if not await self.permission_manager.check_permission(
                admin_id, 'grant_permission', ResourceType.FOLDER, folder_path
            ):
                await self.audit_logger.log_event(
                    'folder_access_denied',
                    admin_id,
                    {'action': 'grant', 'folder': folder_path, 'target_user': user_id}
                )
                return False

            # Create permission mapping
            permission_mapping = {
                'permission_id': str(uuid.uuid4()),
                'user_id': user_id,
                'folder_path': folder_path,
                'access_level': access_level.value,
                'granted_by': admin_id,
                'granted_at': datetime.utcnow().isoformat(),
                'last_modified': datetime.utcnow().isoformat()
            }

            # Store in DynamoDB
            await self.folder_permissions_table.put_item(Item=permission_mapping)
            
            # Log the event
            await self.audit_logger.log_event(
                'folder_access_granted',
                admin_id,
                {
                    'target_user': user_id,
                    'folder': folder_path,
                    'access_level': access_level.value
                }
            )
            
            return True

        except Exception as e:
            await self.audit_logger.log_event(
                'folder_access_error',
                admin_id,
                {
                    'error': str(e),
                    'target_user': user_id,
                    'folder': folder_path
                }
            )
            return False

    async def revoke_folder_access(self, admin_id: str, user_id: str, 
                                 folder_path: str) -> bool:
        """Revoke folder access from a user"""
        try:
            # Check if admin has permission to revoke access
            if not await self.permission_manager.check_permission(
                admin_id, 'revoke_permission', ResourceType.FOLDER, folder_path
            ):
                await self.audit_logger.log_event(
                    'folder_access_denied',
                    admin_id,
                    {'action': 'revoke', 'folder': folder_path, 'target_user': user_id}
                )
                return False

            # Remove from DynamoDB
            await self.folder_permissions_table.delete_item(
                Key={
                    'user_id': user_id,
                    'folder_path': folder_path
                }
            )

            # Log the event
            await self.audit_logger.log_event(
                'folder_access_revoked',
                admin_id,
                {
                    'target_user': user_id,
                    'folder': folder_path
                }
            )

            return True

        except Exception as e:
            await self.audit_logger.log_event(
                'folder_access_error',
                admin_id,
                {
                    'error': str(e),
                    'target_user': user_id,
                    'folder': folder_path
                }
            )
            return False

    async def check_folder_access(self, user_id: str, folder_path: str, 
                                required_access: AccessLevel) -> bool:
        """Check if a user has the required access level for a folder"""
        try:
            # Get user's folder permissions
            response = await self.folder_permissions_table.get_item(
                Key={
                    'user_id': user_id,
                    'folder_path': folder_path
                }
            )
            
            if 'Item' not in response:
                return False

            permission = response['Item']
            user_access = AccessLevel(permission['access_level'])
            
            # Access level hierarchy
            access_hierarchy = {
                AccessLevel.FULL: 4,
                AccessLevel.READ_WRITE: 3,
                AccessLevel.READ_ONLY: 2,
                AccessLevel.NONE: 1
            }
            
            return access_hierarchy[user_access] >= access_hierarchy[required_access]

        except Exception as e:
            await self.audit_logger.log_event(
                'folder_access_check_error',
                user_id,
                {
                    'error': str(e),
                    'folder': folder_path,
                    'required_access': required_access.value
                }
            )
            return False

    async def get_user_folder_permissions(self, user_id: str) -> List[Dict]:
        """Get all folder permissions for a user"""
        try:
            response = await self.folder_permissions_table.query(
                KeyConditionExpression='user_id = :uid',
                ExpressionAttributeValues={
                    ':uid': user_id
                }
            )
            
            return response.get('Items', [])

        except Exception as e:
            await self.audit_logger.log_event(
                'get_permissions_error',
                user_id,
                {'error': str(e)}
            )
            return []

    async def get_folder_users(self, folder_path: str) -> List[Dict]:
        """Get all users who have access to a folder"""
        try:
            response = await self.folder_permissions_table.scan(
                FilterExpression='folder_path = :fp',
                ExpressionAttributeValues={
                    ':fp': folder_path
                }
            )
            
            return response.get('Items', [])

        except Exception as e:
            await self.audit_logger.log_event(
                'get_folder_users_error',
                'system',
                {
                    'error': str(e),
                    'folder': folder_path
                }
            )
            return [] 