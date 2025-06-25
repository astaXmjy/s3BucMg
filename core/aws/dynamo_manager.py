# core/aws/dynamo_manager.py
import boto3
import bcrypt
import uuid
from datetime import datetime
from .config import AWSConfig  # Changed from AppConfig to AWSConfig
import logging
from typing import Dict, List, Optional
from ..utils.cache_manager import CacheManager
from ..utils.audit_logger import AuditLogger
import asyncio

logger = logging.getLogger(__name__)

class DynamoManager:
   def __init__(self, cache_manager: Optional[CacheManager] = None, 
                audit_logger: Optional[AuditLogger] = None):
        config = AWSConfig.get_aws_config()  # Changed from AppConfig to AWSConfig
        self.dynamodb = boto3.resource('dynamodb', **config)
        self.users_table = self.dynamodb.Table(AWSConfig.USERS_TABLE)  # Changed from AppConfig to AWSConfig
        self.sessions_table = self.dynamodb.Table(AWSConfig.SESSIONS_TABLE)  # Changed from AppConfig to AWSConfig
        self.permissions_table = self.dynamodb.Table(AWSConfig.PERMISSIONS_TABLE)  # Changed from AppConfig to AWSConfig
        
        # Initialize dependencies with lazy imports if not provided
        if cache_manager is None:
            from ..utils.cache_manager import CacheManager
            cache_manager = CacheManager()
            
        if audit_logger is None:
            from ..utils.audit_logger import AuditLogger
            audit_logger = AuditLogger(self)
            
        self.cache_manager = cache_manager
        self.audit_logger = audit_logger

   async def create_user(self, user_data: Dict) -> Dict:
       try:
           # Generate UUID and hash password
           user_id = str(uuid.uuid4())
           password_hash = bcrypt.hashpw(
               user_data['password'].encode('utf-8'),
               bcrypt.gensalt()
           ).decode('utf-8')

           item = {
               'username': user_data['username'],
               'sk': '#USER',
               'user_id': user_id,
               'email': user_data['email'],
               'password_hash': password_hash,
               'role': user_data.get('role', 'user'),
               'access_level': user_data.get('access_level', 'read_only'),
               'created_at': datetime.now().isoformat(),
               'last_modified': datetime.now().isoformat(),
               'status': 'active'
           }

           await self.users_table.put_item(Item=item)
           await self.audit_logger.log_action(
               'system', 'create_user', 'users',
               {'username': user_data['username']}
           )

           # Remove sensitive data before returning
           item.pop('password_hash')
           return item

       except Exception as e:
           logger.error(f"Error creating user: {str(e)}")
           raise

   async def get_user(self, username: str) -> Optional[Dict]:
       try:
           logger.info(f"Getting user {username}")
           cache_key = f"user:{username}"
           
           # Try to get from cache first
           if hasattr(self, 'cache_manager') and self.cache_manager:
               try:
                   cached_user = await asyncio.to_thread(
                       lambda: self.cache_manager.get(cache_key)
                   )
                   if cached_user:
                       logger.info(f"User {username} found in cache")
                       return cached_user
               except Exception as cache_error:
                   logger.warning(f"Cache error for {username}: {str(cache_error)}")
           
           # Get from DynamoDB
           try:
               response = await asyncio.to_thread(
                   self.users_table.get_item,
                   Key={
                       'username': username,
                       'sk': '#USER'
                   }
               )
               
               user = response.get('Item')
               if user:
                   logger.info(f"User {username} found in DynamoDB")
                   
                   # Store in cache
                   if hasattr(self, 'cache_manager') and self.cache_manager:
                       try:
                           await asyncio.to_thread(
                               lambda: self.cache_manager.set(cache_key, user)
                           )
                       except Exception as cache_error:
                           logger.warning(f"Cache set error for {username}: {str(cache_error)}")
               else:
                   logger.warning(f"User {username} not found in DynamoDB")
                   
               return user
               
           except Exception as dynamo_error:
               logger.error(f"DynamoDB error getting user {username}: {str(dynamo_error)}")
               raise
               
       except Exception as e:
           logger.error(f"Error getting user {username}: {str(e)}")
           return None

   async def _async_dynamo_operation(self, operation, **kwargs):
       """Helper method to run DynamoDB operations asynchronously"""
       try:
           # Get the operation method
           if isinstance(operation, str):
               if hasattr(self.users_table, operation):
                   method = getattr(self.users_table, operation)
               else:
                   raise ValueError(f"Unknown DynamoDB operation: {operation}")
           else:
               method = operation
            
           # Run the operation in a thread
           result = await asyncio.to_thread(method, **kwargs)
           return result
       except Exception as e:
           logger.error(f"Error in async DynamoDB operation: {str(e)}")
           raise

   async def update_user(self, username: str, updates: Dict) -> Dict:
       """Update user in DynamoDB with optimized performance and improved reliability"""
       try:
           logger.info(f"Starting update for user {username}")
           
           # First, get the existing user to ensure it exists
           existing_user = await self.get_user(username)
           if not existing_user:
               logger.error(f"User {username} not found")
               raise ValueError(f"User {username} not found")
           
           # Prepare update expression and values
           update_expr = "SET "
           expr_values = {}
           expr_names = {}
           
           # Process each update field
           for key, value in updates.items():
               if key == 'username':
                   continue  # Skip primary key
                   
               if key == 'password':
                   # Hash password if provided
                   value = bcrypt.hashpw(
                       value.encode('utf-8'),
                       bcrypt.gensalt()
                   ).decode('utf-8')
                   key = 'password_hash'
               
               # Add to update expression
               update_expr += f"#{key} = :{key}, "
               expr_values[f":{key}"] = value
               expr_names[f"#{key}"] = key

           # Add last_modified timestamp
           update_expr += "#last_modified = :last_modified"
           expr_values[":last_modified"] = datetime.now().isoformat()
           expr_names["#last_modified"] = "last_modified"

           # Execute update with timeout protection
           try:
               # Create a future for the update operation
               update_future = asyncio.create_task(
                   asyncio.to_thread(
                       self.users_table.update_item,
                       Key={
                           'username': username,
                           'sk': '#USER'
                       },
                       UpdateExpression=update_expr,
                       ExpressionAttributeValues=expr_values,
                       ExpressionAttributeNames=expr_names,
                       ReturnValues="ALL_NEW"
                   )
               )
               
               # Wait for the update with a timeout
               response = await asyncio.wait_for(update_future, timeout=10.0)
               
               # Get updated user data
               updated_user = response.get('Attributes', {})
               
               if not updated_user:
                   logger.error(f"Update returned no data for user {username}")
                   raise ValueError(f"Update failed for user {username} - no data returned")
               
               logger.info(f"User {username} updated successfully")
               
               # Clear cache and log in background
               asyncio.create_task(self._post_update_tasks(username))
               
               return updated_user
               
           except asyncio.TimeoutError:
               logger.error(f"Update operation timed out for user {username}")
               raise TimeoutError(f"Update operation timed out for user {username}")
           except Exception as e:
               logger.error(f"DynamoDB update error for {username}: {str(e)}")
               raise

       except Exception as e:
           logger.error(f"Error updating user {username}: {str(e)}")
           raise

   async def _post_update_tasks(self, username):
       """Handle post-update tasks like cache clearing and audit logging"""
       try:
           # Clear cache
           if hasattr(self, 'cache_manager') and self.cache_manager:
               try:
                   await asyncio.to_thread(
                       lambda: self.cache_manager.delete(f"user:{username}")
                   )
                   logger.info(f"Cache cleared for user {username}")
               except Exception as cache_error:
                   logger.warning(f"Cache clear failed for {username}: {str(cache_error)}")
           
           # Log action
           if hasattr(self, 'audit_logger') and self.audit_logger:
               try:
                   await asyncio.to_thread(
                       lambda: self.audit_logger.log_action(
                           'system', 'update_user', 'users',
                           {'username': username}
                       )
                   )
                   logger.info(f"Audit log created for user {username} update")
               except Exception as audit_error:
                   logger.warning(f"Audit logging failed for {username}: {str(audit_error)}")
       
       except Exception as e:
           logger.error(f"Error in post-update tasks for {username}: {str(e)}")
           # We don't re-raise here to avoid affecting the main update operation

   async def delete_user(self, username: str) -> bool:
       """Delete a user completely from DynamoDB"""
       try:
           logger.info(f"Deleting user {username} from DynamoDB")
           
           # Delete the user record
           await asyncio.to_thread(
               self.users_table.delete_item,
               Key={
                   'username': username,
                   'sk': '#USER'
               }
           )
           
           # Delete user permissions
           try:
               # Query for permissions with this username
               response = await asyncio.to_thread(
                   self.permissions_table.query,
                   KeyConditionExpression='username = :username',
                   ExpressionAttributeValues={':username': username}
               )
               
               # Delete each permission
               for item in response.get('Items', []):
                   await asyncio.to_thread(
                       self.permissions_table.delete_item,
                       Key={
                           'username': username,
                           'folder_path': item.get('folder_path', '')
                       }
                   )
               
               logger.info(f"Deleted {len(response.get('Items', []))} permissions for user {username}")
           except Exception as perm_error:
               logger.warning(f"Error deleting permissions for {username}: {str(perm_error)}")
           
           # Clear cache
           if hasattr(self, 'cache_manager') and self.cache_manager:
               try:
                   await asyncio.to_thread(
                       lambda: self.cache_manager.delete(f"user:{username}")
                   )
                   logger.info(f"Cache cleared for user {username}")
               except Exception as cache_error:
                   logger.warning(f"Error clearing cache: {str(cache_error)}")
           
           # Log the deletion
           if hasattr(self, 'audit_logger') and self.audit_logger:
               try:
                   await asyncio.to_thread(
                       lambda: self.audit_logger.log_action(
                           'system', 'delete_user', 'users',
                           {'username': username}
                       )
                   )
                   logger.info(f"Audit log created for user {username} deletion")
               except Exception as audit_error:
                   logger.warning(f"Audit logging failed for {username}: {str(audit_error)}")
           
           logger.info(f"User {username} successfully deleted from DynamoDB")
           return True

       except Exception as e:
           logger.error(f"Error deleting user {username}: {str(e)}")
           raise

   async def list_users(self, active_only: bool = True) -> List[Dict]:
       try:
           if active_only:
               filter_expr = "#status = :status"
               expr_values = {':status': 'active'}
               expr_names = {'#status': 'status'}
           else:
               filter_expr = None
               expr_values = None
               expr_names = None

           response = await self.users_table.scan(
               FilterExpression=filter_expr if filter_expr else None,
               ExpressionAttributeValues=expr_values if expr_values else None,
               ExpressionAttributeNames=expr_names if expr_names else None
           )

           users = response.get('Items', [])
           for user in users:
               user.pop('password_hash', None)

           return users

       except Exception as e:
           logger.error(f"Error listing users: {str(e)}")
           raise

   async def verify_password(self, username: str, password: str) -> bool:
       try:
           user = await self.get_user(username)
           if not user:
               return False

           stored_hash = user.get('password_hash', '').encode('utf-8')
           return bcrypt.checkpw(password.encode('utf-8'), stored_hash)

       except Exception as e:
           logger.error(f"Error verifying password for {username}: {str(e)}")
           return False

   async def get_user_by_email(self, email: str) -> Optional[Dict]:
       try:
           response = await self.users_table.query(
               IndexName=AWSConfig.get_index_name(AWSConfig.USERS_TABLE, 'email_index'),  # Changed from AppConfig to AWSConfig
               KeyConditionExpression='email = :email',
               ExpressionAttributeValues={':email': email}
           )
           users = response.get('Items', [])
           return users[0] if users else None

       except Exception as e:
           logger.error(f"Error getting user by email {email}: {str(e)}")
           return None

   async def get_users_by_role(self, role: str) -> List[Dict]:
       try:
           response = await self.users_table.query(
               IndexName=AWSConfig.get_index_name(AWSConfig.USERS_TABLE, 'role_index'),  # Changed from AppConfig to AWSConfig
               KeyConditionExpression='role = :role',
               ExpressionAttributeValues={':role': role}
           )
           users = response.get('Items', [])
           for user in users:
               user.pop('password_hash', None)
           return users

       except Exception as e:
           logger.error(f"Error getting users by role {role}: {str(e)}")
           return []