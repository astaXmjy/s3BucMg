import boto3
import bcrypt
import jwt
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Dict, Optional, List
import asyncio

# Type checking imports
if TYPE_CHECKING:
    from ..utils.audit_logger import AuditLogger
    from ..utils.cache_manager import CacheManager
    from .permission_manager import PermissionManager

from ..aws.config import AWSConfig

logger = logging.getLogger(__name__)

class UserManager:
    def __init__(self, 
                 audit_logger: Optional['AuditLogger'] = None,
                 cache_manager: Optional['CacheManager'] = None,
                 permission_manager: Optional['PermissionManager'] = None):
        """
        Initialize UserManager with optional dependencies
        """
        self.dynamodb = boto3.resource('dynamodb', **AWSConfig.get_aws_config())
        self.users_table = self.dynamodb.Table(AWSConfig.USERS_TABLE)
        self.sessions_table = self.dynamodb.Table(AWSConfig.SESSIONS_TABLE)
        self.secret_key = os.getenv('JWT_SECRET_KEY')
        self.token_expiry = int(os.getenv('TOKEN_EXPIRY_HOURS', 24))

        # Initialize dependencies with lazy imports if not provided
        if permission_manager is None:
            from .permission_manager import PermissionManager
            permission_manager = PermissionManager()
            
        if cache_manager is None:
            from ..utils.cache_manager import CacheManager
            cache_manager = CacheManager()
            
        if audit_logger is None:
            from ..utils.audit_logger import AuditLogger
            audit_logger = AuditLogger()
            
        self.permission_manager = permission_manager
        self.cache_manager = cache_manager
        self.audit_logger = audit_logger

    async def authenticate_user(self, username: str, password: str) -> Dict:
        """Authenticate user with username and password"""
        try:
            user = await self._get_user(username)
            if not user:
                logger.warning(f"Authentication failed - user not found: {username}")
                await self.audit_logger.log_event(
                    'login_failed',
                    username,
                    details={'reason': 'user_not_found'}
                )
                return self._auth_failed('Invalid username or password')

            # Handle password verification
            if not self._verify_password(password, user['password_hash']):
                logger.warning(f"Authentication failed - invalid password: {username}")
                await self.audit_logger.log_event(
                    'login_failed',
                    username,
                    details={'reason': 'invalid_password'}
                )
                return self._auth_failed('Invalid username or password')

            # Check if user is active
            if user.get('status') != 'active':
                logger.warning(f"Authentication failed - inactive account: {username}")
                await self.audit_logger.log_event(
                    'login_failed',
                    username,
                    details={'reason': 'inactive_account'}
                )
                return self._auth_failed('Account is inactive')

            # Get permissions using loop.run_in_executor for the DynamoDB call
            loop = asyncio.get_event_loop()
            permissions = await self.permission_manager.get_permissions(
                user['uuid'],
                'user'
            )

            # Create user session
            session = await self._create_session(user, permissions)
            access_token = self._create_access_token(user, permissions, session['session_id'])
            refresh_token = self._create_refresh_token(user, session['session_id'])

            logger.info(f"Authentication successful: {username}")
            await self.audit_logger.log_event(
                'login_success',
                username,
                details={'session_id': session['session_id']}
            )

            # Clean up sensitive data before returning
            user_data = {
                'uuid': user['uuid'],
                'username': user['username'],
                'email': user['email'],
                'role': user['role'],
                'access_level': user['access_level'],
                'bucket_access': user.get('bucket_access', []),
                'folder_access': user.get('folder_access', []),
                'permissions': permissions,
                'access_token': access_token,
                'refresh_token': refresh_token,
                'session_id': session['session_id']
            }

            return {
                'success': True,
                'user': user_data
            }

        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            await self.audit_logger.log_event(
                'login_error',
                username,
                details={'error': str(e)}
            )
            return self._auth_failed('Authentication error occurred')

    async def validate_token(self, token: str) -> Dict:
        """
        Validate JWT token
        
        Args:
            token (str): JWT token to validate
            
        Returns:
            Dict containing validation result and user info if valid
        """
        try:
            # Decode and verify token
            payload = jwt.decode(token, self.secret_key, algorithms=['HS256'])
            
            # Get session info
            session_id = payload.get('session_id')
            if not session_id:
                return {'valid': False, 'error': 'Invalid token format'}

            # Check cache first
            cache_key = f"session:{session_id}"
            session = await self.cache_manager.get(cache_key)
            
            # If not in cache, check database
            if not session:
                session = await self._get_session(session_id)
                if session:
                    await self.cache_manager.set(cache_key, session)

            # Verify session is valid
            if not session or not session.get('active'):
                return {'valid': False, 'error': 'Invalid session'}

            # Get user info
            user = await self._get_user(payload['username'])
            if not user:
                return {'valid': False, 'error': 'User not found'}
                
            # Check if user is active
            if user.get('status') != 'active':
                return {'valid': False, 'error': 'Account is inactive'}

            # Get current permissions
            current_permissions = await self.permission_manager.get_permissions(
                user['uuid'], 
                'user'
            )

            # Return validation result with user info
            return {
                'valid': True,
                'user': {
                    'uuid': user['uuid'],
                    'username': user['username'],
                    'role': user['role'],
                    'access_level': user['access_level'],
                    'folder_access': user.get('folder_access', []),
                    'bucket_access': user.get('bucket_access', [])
                },
                'permissions': current_permissions,
                'session_id': session_id
            }

        except jwt.ExpiredSignatureError:
            return {'valid': False, 'error': 'Token expired'}
        except jwt.InvalidTokenError:
            return {'valid': False, 'error': 'Invalid token'}
        except Exception as e:
            logger.error(f"Token validation error: {str(e)}")
            return {'valid': False, 'error': 'Token validation failed'}

    async def create_user(self, user_data: Dict) -> Dict:
        """Create a new user"""
        try:
            username = user_data['username']
            
            # Check if username already exists
            existing_user = await self._get_user(username)
            if existing_user:
                logger.warning(f"User creation failed - username exists: {username}")
                return {'success': False, 'error': 'Username already exists'}

            # Hash password
            password_hash = bcrypt.hashpw(
                user_data['password'].encode('utf-8'),
                bcrypt.gensalt()
            ).decode('utf-8')

            # Prepare folder access
            folder_access = user_data.get('folder_access', [])
            
            # For new users, create their personal folder if needed
            if not folder_access and user_data.get('access_level') in ['push', 'both', 'full']:
                personal_folder = f"users/{username}/"
                folder_access.append(personal_folder)
                
                # Create folder in S3 (if S3 helper available)
                try:
                    from ..aws.s3_helper import S3Helper
                    s3_helper = S3Helper()
                    await s3_helper.create_folder(personal_folder, user_id=None)
                    logger.info(f"Created personal folder for {username}: {personal_folder}")
                except Exception as s3_error:
                    logger.warning(f"Could not create folder for {username}: {str(s3_error)}")

            # Create user item with username as primary key
            user_item = {
                'username': username,  # Primary key
                'sk': '#USER',  # Sort key
                'uuid': str(uuid.uuid4()),
                'email': user_data['email'],
                'password_hash': password_hash,
                'role': user_data.get('role', 'user'),
                'access_level': user_data.get('access_level', 'read_only'),
                'created_at': datetime.utcnow().isoformat(),
                'status': 'active',
                'bucket_access': user_data.get('bucket_access', [AWSConfig.S3_BUCKET_NAME]),
                'folder_access': folder_access
            }
            
            # Ensure username is present
            if not username:
                raise ValueError('Missing required key: username')

            # Convert to DynamoDB call
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.users_table.put_item(Item=user_item)
            )
            
            # Remove sensitive data before returning
            result_item = user_item.copy()
            result_item.pop('password_hash')
            result_item.pop('sk')
            
            # Log user creation
            await self.audit_logger.log_event(
                'user_created',
                username,
                details={
                    'email': user_data['email'],
                    'role': user_item['role'],
                    'access_level': user_item['access_level']
                }
            )

            return {'success': True, 'user': result_item}

        except Exception as e:
            logger.error(f"User creation error: {str(e)}")
            return {'success': False, 'error': str(e)}
        
    async def update_user(self, username: str, updates: Dict) -> Dict:
        """Update user information"""
        try:
            # Get current user
            user = await self._get_user(username)
            if not user:
                logger.warning(f"User update failed - user not found: {username}")
                return None

            # Build update expression and values
            update_expr = "SET "
            expr_values = {}
            expr_names = {}
            
            # Handle special fields
            for key, value in updates.items():
                if key == 'username':
                    # Cannot update username (primary key)
                    continue
                
                if key == 'password':
                    # Hash passwords
                    value = bcrypt.hashpw(
                        value.encode('utf-8'),
                        bcrypt.gensalt()
                    ).decode('utf-8')
                    key = 'password_hash'
                
                # Add to update expression
                attr_name = f"#{key}"
                attr_value = f":{key}"
                update_expr += f"{attr_name} = {attr_value}, "
                expr_values[attr_value] = value
                expr_names[attr_name] = key
            
            # Add last_modified timestamp
            update_expr += "#last_modified = :last_modified"
            expr_values[":last_modified"] = datetime.utcnow().isoformat()
            expr_names["#last_modified"] = "last_modified"

            # Execute update
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.users_table.update_item(
                    Key={'username': username, 'sk': '#USER'},
                    UpdateExpression=update_expr,
                    ExpressionAttributeValues=expr_values,
                    ExpressionAttributeNames=expr_names,
                    ReturnValues="ALL_NEW"
                )
            )

            # Get updated user
            updated_user = response.get('Attributes', {})
            
            # Clear cache
            await self.cache_manager.delete(f"user:{username}")
            
            # Log user update
            await self.audit_logger.log_event(
                'user_updated',
                username,
                details={'updates': {k: v for k, v in updates.items() if k != 'password'}}
            )
            
            # If folder_access was updated, create any new folders
            if 'folder_access' in updates:
                try:
                    from ..aws.s3_helper import S3Helper
                    s3_helper = S3Helper()
                    
                    # Get current folders in S3
                    all_folders, _ = await s3_helper.list_folder_contents()
                    
                    # Check each folder in the update
                    for folder in updates['folder_access']:
                        if folder not in all_folders:
                            try:
                                await s3_helper.create_folder(folder)
                                logger.info(f"Created folder for {username}: {folder}")
                            except Exception as folder_error:
                                logger.warning(f"Could not create folder: {str(folder_error)}")
                except Exception as s3_error:
                    logger.warning(f"Error checking folders: {str(s3_error)}")

            # Remove sensitive data
            if 'password_hash' in updated_user:
                updated_user.pop('password_hash')

            return updated_user

        except Exception as e:
            logger.error(f"User update error: {str(e)}")
            return None

    async def get_all_users(self) -> List[Dict]:
        """Retrieve all users from the database"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.users_table.scan(
                    FilterExpression="sk = :sk",
                    ExpressionAttributeValues={':sk': '#USER'}
                )
            )
            users = response.get('Items', [])

            # Remove sensitive data
            for user in users:
                user.pop('password_hash', None)
                user.pop('sk', None)

            return users

        except Exception as e:
            logger.error(f"Error getting all users: {str(e)}")
            return []

    async def _get_user(self, username: str) -> Optional[Dict]:
        """Get user by username"""
        cache_key = f"user:{username}"
        cached_user = await self.cache_manager.get(cache_key)
        if cached_user:
            return cached_user

        try:
            # Convert synchronous DynamoDB call to async using loop.run_in_executor
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.users_table.get_item(
                    Key={'username': username, 'sk': '#USER'}
                )
            )
            
            user = response.get('Item')
            if user:
                await self.cache_manager.set(cache_key, user)
            return user
        except Exception as e:
            logger.error(f"Error getting user {username}: {str(e)}")
            return None

    async def _get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """Get user by UUID"""
        try:
            # Query by UUID
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.users_table.scan(
                    FilterExpression="uuid = :uuid AND sk = :sk",
                    ExpressionAttributeValues={
                        ':uuid': user_id,
                        ':sk': '#USER'
                    }
                )
            )
            
            items = response.get('Items', [])
            return items[0] if items else None
        except Exception as e:
            logger.error(f"Error getting user by ID {user_id}: {str(e)}")
            return None

    async def _get_session(self, session_id: str) -> Optional[Dict]:
        """Get session by ID"""
        cache_key = f"session:{session_id}"
        cached_session = await self.cache_manager.get(cache_key)
        if cached_session:
            return cached_session

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.sessions_table.get_item(
                    Key={'session_id': session_id}
                )
            )
            session = response.get('Item')
            if session:
                await self.cache_manager.set(cache_key, session)
            return session
        except Exception as e:
            logger.error(f"Error getting session {session_id}: {str(e)}")
            return None

    async def _create_session(self, user: Dict, permissions: Dict) -> Dict:
        """Create a new user session"""
        session_id = str(uuid.uuid4())
        session = {
            'session_id': session_id,
            'username': user['username'],
            'user_id': user['uuid'],
            'created_at': datetime.utcnow().isoformat(),
            'last_activity': datetime.utcnow().isoformat(),
            'permissions': permissions,
            'active': True,
            'expiry_time': int((datetime.utcnow() + timedelta(days=7)).timestamp())
        }

        # Use run_in_executor for DynamoDB operation
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self.sessions_table.put_item(Item=session)
        )
        await self.cache_manager.set(f"session:{session_id}", session)
        return session

    def _create_access_token(self, user: Dict, permissions: Dict, session_id: str) -> str:
        """Create JWT access token"""
        payload = {
            'username': user['username'],
            'user_id': user['uuid'],
            'role': user['role'],
            'permissions': permissions,
            'session_id': session_id,
            'exp': int((datetime.utcnow() + timedelta(hours=self.token_expiry)).timestamp())
        }
        return jwt.encode(payload, self.secret_key, algorithm='HS256')

    def _create_refresh_token(self, user: Dict, session_id: str) -> str:
        """Create JWT refresh token"""
        payload = {
            'username': user['username'],
            'user_id': user['uuid'],
            'session_id': session_id,
            'exp': int((datetime.utcnow() + timedelta(days=7)).timestamp())
        }
        return jwt.encode(payload, self.secret_key, algorithm='HS256')

    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify password against hash"""
        return bcrypt.checkpw(
            password.encode('utf-8'),
            password_hash.encode('utf-8')
        )

    def _auth_failed(self, message: str) -> Dict:
        """Return authentication failed response"""
        return {
            'success': False,
            'message': message
        }

    async def refresh_token(self, refresh_token: str) -> Dict:
        """Generate new access token using refresh token"""
        try:
            payload = jwt.decode(refresh_token, self.secret_key, algorithms=['HS256'])
            username = payload.get('username')
            session_id = payload.get('session_id')

            user = await self._get_user(username)
            if not user:
                return {'success': False, 'error': 'User not found'}

            session = await self._get_session(session_id)
            if not session or not session.get('active'):
                return {'success': False, 'error': 'Invalid session'}

            # Update session last activity
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.sessions_table.update_item(
                    Key={'session_id': session_id},
                    UpdateExpression="SET last_activity = :time",
                    ExpressionAttributeValues={':time': datetime.utcnow().isoformat()}
                )
            )

            # Get current permissions
            permissions = await self.permission_manager.get_permissions(user['uuid'], 'user')
            
            # Create new access token
            access_token = self._create_access_token(user, permissions, session_id)

            return {
                'success': True,
                'access_token': access_token
            }

        except jwt.ExpiredSignatureError:
            return {'success': False, 'error': 'Refresh token expired'}
        except Exception as e:
            logger.error(f"Token refresh error: {str(e)}")
            return {'success': False, 'error': 'Token refresh failed'}

    async def delete_user(self, username: str) -> bool:
        """Soft delete a user (set status to inactive)"""
        try:
            # Update user status
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.users_table.update_item(
                    Key={'username': username, 'sk': '#USER'},
                    UpdateExpression="SET #status = :status, #last_modified = :last_modified",
                    ExpressionAttributeNames={
                        '#status': 'status',
                        '#last_modified': 'last_modified'
                    },
                    ExpressionAttributeValues={
                        ':status': 'inactive',
                        ':last_modified': datetime.utcnow().isoformat()
                    }
                )
            )

            # Clear cache
            await self.cache_manager.delete(f"user:{username}")
            
            # Log user deletion
            await self.audit_logger.log_event(
                'user_deleted',
                username,
                details={'soft_delete': True}
            )

            return True

        except Exception as e:
            logger.error(f"Error deleting user {username}: {str(e)}")
            return False

    async def get_user_folder_access(self, username: str) -> List[str]:
        """Get folders a user has access to"""
        try:
            user = await self._get_user(username)
            if not user:
                return []
                
            # Admin users have access to all folders
            if user.get('role') == 'admin':
                return ['*']  # Special marker for all access
                
            # Get folder access list
            folder_access = user.get('folder_access', [])
            
            # Add default folder if empty
            if not folder_access and user.get('access_level') in ['push', 'both', 'full']:
                personal_folder = f"users/{username}/"
                folder_access.append(personal_folder)
                
            return folder_access
            
        except Exception as e:
            logger.error(f"Error getting folder access for {username}: {str(e)}")
            return []

    async def update_user_role(self, username: str, new_role: str) -> Dict:
        """Update the role of an existing user"""
        try:
            # Fetch the user from DynamoDB
            user = await self._get_user(username)
            if not user:
                return {'success': False, 'error': 'User not found'}

            # Update the role
            response = self.users_table.update_item(
                Key={'username': username},
                UpdateExpression="set role = :r",
                ExpressionAttributeValues={":r": new_role},
                ReturnValues="UPDATED_NEW"
            )

            # Log the role update
            await self.audit_logger.log_event(
                'update_user_role',
                username,
                details={'new_role': new_role}
            )

            return {'success': True, 'updated_attributes': response.get('Attributes', {})}

        except Exception as e:
            logger.error(f"Error updating user role: {str(e)}")
            return {'success': False, 'error': str(e)}

    async def reset_user_password(self, username: str, new_password: str) -> Dict:
        """Reset the password for an existing user"""
        try:
            # Fetch the user from DynamoDB
            user = await self._get_user(username)
            if not user:
                return {'success': False, 'error': 'User not found'}

            # Hash the new password
            password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

            # Update the password hash
            response = self.users_table.update_item(
                Key={'username': username},
                UpdateExpression="set password_hash = :p",
                ExpressionAttributeValues={":p": password_hash},
                ReturnValues="UPDATED_NEW"
            )

            # Log the password reset
            await self.audit_logger.log_event(
                'reset_user_password',
                username
            )

            return {'success': True, 'updated_attributes': response.get('Attributes', {})}

        except Exception as e:
            logger.error(f"Error resetting user password: {str(e)}")
            return {'success': False, 'error': str(e)}

    async def update_user_status(self, username: str, new_status: str) -> Dict:
        """Update the status of an existing user"""
        try:
            # Fetch the user from DynamoDB
            user = await self._get_user(username)
            if not user:
                return {'success': False, 'error': 'User not found'}

            # Validate status
            if new_status not in ['active', 'inactive']:
                return {'success': False, 'error': 'Invalid status value. Must be active or inactive'}

            # Update the status - using ExpressionAttributeNames to handle reserved keyword 'status'
            response = await asyncio.to_thread(
                self.users_table.update_item,
                Key={'username': username, 'sk': '#USER'},
                UpdateExpression="SET #status = :status, #lastmod = :lastmod",
                ExpressionAttributeNames={
                    '#status': 'status',
                    '#lastmod': 'last_modified'
                },
                ExpressionAttributeValues={
                    ':status': new_status,
                    ':lastmod': datetime.now().isoformat()
                },
                ReturnValues="UPDATED_NEW"
            )

            # Log the status update
            await self.audit_logger.log_event(
                'update_user_status',
                username,
                details={'new_status': new_status}
            )

            return {'success': True, 'updated_attributes': response.get('Attributes', {})}

        except Exception as e:
            logger.error(f"Error updating user status: {str(e)}")
            return {'success': False, 'error': str(e)}
            
    async def manage_user_permissions(self, username: str, permissions: List[str]) -> Dict:
        """Manage permissions for an existing user"""
        try:
            # Fetch the user from DynamoDB
            user = await self._get_user(username)
            if not user:
                return {'success': False, 'error': 'User not found'}

            # Update the permissions
            response = self.users_table.update_item(
                Key={'username': username},
                UpdateExpression="set permissions = :p",
                ExpressionAttributeValues={":p": permissions},
                ReturnValues="UPDATED_NEW"
            )

            # Log the permission update
            await self.audit_logger.log_event(
                'manage_user_permissions',
                username,
                details={'permissions': permissions}
            )

            return {'success': True, 'updated_attributes': response.get('Attributes', {})}

        except Exception as e:
            logger.error(f"Error managing user permissions: {str(e)}")
            return {'success': False, 'error': str(e)}