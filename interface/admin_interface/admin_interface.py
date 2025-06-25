import asyncio
from datetime import datetime
import json
import logging
import traceback
from .upload_progress_dialog import EnhancedUploadDialog
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.logger import Logger
from kivy.properties import StringProperty, BooleanProperty
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView

from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonText
from kivymd.uix.card import MDCard
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.list import (
    MDList,
    MDListItem,
    MDListItemHeadlineText,
    MDListItemLeadingIcon,
    MDListItemSupportingText,
)
from kivymd.uix.screen import MDScreen
from kivymd.uix.snackbar import MDSnackbar, MDSnackbarText
from kivymd.uix.textfield import MDTextField, MDTextFieldHintText

# Import core components
from core.auth.user_manager import UserManager
from core.auth.permission_manager import PermissionManager
from core.aws.dynamo_manager import DynamoManager
from core.aws.s3_helper import S3Helper
from core.utils.audit_logger import AuditLogger
from core.utils.cache_manager import CacheManager
from core.utils.database_manager import DatabaseManager
from .folder_selector import FolderSelector


from typing import Dict,List

logger = logging.getLogger(__name__)

class NavItem(MDCard):
    icon = StringProperty("")
    text = StringProperty("")
    selected = BooleanProperty(False)


class CustomTextField(MDTextField):
    """Custom TextField with built-in hint text"""

    def __init__(self, hint_text="", **kwargs):
        super().__init__(**kwargs)
        self.hint_text = hint_text
        self.mode = "outlined"

class AdminDashboard(MDScreen):
    """Admin dashboard screen with user and folder management capabilities"""
    current_tab = StringProperty("dashboard")
    current_user_name = StringProperty("")  # Add this line

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "admin_interface"
        self.dialog = None
        # Initialize lists properly - changed user_list to users_list
        self.users_list = []
        self.folder_list = []
        self.current_tab = "dashboard"
        self.tab_names = ["dashboard", "users", "storage", "logs"]
        self.bucket_stats = {}
        self.user_manager = None
        self.s3_helper = None
        self.permission_manager = None
        self.db_manager = None
        self.audit_logger = None

        # Initialize username
        app = MDApp.get_running_app()
        if hasattr(app, 'current_user') and app.current_user:
            self.current_user_name = f"Hello, {app.current_user.get('username', '')}"
        else:
            self.current_user_name = "Guest"

        # Schedule manager initialization
        Clock.schedule_once(self._initialize_managers, 0)
        # Schedule initialization after the screen is built
        Clock.schedule_once(self.initialize_tabs, 0.5)

        # Make sure Dashboard tab is visible by default
        Clock.schedule_once(self._show_dashboard_tab, 1)

    def _show_dashboard_tab(self, dt):
        """Force dashboard tab to be visible on startup"""
        self.show_tab("dashboard")
        # Load mock data initially in case real data takes time
        self._load_mock_data()

    def initialize_tabs(self, dt):
        """Make the dashboard tab visible by default"""
        print(f"All available IDs: {list(self.ids.keys())}")

        # Show dashboard tab
        if hasattr(self.ids, "dashboard_tab"):
            self.ids.dashboard_tab.opacity = 1
            self.ids.dashboard_tab.disabled = False
            print("Dashboard tab initialized and made visible")
        else:
            print("Dashboard tab not found in IDs")

        # Load initial data
        if hasattr(self, "_refresh_tab_data"):
            self._refresh_tab_data("dashboard")

    def _initialize_managers(self, dt):
        """Initialize data managers with focus on DynamoDB for user data"""
        app = MDApp.get_running_app()

        try:
            Logger.info("Initializing managers with DynamoDB integration")

            # Initialize cache manager
            self.cache_manager = CacheManager()
            Logger.info("Cache manager initialized")

            # Initialize database manager for audit logger
            self.db_manager = DatabaseManager()
            Logger.info("Database manager initialized")
            
            # Initialize managers in the correct order to avoid circular dependencies
            try:
                # Step 1: Create DynamoManager without AuditLogger
                self.dynamo_manager = DynamoManager(cache_manager=self.cache_manager)
                Logger.info("DynamoDB manager initialized")
                
                # Step 2: Create AuditLogger with DynamoManager
                self.audit_logger = AuditLogger(dynamo_manager=self.dynamo_manager, db_manager=self.db_manager)
                Logger.info("Audit logger initialized")
                
                # Step 3: Create PermissionManager
                self.permission_manager = PermissionManager()
                Logger.info("Permission manager initialized")
                
                # Step 4: Create UserManager with all dependencies
                self.user_manager = UserManager(
                    audit_logger=self.audit_logger,
                    cache_manager=self.cache_manager,
                    permission_manager=self.permission_manager
                )
                Logger.info("User manager initialized")
                
                # Step 5: Create S3Helper with correct parameters
                self.s3_helper = S3Helper(
                    db_manager=self.db_manager,
                    audit_logger=self.audit_logger,
                    permission_manager=self.permission_manager
                )
                Logger.info("S3 helper initialized")
                
                # Verify DynamoDB connection
                self._verify_dynamo_connection()
                
                # Initialize data lists
                self.users_list = []
                self.folder_list = []
                self.activity_logs = []
                
                # Load data - use a proper event loop
                self._setup_and_load_data()
                
                Logger.info("All managers initialized successfully with DynamoDB integration")
                return
                
            except Exception as aws_error:
                Logger.error(f"AWS initialization error: {str(aws_error)}")
                Logger.error(traceback.format_exc())
                raise aws_error
                
        except Exception as e:
            Logger.error(f"Failed to initialize managers: {str(e)}")
            Logger.error(traceback.format_exc())
            
            # Use mock data if initialization fails
            self.user_manager = None
            self.permission_manager = None
            self.s3_helper = None
            self.dynamo_manager = None
            
            # Initialize data lists
            self.users_list = []
            self.folder_list = []
            self.activity_logs = []
            
            # Load mock data
            self._load_mock_data()
            Logger.info("Using mock data due to initialization failure")
            
    def _verify_dynamo_connection(self):
        """Verify DynamoDB connection and tables"""
        try:
            if self.dynamo_manager:
                # Check if we can access the users table
                Logger.info("Verifying DynamoDB connection and tables")
                
                # Get table names
                users_table = self.dynamo_manager.users_table.table_name
                permissions_table = self.dynamo_manager.permissions_table.table_name
                sessions_table = self.dynamo_manager.sessions_table.table_name
                
                Logger.info(f"DynamoDB tables verified: Users: {users_table}, Permissions: {permissions_table}, Sessions: {sessions_table}")
                return True
        except Exception as e:
            Logger.error(f"DynamoDB verification failed: {str(e)}")
            Logger.error(traceback.format_exc())
            return False

    def _setup_and_load_data(self):
        """Set up event loop and load data properly"""
        try:
            # Get or create event loop
            app = MDApp.get_running_app()
            if not hasattr(app, 'loop'):
                try:
                    app.loop = asyncio.get_event_loop()
                except RuntimeError:
                    app.loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(app.loop)
            
            # Run the load_all_data coroutine in the event loop
            asyncio.run_coroutine_threadsafe(self._load_all_data(), app.loop)
            Logger.info("Data loading started in background")
        except Exception as e:
            Logger.error(f"Error setting up data loading: {str(e)}")
            Logger.error(traceback.format_exc())
            # Fall back to mock data
            self._load_mock_data()

    def on_enter(self):
        """Called when the screen is entered (shown)"""
        Logger.info("Entered Admin Dashboard")
        
        # Update username display with greeting
        app = MDApp.get_running_app()
        if hasattr(app, 'current_user') and app.current_user:
            self.current_user_name = f"Hello, {app.current_user.get('username', '')}"
        else:
            self.current_user_name = "Guest"
        
        # Refresh data when entering the screen
        self.refresh_data()
        
        # Ensure dashboard stats are updated
        Clock.schedule_once(lambda dt: self._update_dashboard_stats(), 0.5)

    def toggle_nav_drawer(self):
        """Toggle navigation drawer"""
        if hasattr(self.ids, "nav_drawer"):
            self.ids.nav_drawer.set_state("toggle")
        else:
            print("Navigation drawer not found in IDs")
            print(f"Available IDs: {list(self.ids.keys())}")

    def show_create_folder_dialog(self, *args):
        """Show dialog for creating a new folder"""
        Logger.info("Showing create folder dialog")
        
        # Dismiss any existing dialog
        if hasattr(self, 'folder_popup') and self.folder_popup:
            self.folder_popup.dismiss()
            self.folder_popup = None
        
        # Create a better looking layout with proper styling
        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(16),
            padding=[dp(24), dp(16), dp(24), dp(16)],
            md_bg_color=[1, 1, 1, 1],  # White background
            size_hint_y=None,
            height=dp(280)
        )
        
        # Add title with better styling
        title = MDLabel(
            text="Create New Folder",
            font_size="22sp",
            bold=True,
            halign="center",
            size_hint_y=None,
            height=dp(50)
        )
        content.add_widget(title)
        
        # Add description
        description = MDLabel(
            text="Enter a name for the folder you want to create in S3.",
            theme_text_color="Secondary",
            font_size="14sp",
            halign="center",
            size_hint_y=None,
            height=dp(40)
        )
        content.add_widget(description)
        
        # Add folder name input with better styling - without helper_text
        self.folder_name_input = MDTextField(
            hint_text="Folder Name",
            mode="outlined",
            size_hint_y=None,
            height=dp(48)
        )
        content.add_widget(self.folder_name_input)
        
        # Add example text as a separate label instead of helper_text
        example = MDLabel(
            text="Example: documents, projects/web",
            theme_text_color="Secondary",
            font_size="12sp",
            halign="left",
            size_hint_y=None,
            height=dp(30)
        )
        content.add_widget(example)
        
        # Add spacer
        content.add_widget(MDBoxLayout(size_hint_y=None, height=dp(10)))
        
        # Add buttons with better styling
        buttons = MDBoxLayout(
            orientation='horizontal',
            spacing=dp(16),
            size_hint_y=None,
            height=dp(50)
        )
        
        # Cancel button
        cancel_button = MDButton(
            style="text",
            on_release=self._on_cancel_folder
        )
        cancel_button.add_widget(MDButtonText(text="CANCEL"))
        buttons.add_widget(cancel_button)
        
        # Create button with better styling
        create_button = MDButton(
            style="filled",
            md_bg_color=[0.2, 0.7, 0.3, 1.0],  # Green color
            on_release=self._on_create_folder_confirmed
        )
        create_button.add_widget(MDButtonText(text="CREATE FOLDER"))
        buttons.add_widget(create_button)
        
        content.add_widget(buttons)
        
        # Create popup with better styling
        self.folder_popup = Popup(
            title="",
            content=content,
            size_hint=(None, None),
            size=(dp(400), dp(300)),
            auto_dismiss=False,
            background_color=[0.95, 0.95, 0.95, 1.0]  # Light gray background
        )
        
        # Show popup
        self.folder_popup.open()
        Logger.info("Create folder dialog opened")
    
    def _on_cancel_folder(self, instance):
        """Handle cancel button press in folder dialog"""
        Logger.info("Folder creation canceled by user")
        if hasattr(self, 'folder_popup') and self.folder_popup:
            self.folder_popup.dismiss()
            self.folder_popup = None
    
    def _on_create_folder_confirmed(self, instance):
        """Handle create button press in folder dialog with confirmation"""
        if not hasattr(self, 'folder_name_input') or not self.folder_name_input:
            Logger.error("Folder name input not found")
            self.show_snackbar("Error: Could not get folder name")
            return
            
        folder_name = self.folder_name_input.text
        Logger.info(f"Create folder button pressed for: {folder_name}")
        
        if not folder_name or not folder_name.strip():
            self.show_snackbar("Please enter a folder name")
            return
            
        # Close the dialog first
        if hasattr(self, 'folder_popup') and self.folder_popup:
            self.folder_popup.dismiss()
            self.folder_popup = None
            
        # Show a loading snackbar
        self.show_snackbar(f"Creating folder '{folder_name}'...")
        
        # Schedule the actual folder creation to happen after the dialog is closed
        Clock.schedule_once(lambda dt: self._handle_create_folder(folder_name), 0.1)
        
    def _handle_create_folder(self, folder_name):
        """Handle folder creation"""
        Logger.info(f"Handling folder creation for: {folder_name}")
        
        if not folder_name:
            self.show_snackbar("Please enter a folder name")
            Logger.warning("Folder creation failed: Empty folder name")
            return

        # Clean folder name
        folder_name = folder_name.strip().replace('\\', '/').strip('/')
        if not folder_name:
            self.show_snackbar("Invalid folder name")
            Logger.warning("Folder creation failed: Invalid folder name after cleaning")
            return

        # Add trailing slash for S3
        folder_name = f"{folder_name}/"
        Logger.info(f"Cleaned folder name: {folder_name}")

        # Get current user ID
        app = MDApp.get_running_app()
        user_id = getattr(app, 'current_user', {}).get('username', None)
        Logger.info(f"Creating folder for user: {user_id}")

        # Create directly with boto3 for reliability
        self._create_folder_directly(folder_name, user_id)
            
    def _create_folder_directly(self, folder_name, user_id=None):
        """Create folder directly using boto3"""
        try:
            Logger.info(f"Creating folder directly with boto3: {folder_name}")
            
            # Import boto3 here to avoid dependency issues
            import boto3
            from core.aws.config import AWSConfig
            
            # Get AWS config
            aws_config = AWSConfig.get_aws_config()
            
            # Use the specified bucket name directly
            bucket_name = "test-fm-user-bucket"
            
            Logger.info(f"Using S3 bucket: {bucket_name}")
            
            # Create S3 client with proper credentials
            s3_client = boto3.client('s3', **aws_config)
            
            # Ensure folder name ends with slash
            if not folder_name.endswith('/'):
                folder_name = f"{folder_name}/"
                
            Logger.info(f"Creating empty object with key: {folder_name} in bucket: {bucket_name}")
            
            # Create folder (empty object with trailing slash)
            response = s3_client.put_object(
                Bucket=bucket_name,
                Key=folder_name,
                Body=b''
            )
            
            # Verify the folder was created
            try:
                # Check if the object exists
                s3_client.head_object(
                    Bucket=bucket_name,
                    Key=folder_name
                )
                folder_created = True
                Logger.info(f"Verified folder exists: {folder_name}")
            except Exception as verify_error:
                folder_created = False
                Logger.error(f"Failed to verify folder creation: {str(verify_error)}")
            
            if folder_created:
                Logger.info(f"Successfully created folder directly: {folder_name}")
                
                # Add to folder list
                if folder_name not in self.folder_list:
                    self.folder_list.append(folder_name)
                
                # Update UI
                self._update_folders_list()
                
                # Show success message
                self.show_snackbar(f"Folder '{folder_name.rstrip('/')}' created successfully")
                
                # Refresh folder list
                app = MDApp.get_running_app()
                if hasattr(app, 'loop'):
                    asyncio.run_coroutine_threadsafe(
                        self._load_folders(),
                        app.loop
                    )
                return True
            else:
                self.show_snackbar(f"Failed to create folder: {folder_name}")
                return False
            
        except Exception as e:
            Logger.error(f"Error creating folder directly: {str(e)}")
            Logger.error(traceback.format_exc())
            self.show_snackbar(f"Error creating folder: {str(e)}")
            
            # Try to reload folders list anyway in case the folder was created
            app = MDApp.get_running_app()
            if hasattr(app, 'loop'):
                asyncio.run_coroutine_threadsafe(
                    self._load_folders(),
                    app.loop
                )
            return False
            
    async def _create_user_task(self, user_data):
        """Handle user creation asynchronously"""
        try:
            if not self.user_manager:
                Logger.error("UserManager not available")
                return False

            # Create user using UserManager
            result = await self._async_create_user(user_data)
            
            if result.get('success'):
                # Refresh users list after successful creation
                await self._load_users()
                return True
            else:
                Logger.error(f"User creation failed: {result.get('error')}")
                return False
    
        except Exception as e:
            Logger.error(f"Error in _create_user_task: {str(e)}")
            Logger.error(traceback.format_exc())
            return False
        
    async def _update_user_directly_in_dynamo(self, username: str, updates: Dict) -> Dict:
        """Update user directly in DynamoDB with fix for serialization issue"""
        try:
            Logger.info(f"DIRECT DYNAMO UPDATE: Updating user {username} with updates: {updates}")
            
            # Create a new boto3 client each time to avoid serialization issues
            import boto3
            from core.aws.config import AWSConfig
            
            # Get configuration values directly
            aws_access_key = AWSConfig.AWS_ACCESS_KEY
            aws_secret_key = AWSConfig.AWS_SECRET_KEY
            aws_region = AWSConfig.AWS_REGION
            
            # Create new clients each time instead of reusing from other threads
            dynamodb = boto3.resource(
                'dynamodb',
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                region_name=aws_region
            )
            
            # Get the users table - use exact table name from config
            users_table_name = "test-fm-user-db-table-users"
            users_table = dynamodb.Table(users_table_name)
            
            Logger.info(f"Using DynamoDB table: {users_table_name}")
            
            # Build update expression and values
            try:
                # Convert folder_access to a simple list before passing to DynamoDB
                if 'folder_access' in updates:
                    if isinstance(updates['folder_access'], list):
                        # Make a simple copy of the list to avoid any serialization issues
                        updates['folder_access'] = [str(folder) for folder in updates['folder_access']]
                    elif isinstance(updates['folder_access'], str):
                        updates['folder_access'] = [f.strip() for f in updates['folder_access'].split(',') if f.strip()]
                
                # Create update expression components
                update_expr_parts = []
                expr_values = {}
                expr_names = {}
                
                # Process each update field
                for key, value in updates.items():
                    if key == 'username':
                        continue  # Skip primary key
                    
                    # Add to update expression
                    attr_name = f"#{key}"
                    attr_value = f":{key}"
                    update_expr_parts.append(f"{attr_name} = {attr_value}")
                    expr_values[attr_value] = value
                    expr_names[attr_name] = key
                
                # Add last_modified timestamp if not already included
                if 'last_modified' not in updates:
                    attr_name = "#last_modified"
                    attr_value = ":last_modified"
                    update_expr_parts.append(f"{attr_name} = {attr_value}")
                    expr_values[attr_value] = datetime.utcnow().isoformat()
                    expr_names[attr_name] = "last_modified"
                
                # Combine update expression parts
                update_expr = "SET " + ", ".join(update_expr_parts)
                
                Logger.info(f"Update expression: {update_expr}")
                Logger.info(f"Expression values: {expr_values}")
                
                # Execute update - using synchronous call to avoid serialization issues
                # This is the key change - don't use asyncio.to_thread which can cause serialization problems
                import time
                Logger.info(f"Executing DynamoDB UpdateItem for user: {username}")
                
                # Manual wait approach instead of await
                start_time = time.time()
                
                # Perform direct update without asyncio
                response = users_table.update_item(
                    Key={
                        'username': username,
                        'sk': '#USER'
                    },
                    UpdateExpression=update_expr,
                    ExpressionAttributeValues=expr_values,
                    ExpressionAttributeNames=expr_names,
                    ReturnValues="ALL_NEW"
                )
                
                end_time = time.time()
                Logger.info(f"DynamoDB update completed in {end_time - start_time:.2f} seconds")
                
                # Process response
                if response and 'Attributes' in response:
                    updated_user = response['Attributes']
                    Logger.info(f"User {username} updated successfully in DynamoDB")
                    
                    # Remove sensitive data
                    if 'password_hash' in updated_user:
                        updated_user.pop('password_hash')
                    
                    # Update local cache
                    for i, user in enumerate(self.users_list):
                        if user.get('username') == username:
                            # Update the user in the local list
                            for key, value in updates.items():
                                self.users_list[i][key] = value
                            Logger.info(f"Updated user {username} in local cache")
                            break
                    
                    return {
                        'success': True,
                        'user': updated_user,
                        'username': username,
                        'message': f"User {username} updated successfully",
                        'updated_attributes': updates
                    }
                else:
                    error_msg = "Update operation did not return updated attributes"
                    Logger.error(error_msg)
                    return {'success': False, 'error': error_msg}

            except Exception as e:
                error_msg = f"Error during UpdateItem: {str(e)}"
                Logger.error(error_msg)
                Logger.exception("UpdateItem error")
                return {'success': False, 'error': error_msg}

        except Exception as e:
            error_msg = f"Error in direct DynamoDB update: {str(e)}"
            Logger.error(error_msg)
            Logger.exception("Direct DynamoDB update error")
            return {'success': False, 'error': error_msg}

    # Also modify the handler to use direct function calls

    # Add a direct update method that doesn't use async/await
    def _direct_dynamo_update(self, username, updates):
        """Direct synchronous DynamoDB update avoiding PutItem completely"""
        try:
            Logger.info(f"DIRECT DYNAMO UPDATE: Updating user {username} with updates: {updates}")
            
            # Create a new boto3 client each time
            import boto3
            from core.aws.config import AWSConfig

            # Get configuration values directly
            aws_access_key = AWSConfig.AWS_ACCESS_KEY
            aws_secret_key = AWSConfig.AWS_SECRET_KEY
            aws_region = AWSConfig.AWS_REGION
            
            # Create new resource
            dynamodb = boto3.resource(
                'dynamodb',
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                region_name=aws_region
            )
            
            # Get the users table
            users_table_name = "test-fm-user-db-table-users" 
            users_table = dynamodb.Table(users_table_name)
            
            # Convert folder_access to a simple list
            if 'folder_access' in updates and isinstance(updates['folder_access'], list):
                updates['folder_access'] = [str(folder) for folder in updates['folder_access']]
            
            # Create update expression components
            update_expr_parts = []
            expr_values = {}
            expr_names = {}
            
            # Process each update field
            for key, value in updates.items():
                if key == 'username':
                    continue  # Skip primary key
                
                # Add to update expression
                attr_name = f"#{key}"
                attr_value = f":{key}"
                update_expr_parts.append(f"{attr_name} = {attr_value}")
                expr_values[attr_value] = value
                expr_names[attr_name] = key
            
            # Add last_modified timestamp if not already included
            if 'last_modified' not in updates:
                attr_name = "#last_modified"
                attr_value = ":last_modified"
                update_expr_parts.append(f"{attr_name} = {attr_value}")
                expr_values[attr_value] = datetime.utcnow().isoformat()
                expr_names[attr_name] = "last_modified"
            
            # Combine update expression parts
            update_expr = "SET " + ", ".join(update_expr_parts)
            
            # Log the operation
            Logger.info(f"Update operation: Table={users_table_name}, Key={{username={username}, sk=#USER}}")
            Logger.info(f"UpdateExpression: {update_expr}")
            
            # Execute update - IMPORTANT: Using only update_item, never put_item
            response = users_table.update_item(
                Key={
                    'username': username,
                    'sk': '#USER'
                },
                UpdateExpression=update_expr,
                ExpressionAttributeValues=expr_values,
                ExpressionAttributeNames=expr_names,
                ReturnValues="ALL_NEW"
            )
            
            # Process response
            if response and 'Attributes' in response:
                updated_user = response['Attributes']
                Logger.info(f"User {username} updated successfully in DynamoDB")
                
                # Remove sensitive data
                if 'password_hash' in updated_user:
                    updated_user.pop('password_hash')
                
                return {
                    'success': True,
                    'user': updated_user,
                    'username': username,
                    'message': f"User {username} updated successfully",
                    'updated_attributes': updates
                }
            else:
                return {'success': False, 'error': "Update operation did not return updated attributes"}
            
        except Exception as e:
            Logger.error(f"Error in direct DynamoDB update: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    # Enhanced method to handle update results with immediate UI refresh
    def _handle_update_result(self, result, username, selected_folders):
        """Handle the result of a DynamoDB update operation with immediate UI refresh"""
        try:
            if result and result.get('success'):
                # Show success message
                self.show_snackbar(f"Folder access updated successfully")
                
                # Update the local user list immediately
                for i, user in enumerate(self.users_list):
                    if user.get('username') == username:
                        # Update directly in the list to ensure UI reflects changes
                        self.users_list[i]['folder_access'] = selected_folders
                        Logger.info(f"Updated local user list for {username}")
                        break
                
                # Force UI updates
                self._update_users_list()
                
                # If we're in the users tab, make that update visible
                if self.current_tab == "users":
                    # Force redraw of users list
                    Clock.schedule_once(lambda dt: self._update_users_list(), 0.1)
                    
                    # If viewing user details, update them too
                    if hasattr(self, 'dialog') and self.dialog:
                        # Try to update dialog content if it's showing user details
                        try:
                            title_widget = None
                            for child in self.dialog.content.children:
                                if isinstance(child, MDLabel) and username in child.text:
                                    title_widget = child
                                    break
                                    
                            if title_widget:
                                # This is likely a user details dialog, update it
                                Clock.schedule_once(lambda dt: self.dialog.dismiss(), 0.1)
                                Clock.schedule_once(lambda dt: self._show_user_details(self.users_list[i]), 0.3)
                        except:
                            pass  # Ignore dialog update errors
                
                # Schedule a full data refresh
                Clock.schedule_once(lambda dt: self.refresh_data(), 0.5)
                
            else:
                # Show error message
                error = result.get('error', 'Unknown error')
                self.show_snackbar(f"Error updating folder access: {error}")
        except Exception as e:
            Logger.error(f"Error handling update result: {str(e)}")
            self.show_snackbar(f"Error: {str(e)}")
    
    # Also add a debugging method to check for any remaining PutItem calls
    def debug_check_putitem_calls(self):
        """Check for any PutItem calls in the codebase - for debugging only"""
        import inspect
        import re
        
        putitem_pattern = re.compile(r'put_item|PutItem', re.IGNORECASE)
        found_calls = []
        
        # Check all methods in this class
        for name, method in inspect.getmembers(self, inspect.ismethod):
            if name.startswith('_'):  # Only check private methods
                source = inspect.getsource(method)
                if putitem_pattern.search(source):
                    found_calls.append(name)
        
        if found_calls:
            Logger.warning(f"Found potential PutItem calls in these methods: {found_calls}")
        else:
            Logger.info("No PutItem calls found in class methods")

        return found_calls

    def show_tab(self, tab_name):
        """Switch between tabs"""
        print(f"Show_tab called with: {tab_name}")

        # Normalize tab name
        if isinstance(tab_name, str):
            tab_to_show = tab_name.lower()
        else:
            # Get text if it's an object
            tab_to_show = getattr(tab_name, 'text', '').lower()
            if not tab_to_show:
                tab_to_show = "dashboard"  # Default

        # Validate tab name
        if tab_to_show not in self.tab_names:
            print(f"Warning: Tab '{tab_to_show}' not in available tabs: {self.tab_names}")
            tab_to_show = "dashboard"  # Fallback to default

        # Store current tab
        self.current_tab = tab_to_show
        print(f"Switching to tab: {tab_to_show}")

        # Use ScreenManager to switch tabs
        if hasattr(self.ids, 'tab_manager'):
            try:
                self.ids.tab_manager.current = tab_to_show
            except Exception as e:
                print(f"Error switching tabs in ScreenManager: {e}")

        # Also update tab visibility directly
        for name in self.tab_names:
            screen_id = f"{name}_screen"
            if screen_id in self.ids:
                self.ids[screen_id].opacity = 1 if name == tab_to_show else 0
                self.ids[screen_id].disabled = name != tab_to_show

        # Refresh tab data
        self._refresh_tab_data(tab_to_show)

    def _refresh_tab_data(self, tab_name):
        """Refresh data for specific tab"""
        app = MDApp.get_running_app()
        if not hasattr(app, "loop"):
            try:
                app.loop = asyncio.get_event_loop()
            except RuntimeError:
                app.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(app.loop)

        if tab_name == "users":
            asyncio.run_coroutine_threadsafe(self._load_users(), app.loop)
        elif tab_name == "storage":
            asyncio.run_coroutine_threadsafe(self._load_folders(), app.loop)
        elif tab_name == "logs":
            asyncio.run_coroutine_threadsafe(self._load_activity_logs(), app.loop)
        elif tab_name == "dashboard":
            asyncio.run_coroutine_threadsafe(self._load_storage_stats(), app.loop)

    def refresh_data(self):
        """Refresh all dashboard data and update any open popups"""
        app = MDApp.get_running_app()
        if not hasattr(app, "loop"):
            try:
                app.loop = asyncio.get_event_loop()
            except RuntimeError:
                app.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(app.loop)

        asyncio.run_coroutine_threadsafe(self._load_all_data(), app.loop)
        
        # Refresh folder details popup if it's open
        if hasattr(self, 'folder_details_popup') and self.folder_details_popup and self.folder_details_popup.content:
            folder_title = self.folder_details_popup.content.children[-1].text
            if folder_title.startswith('Folder: '):
                folder = folder_title[8:]  # Extract folder name from title
                Clock.schedule_once(lambda dt: asyncio.run_coroutine_threadsafe(self._show_folder_details(folder), app.loop), 0.1)

    async def _load_all_data(self):
        """Load all dashboard data"""
        try:
            await asyncio.gather(
                self._load_storage_stats(),
                self._load_users(),
                self._load_folders(),
                self._load_activity_logs()
            )
            # Update dashboard stats after loading data
            Clock.schedule_once(lambda dt: self._update_dashboard_stats(), 0.1)
            Logger.info("Admin dashboard data loaded")
        except Exception as e:
            Logger.error(f"Dashboard data loading error: {str(e)}")
            self._load_mock_data()

    def _update_dashboard_stats(self):
        """Update dashboard statistics display"""
        # Update user count on dashboard - Fix: Changed user_list to users_list
        if hasattr(self.ids, 'user_count_label'):
            self.ids.user_count_label.text = str(len(self.users_list))
            Logger.info(f"Updated dashboard user count: {len(self.users_list)}")
        
        # Update folder count on dashboard
        if hasattr(self.ids, 'folder_count_label'):
            self.ids.folder_count_label.text = str(len(self.folder_list))
            Logger.info(f"Updated dashboard folder count: {len(self.folder_list)}")
        
        # Update any other dashboard stats as needed

    async def _load_storage_stats(self):
        """Load storage statistics"""
        try:
            if not self.s3_helper and not self.permission_manager:
                self._update_mock_storage_stats()
                return

            if self.permission_manager:
                stats = await self.permission_manager.get_bucket_stats()
            else:
                stats = await self.s3_helper.get_bucket_stats()

            Clock.schedule_once(lambda dt: self._update_storage_display(stats))
        except Exception as e:
            Logger.error(f"Storage stats error: {str(e)}")
            self._update_mock_storage_stats()

    def _update_storage_display(self, stats):
        """Update storage statistics display"""
        if hasattr(self.ids, 'storage_label'):
            self.ids.storage_label.text = f"{stats.get('total_size_gb', 0):.1f} GB / 50 GB"

        if hasattr(self.ids, 'storage_progress'):
            self.ids.storage_progress.value = min(100, stats.get('usage_percentage', 0))

    def _update_mock_storage_stats(self):
        """Update with mock storage stats"""
        mock_stats = {
            'total_size_gb': 2.5,
            'usage_percentage': 5,
            'total_files': 15
        }
        self._update_storage_display(mock_stats)

    async def _load_users(self):
        """Load users data from DynamoDB using UserManager"""
        try:
            if self.user_manager:
                Logger.info("Fetching users from DynamoDB...")
                # Use UserManager to get users from DynamoDB
                users = await self.user_manager.get_all_users()
                
                if users:
                    # Fix: Changed user_list to users_list
                    self.users_list = users
                    Logger.info(f"Successfully loaded {len(self.users_list)} users from DynamoDB")
                else:
                    Logger.warning("No users found in DynamoDB, checking if we need to create default admin")
                    # Check if we need to create a default admin user
                    await self._ensure_admin_user()
                    # Try loading users again
                    users = await self.user_manager.get_all_users()
                    # Fix: Changed user_list to users_list
                    self.users_list = users or []
                    Logger.info(f"Loaded {len(self.users_list)} users after admin check")
            else:
                # Use mock data if no user manager
                Logger.warning("UserManager not available, using mock data")
                self._update_mock_users()
                Logger.info("Using mock user data")

            # Update UI
            Clock.schedule_once(lambda dt: self._update_users_list(), 0)
            # Update dashboard stats
            Clock.schedule_once(lambda dt: self._update_dashboard_stats(), 0.1)

        except Exception as e:
            Logger.error(f"Error loading users from DynamoDB: {str(e)}")
            Logger.error(traceback.format_exc())
            # Fall back to mock data
            self._update_mock_users()

    async def _ensure_admin_user(self):
        """Ensure there is at least one admin user in the database"""
        try:
            if not self.user_manager:
                return

            # Check if we have any users
            users = await self.user_manager.get_all_users()
            if users:
                return  # Users exist, no need to create admin

            # Create default admin user
            from core.aws.config import AWSConfig
            admin_username = AWSConfig.ADMIN_USERNAME
            admin_password = AWSConfig.ADMIN_PASSWORD

            if not admin_username or not admin_password:
                Logger.warning("Admin credentials not configured, cannot create default admin")
                return

            Logger.info(f"Creating default admin user: {admin_username}")

            admin_data = {
                'username': admin_username,
                'password': admin_password,
                'email': f"{admin_username}@example.com",
                'role': 'admin',
                'access_level': 'both',
                'folder_access': ['/'],
                'status': 'active'
            }

            result = await self.user_manager.create_user(admin_data)
            if result.get('success'):
                Logger.info("Default admin user created successfully")
            else:
                Logger.error(f"Failed to create default admin: {result.get('error')}")

        except Exception as e:
            Logger.error(f"Error ensuring admin user: {str(e)}")
            Logger.error(traceback.format_exc())

    async def _async_create_user(self, user_data):
        """Create user using UserManager"""
        try:
            result = await self.user_manager.create_user(user_data)
            
            if result.get('success'):
                self.show_snackbar("User created successfully")
                return {'success': True}
            else:
                error_msg = result.get('error', 'Failed to create user')
                self.show_snackbar(f"Error: {error_msg}")
                return {'success': False, 'error': error_msg}

        except Exception as e:
            error_msg = str(e)
            Logger.error(f"User creation error: {error_msg}")
            self.show_snackbar(f"Error: {error_msg}")
            return {'success': False, 'error': error_msg}

    def _update_users_list(self):
        """Update the users list in the UI"""
        if not hasattr(self.ids, 'users_list'):
            Logger.error("users_list not found in IDs")
            return

        users_list = self.ids.users_list
        users_list.clear_widgets()

        # Update user count label if available
        if hasattr(self.ids, 'user_count_label'):
            self.ids.user_count_label.text = f"Total Users: {len(self.users_list)}"

        Logger.info(f"Updating user list with {len(self.users_list)} users")

        for user in self.users_list:
            username = user.get('username', 'Unknown')
            role = user.get('role', 'user')
            status = user.get('status', 'active')
            access_level = user.get('access_level', 'pull')
            email = user.get('email', '')

            # Create list item with user info
            item = MDListItem(
                MDListItemLeadingIcon(
                    icon="account-circle" if status == 'active' else "account-off"
                ),
                MDListItemHeadlineText(
                    text=f"{username} ({role.capitalize()})"
                ),
                MDListItemSupportingText(
                    text=f"Access: {access_level} | Status: {status} | Email: {email}"
                )
            )

            # Create actions box
            actions_box = MDBoxLayout(
                orientation='horizontal',
                spacing="8dp",
                adaptive_size=True,
                pos_hint={'right': 1},
                padding=[0, 0, "16dp", 0]
            )

            # View Details button
            details_btn = MDButton(
                style="text",
                on_release=lambda x, u=user: self._show_user_details(u)
            )
            details_btn.add_widget(MDButtonText(text="DETAILS"))
            actions_box.add_widget(details_btn)

            # Edit button
            edit_btn = MDButton(
                style="text",
                on_release=lambda x, u=user: self._show_edit_user_dialog(u)
            )
            edit_btn.add_widget(MDButtonText(text="EDIT"))
            actions_box.add_widget(edit_btn)

            # Reset Password button removed for future implementation

            # Manage Permissions button
            perm_btn = MDButton(
                style="text",
                on_release=lambda x, u=user: self._show_manage_permissions_dialog(u)
            )
            perm_btn.add_widget(MDButtonText(text="PERMISSIONS"))
            actions_box.add_widget(perm_btn)

            # Toggle Status button
            status_btn = MDButton(
                style="text",
                on_release=lambda x, u=user: self._run_async_toggle(u['username'], u['status'])
            )
            status_btn.add_widget(MDButtonText(
                text="DISABLE" if status == 'active' else "ENABLE"
            ))
            actions_box.add_widget(status_btn)

            # Delete button (only for non-admin users)
            if role != 'admin':
                delete_btn = MDButton(
                    style="text",
                    theme_text_color="Custom",
                    on_release=lambda x, u=user: self._show_delete_user_dialog(u)
                )
                delete_btn.add_widget(MDButtonText(text="DELETE"))
                actions_box.add_widget(delete_btn)

            # Add actions to list item
            item.add_widget(actions_box)
            users_list.add_widget(item)

    def _run_async_toggle(self, username: str, current_status: str):
        """Run the async toggle task"""
        try:
            # Get or create event loop
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Create coroutine
            async def toggle_task():
                try:
                    await self._toggle_user_status(username, current_status)
                except Exception as e:
                    Logger.error(f"Toggle status error: {str(e)}")
                    self.show_snackbar("Failed to toggle user status")
            
            # Run the coroutine
            loop.run_until_complete(toggle_task())
            
        except Exception as e:
            Logger.error(f"Error scheduling toggle task: {str(e)}")
            self.show_snackbar("Error occurred while toggling status")

    async def _toggle_user_status(self, username: str, current_status: str):
        """Toggle user status between active and inactive"""
        try:
            new_status = 'inactive' if current_status == 'active' else 'active'
            if self.user_manager:
                result = await self.user_manager.update_user_status(username, new_status)
                if result['success']:
                    # Update local user list to reflect the change
                    for user in self.users_list:
                        if user['username'] == username:
                            user['status'] = new_status
                            break
                    # Refresh the users tab to show updated status
                    await self._refresh_users_list()
                    self.show_snackbar(f"User {username} status updated to {new_status}")
                else:
                    self.show_snackbar(f"Failed to update user status: {result.get('error', 'Unknown error')}")
            else:
                self.show_snackbar("User manager not initialized")
        except Exception as e:
            Logger.error(f"Error toggling user status: {str(e)}")
            self.show_snackbar(f"Error: {str(e)}")
            
    async def _refresh_users_list(self):
        """Refresh the users list in the UI after changes"""
        try:
            # Reload users from DynamoDB
            if self.user_manager:
                users = await self.user_manager.get_all_users()
                if users:
                    self.users_list = users

            # Update the UI on the main thread
            Clock.schedule_once(lambda dt: self._update_users_list(), 0)
            Clock.schedule_once(lambda dt: self._update_dashboard_stats(), 0.1)

        except Exception as e:
            Logger.error(f"Error refreshing users list: {str(e)}")
            Logger.error(traceback.format_exc())
            
    def _handle_status_update_completion(self, future):
        """Handle completion of status update operation"""
        try:
            result = future.result()
            if result and result.get('success'):
                # Get the username and updated status
                updated_attrs = result.get('updated_attributes', {})
                username = result.get('username', 'User')
                
                # Get the new status from updated attributes
                new_status = updated_attrs.get('status') or updated_attrs.get('#status')
                
                if new_status:
                    # Update local user list to reflect the change
                    for i, user in enumerate(self.users_list):
                        if user.get('username') == username:
                            self.users_list[i]['status'] = new_status
                            break
                    
                    # Show success message
                    status_text = 'enabled' if new_status == 'active' else 'disabled'
                    self.show_snackbar(f"User {username} {status_text} successfully")
                    Logger.info(f"Status update successful for {username}: {new_status}")
                    
                    # Trigger UI refresh
                    Clock.schedule_once(lambda dt: self.refresh_data(), 0.1)
            else:
                # Show error message
                error = result.get('error', 'Unknown error occurred')
                self.show_snackbar(f"Error updating status: {error}")
                Logger.error(f"Status update failed: {error}")
        except Exception as e:
            Logger.error(f"Error in status update completion handler: {str(e)}")
            Logger.error(traceback.format_exc())
            self.show_snackbar(f"Error: {str(e)}")

    def _update_mock_users(self):
        """Update with mock user data"""
        self.users_list = [
            {'username': 'admin', 'role': 'admin', 'access_level': 'full', 'status': 'active', 
             'folder_access': ['/', 'public/', 'shared/', 'users/']},
            {'username': 'user1', 'role': 'user', 'access_level': 'pull', 'status': 'active',
             'folder_access': ['public/', 'shared/', 'users/user1/']},
            {'username': 'user2', 'role': 'user', 'access_level': 'push', 'status': 'active',
             'folder_access': ['public/', 'users/user2/']}
        ]
        self._update_users_list()

    def _handle_edit_user(self, username, role, access_level, folder_access, popup=None):
        """Process user edit form submission"""
        if not username:
            self.show_snackbar("Username is required")
            return
    
        # Validate role
        if role.lower() not in ['user', 'admin']:
            self.show_snackbar("Role must be either 'user' or 'admin'")
            return
    
        # Validate access level
        if access_level.lower() not in ['pull', 'push', 'both', 'full']:
            self.show_snackbar("Access level must be 'pull', 'push', 'both', or 'full'")
            return
        
        # Close dialog if provided
        if popup:
            popup.dismiss()
    
        # Show loading message
        self.show_snackbar(f"Updating user {username}...")
    
        # Process folder access (convert comma-separated string to list)
        folder_list = [folder.strip() for folder in folder_access.split(',') if folder.strip()]
        
        # Create updates dictionary
        updates = {
            'role': role.lower(),
            'access_level': access_level.lower(),
            'folder_access': folder_list,
            'last_modified': datetime.utcnow().isoformat()
        }

        # If user_manager is available, update user using our direct DynamoDB method
        app = MDApp.get_running_app()
        if not hasattr(app, 'loop'):
            try:
                app.loop = asyncio.get_event_loop()
            except RuntimeError:
                app.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(app.loop)

        asyncio.run_coroutine_threadsafe(
            self._async_update_user(username, updates),
            app.loop
        )

    def _show_edit_user_dialog(self, user):
        """Show dialog to edit user details"""
        try:
            Logger.info(f"[Showing edit dialog for user] {user['username']}")
            
            # Store the current user being edited
            self.current_edit_user = user
            
            # Create the main dialog box
            dialog_box = MDBoxLayout(
                orientation='vertical',
                spacing=dp(20),
                padding=dp(20),
                size_hint_y=None,
                height=dp(450),  # Increased height to accommodate all content
                md_bg_color=[1, 1, 1, 1]  # White background
            )
            
            # Add title
            title = MDLabel(
                text=f"Edit User: {user['username']}",
                font_size="24sp",
                bold=True,
                size_hint_y=None,
                height=dp(40)
            )
            dialog_box.add_widget(title)
            
            # Create fields dictionary to store references
            self.edit_fields = {}
            
            # Add fields
            fields = [
                ('email', 'Email', user.get('email', '')),
                ('role', 'Role', user.get('role', 'user')),
                ('access_level', 'Access Level', user.get('access_level', 'pull')),
                ('status', 'Status', user.get('status', 'active'))
            ]
            
            # Fields container
            fields_box = MDBoxLayout(
                orientation='vertical',
                spacing=dp(10),
                size_hint_y=None,
                height=dp(250)  # Height for fields
            )
            
            for field_id, label, value in fields:
                field = CustomTextField(
                    hint_text=label,
                    text=str(value),
                    size_hint_y=None,
                    height=dp(48)
                )
                self.edit_fields[field_id] = field
                fields_box.add_widget(field)
                
            dialog_box.add_widget(fields_box)
            
            # Add help text
            help_text = MDLabel(
                text="Edit user details and click Save to update",
                theme_text_color="Secondary",
                font_size="14sp",
                size_hint_y=None,
                height=dp(30)
            )
            dialog_box.add_widget(help_text)
            
            # Create buttons container
            buttons = MDBoxLayout(
                orientation='horizontal',
                spacing=dp(8),
                size_hint_y=None,
                height=dp(48),
                padding=[0, dp(20), 0, 0]  # Add top padding
            )
            
            # Cancel button
            cancel_btn = MDButton(
                style="text",
                on_release=lambda x: self.edit_dialog.dismiss()
            )
            cancel_btn.add_widget(MDButtonText(text="CANCEL"))
            buttons.add_widget(cancel_btn)
            
            # Save button
            save_btn = MDButton(
                style="filled",
                on_release=lambda x: self._handle_save_button_press(user['username'])
            )
            save_btn.add_widget(MDButtonText(text="SAVE"))
            buttons.add_widget(save_btn)
            
            dialog_box.add_widget(buttons)
            
            # Create the dialog using the new properties
            self.edit_dialog = Popup(
                title="",  # Empty title since we have it in the content
                content=dialog_box,
                size_hint=(None, None),
                size=(dp(400), dp(500)),
                auto_dismiss=True,
                background_color=[0.95, 0.95, 0.95, 1.0]  # Light gray background
            )
            
            # Show the dialog
            self.edit_dialog.open()
            Logger.info("Edit user dialog opened successfully")
            
        except Exception as e:
            Logger.error(f"Error showing edit dialog: {str(e)}")
            Logger.error(traceback.format_exc())
            self.show_snackbar(f"Error: {str(e)}")

    def _handle_save_button_press(self, username):
        """Handle save button press in edit dialog with improved reliability"""
        try:
            Logger.info(f"Save button pressed for user: {username}")
            
            # Store the field values before dismissing the dialog
            if hasattr(self, 'edit_fields'):
                self.saved_field_values = {
                    'email': self.edit_fields['email'].text,
                    'role': self.edit_fields['role'].text.lower(),
                    'access_level': self.edit_fields['access_level'].text.lower(),
                    'status': self.edit_fields['status'].text.lower()
                }
                Logger.info(f"Stored field values: {self.saved_field_values}")
            else:
                Logger.error("Edit fields not found")
                self.show_snackbar("Error: Could not retrieve form data")
                return
            
            # Immediately dismiss the dialog
            if hasattr(self, 'edit_dialog') and self.edit_dialog:
                self.edit_dialog.dismiss()
                self.edit_dialog = None
            
            # Show loading message
            self.show_snackbar("Saving changes...")
            
            # Schedule the save operation to run in the next frame
            Clock.schedule_once(lambda dt: self._execute_save_operation(username), 0.1)
            
        except Exception as e:
            Logger.error(f"Error in save button handler: {str(e)}")
            Logger.error(traceback.format_exc())
            self.show_snackbar(f"Error: {str(e)}")

    def _execute_save_operation(self, username):
        """Execute the save operation in a more reliable way"""
        try:
            # Get the app instance
            app = MDApp.get_running_app()
            
            # Create or get event loop
            if not hasattr(app, 'loop'):
                try:
                    app.loop = asyncio.get_event_loop()
                except RuntimeError:
                    app.loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(app.loop)
            
            # Verify DynamoDB manager is available
            if not hasattr(self, 'dynamo_manager') or not self.dynamo_manager:
                Logger.error("DynamoDB manager not available")
                self.show_snackbar("Error: DynamoDB manager not available")
                return
            
            # Create a task for the save operation
            future = asyncio.run_coroutine_threadsafe(
                self._handle_save_edit(username),
                app.loop
            )
            
            # Add a callback to handle the result
            future.add_done_callback(self._handle_save_completion)
            
        except Exception as e:
            Logger.error(f"Error executing save operation: {str(e)}")
            Logger.error(traceback.format_exc())
            self.show_snackbar(f"Error: {str(e)}")

    def _handle_save_completion(self, future):
        """Handle completion of save operation"""
        try:
            # Get the result from the future
            result = future.result()
            
            if result and result.get('success'):
                # Show success message
                self.show_snackbar("User details updated successfully")
                
                # Update the UI immediately
                Clock.schedule_once(lambda dt: self._update_users_list(), 0.1)
                
                # Refresh data from server
                Clock.schedule_once(lambda dt: self.refresh_data(), 0.5)
            else:
                # Show error message
                error = result.get('error', 'Unknown error occurred')
                self.show_snackbar(f"Error updating user: {error}")
        except Exception as e:
            Logger.error(f"Error in save completion handler: {str(e)}")
            self.show_snackbar(f"Error: {str(e)}")

    async def _handle_save_edit(self, username):
        """Process user edit and save to DynamoDB with retry logic"""
        try:
            # Use the stored field values instead of trying to access edit_fields
            if not hasattr(self, 'saved_field_values'):
                return {'success': False, 'error': 'Form data not found'}
            
            # Get the updates from stored values
            updates = self.saved_field_values.copy()  # Make a copy to avoid modifying the original
            
            # Ensure username is included in updates
            updates['username'] = username
            
            # Quick validation
            if updates['role'] not in ['user', 'admin']:
                return {'success': False, 'error': "Role must be either 'user' or 'admin'"}
            
            if updates['access_level'] not in ['pull', 'push', 'both', 'full']:
                return {'success': False, 'error': "Access level must be 'pull', 'push', 'both', or 'full'"}
            
            if updates['status'] not in ['active', 'inactive']:
                return {'success': False, 'error': "Status must be either 'active' or 'inactive'"}
            
            # Implement retry logic for more reliability
            max_retries = 3
            retry_count = 0
            last_error = None
            
            while retry_count < max_retries:
                try:
                    # Log the update attempt
                    Logger.info(f"Update attempt {retry_count + 1} for user {username} with data: {updates}")
                    
                    # Use DynamoManager's update_user method
                    updated_user = await self.dynamo_manager.update_user(username, updates)
                    
                    # Update the local user list
                    for user in self.users_list:
                        if user['username'] == username:
                            user.update(updates)
                            break
                    
                    # Clear the stored field values
                    if hasattr(self, 'saved_field_values'):
                        delattr(self, 'saved_field_values')
                    
                    return {'success': True, 'user': updated_user}
                    
                except Exception as e:
                    retry_count += 1
                    last_error = str(e)
                    Logger.warning(f"Update attempt {retry_count} failed: {str(e)}")
                    
                    # Check for ValidationException
                    if "ValidationException" in last_error and "Missing the key username" in last_error:
                        Logger.error("Username key missing error detected, trying alternative approach")
                        try:
                            # Try direct update with explicit key
                            result = await self._update_user_directly_in_dynamo(username, updates)
                            if result:
                                Logger.info(f"Direct update successful for user {username}")
                                return {'success': True, 'user': result}
                        except Exception as direct_error:
                            Logger.error(f"Direct update failed: {str(direct_error)}")
                    
                    # Wait a bit before retrying
                    await asyncio.sleep(0.5)
            
            # If we get here, all retries failed
            Logger.error(f"All update attempts failed after {max_retries} retries. Last error: {last_error}")
            return {'success': False, 'error': f"Failed after {max_retries} attempts: {last_error}"}
                
        except Exception as e:
            Logger.error(f"Error in _handle_save_edit: {str(e)}")
            return {'success': False, 'error': str(e)}

    def _show_user_details(self, user):
        """Show user details with improved UI styling"""
        try:
            Logger.info(f"Showing details for user: {user.get('username')}")
            
            # Close any existing dialog
            if hasattr(self, 'dialog') and self.dialog:
                self.dialog.dismiss()
                self.dialog = None
            
            # Create the main content layout
            content = MDBoxLayout(
                orientation='vertical',
                spacing=dp(15),
                padding=dp(24),
                md_bg_color=[1, 1, 1, 1],  # White background
                size_hint_y=None,
                height=dp(450)
            )
            
            # Add title
            title = MDLabel(
                text=f"User details: {user.get('username')}",
                font_size="22sp",
                bold=True,
                size_hint_y=None,
                height=dp(40)
            )
            content.add_widget(title)
            
            # Create fields container
            fields_container = MDBoxLayout(
                orientation='vertical',
                spacing=dp(20),
                size_hint_y=None,
                height=dp(300)
            )
            
            # Add user details as styled fields
            field_data = [
                {"label": "Email:", "value": user.get('email', '')},
                {"label": "Role:", "value": user.get('role', 'user')},
                {"label": "Access Level:", "value": user.get('access_level', 'pull')},
                {"label": "Status:", "value": user.get('status', 'active')}
            ]
            
            for field in field_data:
                field_row = MDBoxLayout(
                    orientation='horizontal',
                    size_hint_y=None,
                    height=dp(40)
                )
                
                label = MDLabel(
                    text=field['label'],
                    bold=True,
                    size_hint_x=0.3,
                    halign="left"
                )
                
                value = MDLabel(
                    text=field['value'],
                    size_hint_x=0.7,
                    halign="left"
                )
                
                field_row.add_widget(label)
                field_row.add_widget(value)
                fields_container.add_widget(field_row)
            
            # Add folder access section
            folder_label = MDLabel(
                text="Folder Access:",
                bold=True,
                size_hint_y=None,
                height=dp(30),
                halign="left"
            )
            fields_container.add_widget(folder_label)
            
            # Get folder access list
            folder_access = user.get('folder_access', [])
            folder_text = '\n'.join(folder_access) if folder_access else 'None'
            
            folder_value = MDLabel(
                text=folder_text,
                size_hint_y=None,
                height=dp(80),
                halign="left"
            )
            fields_container.add_widget(folder_value)
            
            content.add_widget(fields_container)
            
            # Create buttons container
            buttons = MDBoxLayout(
                orientation='horizontal',
                spacing=dp(10),
                size_hint_y=None,
                height=dp(48),
                pos_hint={'center_x': 0.5}
            )
            
            # Close button
            close_btn = MDButton(
                style="filled",
                size_hint_x=None,
                width=dp(120),
                on_release=lambda x: self.dialog.dismiss()
            )
            close_btn.add_widget(MDButtonText(text="CLOSE"))
            buttons.add_widget(close_btn)
            
            content.add_widget(buttons)
            
            # Create popup
            self.dialog = Popup(
                title="",
                content=content,
                size_hint=(None, None),
                size=(dp(450), dp(500)),
                background_color=[0.95, 0.95, 0.95, 1.0],  # Light gray background
                auto_dismiss=True
            )
            
            # Show dialog
            self.dialog.open()
            Logger.info("User details dialog opened successfully")
            
        except Exception as e:
            Logger.error(f"Error showing user details: {str(e)}")
            Logger.error(traceback.format_exc())
            self.show_snackbar(f"Error: {str(e)}")

    def _show_update_role_dialog(self, user):
        """Show dialog to update user role"""
        if self.dialog:
            self.dialog.dismiss()
            self.dialog = None

        # Create content box
        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(16),
            padding=dp(20),
            adaptive_height=True
        )

        # Add title
        title = MDLabel(
            text="Update User Role",
            font_size="20sp",
            bold=True,
            size_hint_y=None,
            height=dp(40)
        )
        content.add_widget(title)

        # Add role field
        self.role_input = MDTextField(
            hint_text="New Role",
            mode="outlined",
            size_hint_y=None,
            height=dp(48)
        )
        content.add_widget(self.role_input)

        # Create buttons
        buttons = MDBoxLayout(
            orientation='horizontal',
            spacing=dp(16),
            size_hint_y=None,
            height=dp(50)
        )

        # Update button
        update_button = MDButton(
            style="filled",
            on_release=lambda x: self._handle_update_role(user['username'], self.role_input.text)
        )
        update_button.add_widget(MDButtonText(text="UPDATE"))
        buttons.add_widget(update_button)

        # Cancel button
        cancel_button = MDButton(
            style="text",
            on_release=lambda x: self.dialog.dismiss()
        )
        cancel_button.add_widget(MDButtonText(text="CANCEL"))
        buttons.add_widget(cancel_button)

        content.add_widget(buttons)

        # Create dialog
        self.dialog = MDDialog()
        self.dialog.title = "Update User Role"
        self.dialog.content_cls = content

            # Open dialog
        self.dialog.open()
    
    def _show_manage_permissions_dialog(self, user):
        """Show dialog to manage user permissions with improved UI styling and folder selector"""
        try:
            Logger.info(f"Showing permissions dialog for user: {user.get('username')}")
            
            # Close any existing dialog
            if hasattr(self, 'dialog') and self.dialog:
                self.dialog.dismiss()
                self.dialog = None
            
            # Create the main content layout
            content = MDBoxLayout(
                orientation='vertical',
                spacing=dp(15),
                padding=dp(24),
                md_bg_color=[1, 1, 1, 1],  # White background
                size_hint_y=None,
                height=dp(450)
            )
            
            # Add title
            title = MDLabel(
                text=f"Manage Permissions: {user.get('username')}",
                font_size="22sp",
                bold=True,
                size_hint_y=None,
                height=dp(40)
            )
            content.add_widget(title)
            
            # Create fields container
            fields_container = MDBoxLayout(
                orientation='vertical',
                spacing=dp(20),
                size_hint_y=None,
                height=dp(300)
            )
            
            # Current permissions section
            current_label = MDLabel(
                text="Current Folder Access:",
                bold=True,
                size_hint_y=None,
                height=dp(30),
                halign="left"
            )
            fields_container.add_widget(current_label)
            
            # Get folder access list
            folder_access = user.get('folder_access', [])
            folder_text = '\n'.join(folder_access) if folder_access else 'None'
            
            current_folders = MDLabel(
                text=folder_text,
                size_hint_y=None,
                height=dp(80),
                halign="left"
            )
            fields_container.add_widget(current_folders)
    
            # Access level field - read-only, automatically set based on user's access level
            access_level_label = MDLabel(
                text="Access Level (automatically set):",
                bold=True,
                size_hint_y=None,
                height=dp(30),
                halign="left"
            )
            fields_container.add_widget(access_level_label)
            
            # Get user's access level
            user_access_level = user.get('access_level', 'pull')
            
            # Create read-only access field
            access_field = MDTextField(
                hint_text="User's access level",
                mode="outlined",
                text=user_access_level,
                size_hint_y=None,
                height=dp(48),
                readonly=True  # Make it read-only
            )
            fields_container.add_widget(access_field)
            
            content.add_widget(fields_container)
            
            # Create buttons container
            buttons = MDBoxLayout(
                orientation='horizontal',
                spacing=dp(10),
                size_hint_y=None,
                height=dp(48),
                pos_hint={'right': 1}
            )
            
            # Cancel button
            cancel_btn = MDButton(
                style="text",
                size_hint_x=None,
                width=dp(120),
                on_release=lambda x: self.dialog.dismiss()
            )
            cancel_btn.add_widget(MDButtonText(text="CANCEL"))
            buttons.add_widget(cancel_btn)
    
            # Select Folders button - calls the new folder selector
            select_folders_btn = MDButton(
                style="filled",
                size_hint_x=None,
                width=dp(180),
                on_release=lambda x: self._show_folder_selector(user)
            )
            select_folders_btn.add_widget(MDButtonText(text="SELECT FOLDERS"))
            buttons.add_widget(select_folders_btn)
            
            content.add_widget(buttons)
            
            # Create popup
            self.dialog = Popup(
                title="",
                content=content,
                size_hint=(None, None),
                size=(dp(450), dp(500)),
                background_color=[0.95, 0.95, 0.95, 1.0],  # Light gray background
                auto_dismiss=True
            )
            
            # Show dialog
            self.dialog.open()
            Logger.info("Permissions dialog opened successfully")
            
        except Exception as e:
            Logger.error(f"Error showing permissions dialog: {str(e)}")
            Logger.error(traceback.format_exc())
            self.show_snackbar(f"Error: {str(e)}")

    def _show_folder_selector(self, user):
        """Show the folder selector dialog with callback fix"""
        # Close the current dialog
        if hasattr(self, 'dialog') and self.dialog:
            self.dialog.dismiss()
            self.dialog = None
            
        try:
            username = user.get('username', 'unknown')
            Logger.info(f"Showing folder selector for user: {username}")
            
            # Get current folders this user has access to
            current_folders = user.get('folder_access', [])
            Logger.info(f"Current folders for {username}: {current_folders}")

            # Get all available folders from S3
            available_folders = self.folder_list
            
            # If no folders loaded yet, try to fetch them
            if not available_folders:
                app = MDApp.get_running_app()
                if hasattr(app, 'loop'):
                    # Load folders asynchronously
                    Logger.info("Loading folders from S3...")
                    asyncio.run_coroutine_threadsafe(self._load_folders(), app.loop)
                    # Show a temporary loading message
                    self.show_snackbar("Loading folders from S3...")
                    # Use mock folders until real ones are loaded
                    available_folders = ['/', 'public/', 'shared/', 'users/']
                else:
                    # Fallback to default folders
                    available_folders = ['/', 'public/', 'shared/', 'users/']
                    Logger.warning("Using default folders")
            
            Logger.info(f"Available folders for selection: {available_folders}")
            
            # Define the callback function outside of FolderSelector initialization
            def selection_callback(selected_folders):
                Logger.info(f"SELECTION CALLBACK CALLED with folders: {selected_folders}")
                self._handle_folder_selection(username, selected_folders)
                
            # Create and show the folder selector
            selector = FolderSelector(
                available_folders=available_folders,
                current_folders=current_folders,
                on_selection_complete=selection_callback  # Pass the callback properly
            )
            selector.open()
            
        except Exception as e:
            Logger.error(f"Error showing folder selector: {str(e)}")
            Logger.exception("Folder selector error")
            self.show_snackbar(f"Error: {str(e)}")
    
    # Add a separate method to handle the folder selection
    def _handle_folder_selection(self, username, selected_folders):
        """Handle the folder selection result with synchronous updates and UI refresh"""
        try:
            Logger.info(f"Processing folder selection for {username}: {selected_folders}")
            
            # Show loading message
            self.show_snackbar(f"Updating folder access for {username}...")
            
            # Create updates dictionary
            updates = {
                'folder_access': selected_folders,
                'last_modified': datetime.utcnow().isoformat()
            }
            
            # Use threading for the DynamoDB operation
            import threading
            
            def update_in_thread():
                try:
                    # Call the update function directly
                    result = self._direct_dynamo_update(username, updates)
                    
                    # Handle the result on the main thread
                    from kivy.clock import Clock
                    Clock.schedule_once(lambda dt: self._handle_update_result(result, username, selected_folders), 0)
                except Exception as e:
                    Logger.error(f"Error in update thread: {str(e)}")
                    from kivy.clock import Clock
                    Clock.schedule_once(lambda dt: self.show_snackbar(f"Error: {str(e)}"), 0)
            
            # Start the update in a separate thread
            update_thread = threading.Thread(target=update_in_thread)
            update_thread.daemon = True
            update_thread.start()

        except Exception as e:
            Logger.error(f"Error handling folder selection: {str(e)}")
            Logger.exception("Folder selection handling error")
            self.show_snackbar(f"Error: {str(e)}")
    # Add a completion handler for the update
    def _handle_update_completion(self, future):
        """Handle completion of the update operation"""
        try:
            # Get the result
            result = future.result()
            Logger.info(f"Update operation completed with result: {result}")
            
            if result and result.get('success'):
                # Show success message
                self.show_snackbar(f"Folder access updated successfully for {result.get('username')}")

                # Update UI
                Clock.schedule_once(lambda dt: self._update_users_list(), 0.1)
                Clock.schedule_once(lambda dt: self.refresh_data(), 0.5)
            else:
                # Show error message
                error = result.get('error', 'Unknown error')
                self.show_snackbar(f"Error updating folder access: {error}")
        except Exception as e:
            Logger.error(f"Error in update completion handler: {str(e)}")
            Logger.exception("Update completion handler error")
            self.show_snackbar(f"Error: {str(e)}")


    def _handle_update_permissions(self, username, folders_text, access_level):
        """Handle updating user permissions with improved reliability"""
        try:
            Logger.info(f"Updating permissions for user: {username} with access level: {access_level}")
            
            # No need to validate access level as it's automatically set from user's profile
            
            # Get the current user data
            current_user = None
            for user in self.users_list:
                if user.get('username') == username:
                    current_user = user
                    break
            
            if not current_user:
                self.show_snackbar(f"User {username} not found")
                return
            
            # Get current folder access
            current_folders = current_user.get('folder_access', [])
            
            # Parse new folder paths
            new_folders = []
            if folders_text.strip():
                new_folders = [f.strip() for f in folders_text.split(',') if f.strip()]
                
                # Ensure folders start with '/' if not already
                for i, folder in enumerate(new_folders):
                    if not folder.startswith('/') and not folder.endswith('/'):
                        new_folders[i] = f"{folder}/"
                    elif not folder.endswith('/'):
                        new_folders[i] = f"{folder}/"
            
            # Combine current and new folders, removing duplicates
            combined_folders = list(set(current_folders + new_folders))
            
            # Prepare updates
            updates = {
                'folder_access': combined_folders,
                'access_level': access_level.lower(),
                'last_modified': datetime.utcnow().isoformat()
            }
            
            # Show loading message
            self.show_snackbar(f"Updating permissions for {username}...")
            
            # Dismiss dialog
            if hasattr(self, 'dialog') and self.dialog:
                self.dialog.dismiss()
                self.dialog = None
            
            # Get or create event loop
            app = MDApp.get_running_app()
            if not hasattr(app, 'loop'):
                try:
                    app.loop = asyncio.get_event_loop()
                except RuntimeError:
                    app.loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(app.loop)
            
            # Run update in background with callback
            future = asyncio.run_coroutine_threadsafe(
                self._update_user_directly_in_dynamo(username, updates),
                app.loop
            )
            
            # Add callback to handle completion
            future.add_done_callback(self._handle_permissions_update_completion)
            
        except Exception as e:
            Logger.error(f"Error updating permissions: {str(e)}")
            Logger.error(traceback.format_exc())
            self.show_snackbar(f"Error: {str(e)}")
            
    def _handle_permissions_update_completion(self, future):
        """Handle completion of permissions update operation with improved UI refresh"""
        try:
            result = future.result()
            if result and result.get('success'):
                # Show success message immediately
                self.show_snackbar("User permissions updated successfully")

                # Schedule UI updates to ensure they run on the main thread
                app = MDApp.get_running_app()
                Clock.schedule_once(lambda dt: asyncio.run_coroutine_threadsafe(
                    self._load_all_data(), app.loop
                ), 0)

                # Force immediate refresh of users list
                Clock.schedule_once(lambda dt: self._update_users_list(), 0.1)
                Clock.schedule_once(lambda dt: self._force_reload_users(None), 0.2)
                
                # Refresh any open popups
                Clock.schedule_once(lambda dt: self.refresh_data(), 0.3)
                
                Logger.info("User permissions updated successfully, UI refreshed")
            else:
                # Show error message immediately
                error = result.get('error', 'Unknown error occurred')
                self.show_snackbar(f"Error updating permissions: {error}")
                Logger.error(f"Permissions update failed: {error}")
        except Exception as e:
            Logger.error(f"Error in permissions update completion handler: {str(e)}")
            Logger.error(traceback.format_exc())
            self.show_snackbar(f"Error: {str(e)}")

    async def _load_folders(self):
        """Load folders list"""
        try:
            Logger.info("Loading folders from S3...")
            
            if not self.s3_helper:
                Logger.warning("S3Helper not available, initializing new instance")
                from core.aws.s3_helper import S3Helper
                self.s3_helper = S3Helper()
                
            # Directly list objects from the bucket with delimiter to get "folders"
            import boto3
            from core.aws.config import AWSConfig
            
            # Get AWS config
            aws_config = AWSConfig.get_aws_config()
            bucket_name = "test-fm-user-bucket"
            
            Logger.info(f"Listing folders in bucket: {bucket_name}")
            
            # Create S3 client
            s3_client = boto3.client('s3', **aws_config)
            
            # List folders (objects with delimiter)
            response = await asyncio.to_thread(
                s3_client.list_objects_v2,
                Bucket=bucket_name,
                Delimiter='/'
            )
            
            folders = []
            
            # Process common prefixes (folders)
            if 'CommonPrefixes' in response:
                for prefix in response['CommonPrefixes']:
                    folder = prefix.get('Prefix')
                    if folder:
                        folders.append(folder)
                        Logger.info(f"Found folder: {folder}")
            
            # Root folder
            folders.insert(0, '/')

            self.folder_list = folders
            Logger.info(f"Loaded {len(folders)} folders: {folders}")
            
            # Update UI
            Clock.schedule_once(lambda dt: self._update_folders_list())
        except Exception as e:
            Logger.error(f"Error loading folders: {str(e)}")
            Logger.error(traceback.format_exc())
            # Fallback to mock data
            self._update_mock_folders()

    def _update_folders_list(self):
        """Update folders list display"""
        if not hasattr(self.ids, 'folders_list'):
            return

        folders_list = self.ids.folders_list
        folders_list.clear_widgets()

        for folder in sorted(self.folder_list):
            folder_name = folder.rstrip('/')
            if not folder_name:
                folder_name = "Root"

            item = MDListItem(
                MDListItemLeadingIcon(
                    icon="folder"
                ),
                MDListItemHeadlineText(
                    text=folder_name
                )
            )
            # Update to show folder contents on click
            item.bind(on_release=lambda x, f=folder: self._show_folder_contents(f))
            folders_list.add_widget(item)

    def _update_mock_folders(self):
        """Update with mock folder data"""
        self.folder_list = [
            '/',
            'public/',
            'shared/',
            'users/',
            'users/admin/',
            'users/user1/',
            'users/user2/'
        ]
        self._update_folders_list()

    async def _show_folder_details(self, folder):
        """Show dialog with folder details and user access"""
        Logger.info(f"Showing folder details for {folder}")
        
        try:
            users_with_access = []
            
            # First get users from users table who have this folder in their folder_access
            for user in self.users_list:
                if folder in user.get('folder_access', []):
                    users_with_access.append({
                        'username': user['username'],
                        'access_level': user.get('access_level', 'pull'),
                        'role': user.get('role', 'user')
                    })

            # Then get additional users from permissions table using GSI
            if hasattr(self, 'dynamo_manager') and self.dynamo_manager:
                try:
                    # Query permissions table using GSI on folder path
                    response = await asyncio.to_thread(
                        self.dynamo_manager.permissions_table.query,
                        IndexName='FolderIndex',
                        KeyConditionExpression='GSI1PK = :folder AND begins_with(GSI1SK, :prefix)',
                        ExpressionAttributeValues={
                            ':folder': f"FOLDER#{folder}",
                            ':prefix': 'USER#'
                        }
                    )
                    
                    # Add users from permissions table if not already in list
                    for item in response.get('Items', []):
                        username = item['username']
                        if not any(u['username'] == username for u in users_with_access):
                            users_with_access.append({
                                'username': username,
                                'access_level': item.get('access_level', 'pull'),
                                'role': 'user'  # Default to user role for permissions table entries
                            })
                            
                except Exception as e:
                    Logger.error(f"Error querying permissions table: {str(e)}")

            # Create content layout
            content = MDBoxLayout(
                orientation='vertical',
                spacing=dp(16),
                padding=[dp(24), dp(16), dp(24), dp(16)],
                md_bg_color=[1, 1, 1, 1],  # White background
                size_hint_y=None,
                height=dp(400)
            )
            
            # Add title
            title = MDLabel(
                text=f"Folder: {folder}",
                font_size="20sp",
                bold=True,
                halign="center",
                size_hint_y=None,
                height=dp(40)
            )
            content.add_widget(title)
            
            # Create scrollable list for users
            scroll = ScrollView(
                size_hint=(1, 1),
                do_scroll_x=False,
                do_scroll_y=True,
                bar_width=dp(4),
                bar_color=[0.7, 0.7, 0.7, 0.5],
                bar_inactive_color=[0.7, 0.7, 0.7, 0.2]
            )
            
            users_list = MDList()
            
            if not users_with_access:
                users_list.add_widget(
                    MDListItem(
                        MDListItemHeadlineText(
                            text="No users have access to this folder"
                        )
                    )
                )
            else:
                for user in users_with_access:
                    username = user['username']
                    access_level = user['access_level']
                    role = user['role']
                    
                    # Format the display text
                    if role == 'admin':
                        display_text = f"{username} (Admin - Full Access)"
                    else:
                        display_text = f"{username} ({access_level} access)"
                    
                    users_list.add_widget(
                        MDListItem(
                            MDListItemHeadlineText(
                                text=display_text
                            )
                        )
                    )
            
            scroll.add_widget(users_list)
            content.add_widget(scroll)
            
            # Add buttons
            buttons = MDBoxLayout(
                orientation='horizontal',
                spacing=dp(16),
                size_hint_y=None,
                height=dp(50)
            )
            
            # Close button
            close_button = MDButton(
                style="text",
                on_release=lambda x: self._dismiss_folder_details()
            )
            close_button.add_widget(MDButtonText(text="CLOSE"))
            buttons.add_widget(close_button)

            # Manage Access button
            manage_button = MDButton(
                style="filled",
                on_release=lambda x: self._show_manage_folder_access_popup(folder)
            )
            manage_button.add_widget(MDButtonText(text="MANAGE ACCESS"))
            buttons.add_widget(manage_button)
            
            content.add_widget(buttons)
            
            # Create popup
            self.folder_details_popup = Popup(
                title="Folder Details",
                content=content,
                size_hint=(None, None),
                size=(dp(450), dp(450)),
                auto_dismiss=True
            )
            
            # Show popup
            self.folder_details_popup.open()
            Logger.info("Folder details dialog opened")

        except Exception as e:
            Logger.error(f"Error showing folder details: {str(e)}")
            Logger.error(traceback.format_exc())
            self.show_snackbar(f"Error: {str(e)}")

    def _dismiss_folder_details(self):
        """Dismiss the folder details popup"""
        if hasattr(self, 'folder_details_popup') and self.folder_details_popup:
            self.folder_details_popup.dismiss()
            self.folder_details_popup = None
            
    def _show_manage_folder_access_popup(self, folder):
        """Show popup to manage folder access"""
        Logger.info(f"Showing manage access popup for folder: {folder}")
        
        # Dismiss any existing popups
        self._dismiss_folder_details()
        
        # Create content layout
        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(16),
            padding=[dp(24), dp(16), dp(24), dp(16)],
            md_bg_color=[1, 1, 1, 1],  # White background
            size_hint_y=None,
            height=dp(400)  # Increased height for new field
        )
        
        # Add title
        title = MDLabel(
            text=f"Manage Access for: {folder}",
            font_size="18sp",
            bold=True,
            halign="center",
            size_hint_y=None,
            height=dp(40)
        )
        content.add_widget(title)
        
        # Add username field
        self.access_username_input = MDTextField(
            hint_text="Enter Username",
            mode="outlined",
            size_hint_y=None,
            height=dp(48)
        )
        content.add_widget(self.access_username_input)
        
        # Add access level field
        self.access_level_input = MDTextField(
            hint_text="Access Level (pull/push/full)",
            mode="outlined",
            text="pull",  # Default value
            size_hint_y=None,
            height=dp(48)
        )
        content.add_widget(self.access_level_input)
        
        # Add help text
        help_text = MDLabel(
            text="Access Levels:\npull - Read only\npush - Write only\nfull - Full access",
            theme_text_color="Secondary",
            font_size="14sp",
            halign="left",
            size_hint_y=None,
            height=dp(80)
        )
        content.add_widget(help_text)
        
        # Add buttons
        buttons = MDBoxLayout(
            orientation='horizontal',
            spacing=dp(16),
            size_hint_y=None,
            height=dp(50)
        )
        
        # Cancel button
        cancel_button = MDButton(
            style="text",
            on_release=lambda x: self._dismiss_access_popup()
        )
        cancel_button.add_widget(MDButtonText(text="CANCEL"))
        buttons.add_widget(cancel_button)

        # Grant access button
        grant_button = MDButton(
            style="filled",
            md_bg_color=[0.2, 0.7, 0.3, 1.0],  # Green color
            on_release=lambda x: self._handle_grant_access_popup(folder)
        )
        grant_button.add_widget(MDButtonText(text="GRANT ACCESS"))
        buttons.add_widget(grant_button)
        
        # Revoke access button
        revoke_button = MDButton(
            style="filled",
            md_bg_color=[0.8, 0.2, 0.2, 1.0],  # Red color
            on_release=lambda x: self._handle_revoke_access_popup(folder)
        )
        revoke_button.add_widget(MDButtonText(text="REVOKE ACCESS"))
        buttons.add_widget(revoke_button)
        
        content.add_widget(buttons)
        
        # Create popup
        self.access_popup = Popup(
            title="Manage Folder Access",
            content=content,
            size_hint=(None, None),
            size=(dp(500), dp(400)),  # Increased height
            auto_dismiss=True
        )
        
        # Show popup
        self.access_popup.open()
        Logger.info("Manage folder access popup opened")
    
    def _dismiss_access_popup(self):
        """Dismiss the access management popup"""
        if hasattr(self, 'access_popup') and self.access_popup:
            self.access_popup.dismiss()
            self.access_popup = None
            
    def _handle_reset_password(self, username, new_password):
        """Handle password reset for a user"""
        try:
            # Validate inputs
            if not username:
                self.show_snackbar("Error: Username is required")
                return
                
            if not new_password or len(new_password) < 6:
                self.show_snackbar("Error: Password must be at least 6 characters")
                return
                
            # Dismiss the dialog
            if hasattr(self, 'dialog') and self.dialog:
                self.dialog.dismiss()
                
            # Show loading message
            self.show_snackbar(f"Resetting password for {username}...")
            
            # Get or create event loop
            app = MDApp.get_running_app()
            if not hasattr(app, 'loop'):
                try:
                    app.loop = asyncio.get_event_loop()
                except RuntimeError:
                    app.loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(app.loop)
            
            # Call the user manager to reset the password
            if self.user_manager:
                # Use the user manager's reset_user_password method
                future = asyncio.run_coroutine_threadsafe(
                    self.user_manager.reset_user_password(username, new_password),
                    app.loop
                )
                
                # Add callback to handle completion
                future.add_done_callback(self._handle_password_reset_completion)
            else:
                # Fallback to direct update if user_manager is not available
                self.show_snackbar("Error: User manager not available")
                
        except Exception as e:
            Logger.error(f"Error resetting password: {str(e)}")
            Logger.error(traceback.format_exc())
            self.show_snackbar(f"Error: {str(e)}")
            
    def _handle_password_reset_completion(self, future):
        """Handle completion of password reset operation"""
        try:
            result = future.result()
            if result and result.get('success'):
                # Show success message
                self.show_snackbar("Password reset successfully")
                Logger.info("Password reset successful")
            else:
                # Show error message
                error = result.get('error', 'Unknown error occurred')
                self.show_snackbar(f"Error resetting password: {error}")
                Logger.error(f"Password reset failed: {error}")
        except Exception as e:
            Logger.error(f"Error in password reset completion handler: {str(e)}")
            Logger.error(traceback.format_exc())
            self.show_snackbar(f"Error: {str(e)}")
    
    def _handle_grant_access_popup(self, folder):
        """Handle granting access from popup"""
        if not hasattr(self, 'access_username_input') or not self.access_username_input:
            self.show_snackbar("Error: Could not get username")
            return
            
        username = self.access_username_input.text
        if not username:
            self.show_snackbar("Please enter a username")
            return

        # Get access level
        access_level = self.access_level_input.text.lower()
        if access_level not in ['pull', 'push', 'full']:
            self.show_snackbar("Access level must be 'pull', 'push', or 'full'")
            return
            
        # Dismiss the popup
        self._dismiss_access_popup()
        
        # Call the existing grant access method with access level
        self._handle_grant_access(username, folder, access_level)
    
    def _handle_revoke_access_popup(self, folder):
        """Handle revoking access from popup"""
        if not hasattr(self, 'access_username_input') or not self.access_username_input:
            self.show_snackbar("Error: Could not get username")
            return
            
        username = self.access_username_input.text
        if not username:
            self.show_snackbar("Please enter a username")
            return
            
        # Dismiss the popup
        self._dismiss_access_popup()
        
        # Call the existing revoke access method
        self._handle_revoke_access(username, folder)

    def _handle_grant_access(self, username, folder, access_level='pull'):
        """Grant folder access to user with specified permission level"""
        Logger.info(f"Granting {access_level} access to {folder} for user {username}")
        
        if not username:
            self.show_snackbar("Please enter a username")
            return

        # Validate access level
        if access_level not in ['pull', 'push', 'full']:
            self.show_snackbar("Invalid access level. Must be 'pull', 'push', or 'full'")
            return

        # Show loading message
        self.show_snackbar(f"Updating access for {username}...")

        app = MDApp.get_running_app()
        if not hasattr(app, 'loop'):
            try:
                app.loop = asyncio.get_event_loop()
            except RuntimeError:
                app.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(app.loop)

        # Create the permission record with proper keys for querying
        permission_data = {
            'username': username,
            'folder_path': folder,
            'access_level': access_level,
            'granted_by': getattr(app, 'current_user', {}).get('username', 'system'),
            'granted_at': datetime.utcnow().isoformat(),
            'status': 'active',
            # Add GSI keys for querying by folder
            'GSI1PK': f"FOLDER#{folder}",
            'GSI1SK': f"USER#{username}",
            # Add composite sort key for status
            'sk': 'PERMISSION#ACTIVE'
        }

        async def update_permissions():
            try:
                Logger.info(f"Starting permission update for user {username}")
                
                # First check if user exists
                user = None
                for u in self.users_list:
                    if u.get('username') == username:
                        user = u
                        break

                if not user:
                    Logger.error(f"User {username} not found")
                    Clock.schedule_once(lambda dt: self.show_snackbar(f"User {username} not found"), 0)
                    return False

                try:
                    # First update permissions table
                    if hasattr(self, 'dynamo_manager') and self.dynamo_manager:
                        try:
                            # First check if permission already exists
                            existing_perm = await asyncio.to_thread(
                                self.dynamo_manager.permissions_table.get_item,
                                Key={
                                    'username': username,
                                    'folder_path': folder
                                }
                            )
                            
                            if 'Item' in existing_perm:
                                # Update existing permission
                                await asyncio.to_thread(
                                    self.dynamo_manager.permissions_table.update_item,
                                    Key={
                                        'username': username,
                                        'folder_path': folder
                                    },
                                    UpdateExpression="SET #al = :al, #st = :st, #gb = :gb, #ga = :ga, #gsi1pk = :gsi1pk, #gsi1sk = :gsi1sk, #sk = :sk",
                                    ExpressionAttributeNames={
                                        '#al': 'access_level',
                                        '#st': 'status',
                                        '#gb': 'granted_by',
                                        '#ga': 'granted_at',
                                        '#gsi1pk': 'GSI1PK',
                                        '#gsi1sk': 'GSI1SK',
                                        '#sk': 'sk'
                                    },
                                    ExpressionAttributeValues={
                                        ':al': access_level,
                                        ':st': 'active',
                                        ':gb': permission_data['granted_by'],
                                        ':ga': permission_data['granted_at'],
                                        ':gsi1pk': permission_data['GSI1PK'],
                                        ':gsi1sk': permission_data['GSI1SK'],
                                        ':sk': permission_data['sk']
                                    }
                                )
                                Logger.info(f"Updated existing permission record for {username}")
                            else:
                                # Create new permission record
                                await asyncio.to_thread(
                                    self.dynamo_manager.permissions_table.put_item,
                                    Item=permission_data
                                )
                                Logger.info(f"Created new permission record for {username}")

                            # Verify the permission was saved
                            verify_perm = await asyncio.to_thread(
                                self.dynamo_manager.permissions_table.get_item,
                                Key={
                                    'username': username,
                                    'folder_path': folder
                                }
                            )
                            
                            if 'Item' not in verify_perm:
                                raise Exception("Permission record not found after saving")
                            
                        except Exception as perm_error:
                            Logger.error(f"Error updating permissions table: {str(perm_error)}")
                            raise perm_error

                    # Then update user's folder_access in users table
                    folder_access = list(user.get('folder_access', []))
                    if folder not in folder_access:
                        folder_access.append(folder)
                        updates = {
                            'folder_access': folder_access,
                            'last_modified': datetime.utcnow().isoformat()
                        }
                        
                        Logger.info(f"Updating user {username} with new folder access: {folder_access}")
                        
                        # Update user in DynamoDB
                        result = await self._update_user_directly_in_dynamo(username, updates)
                        
                        if not result.get('success'):
                            error_msg = result.get('error', 'Unknown error')
                            Logger.error(f"Failed to update user in DynamoDB: {error_msg}")
                            raise Exception(f"Failed to update user: {error_msg}")
                            
                        Logger.info(f"Successfully updated user {username} in DynamoDB users table")
                    
                    # Reload users to refresh the data
                    await self._load_users()
                    
                    # Log the action
                    if self.audit_logger:
                        await self.audit_logger.log_event(
                            action="grant_folder_access",
                            user_id=username,
                            details={
                                "folder": folder,
                                "access_level": access_level,
                                "granted_by": permission_data['granted_by']
                            },
                            severity="info",
                            success=True
                        )
                    
                    # Refresh UI
                    Clock.schedule_once(lambda dt: self.refresh_data(), 0)
                    Clock.schedule_once(lambda dt: self.show_snackbar(f"Access granted for {username} to {folder}"), 0)
                    return True
                except Exception as update_error:
                    Logger.error(f"Error during permission update: {str(update_error)}")
                    Clock.schedule_once(lambda dt: self.show_snackbar(f"Error: {str(update_error)}"), 0)
                    return False

            except Exception as e:
                Logger.error(f"Error granting access: {str(e)}")
                Logger.error(traceback.format_exc())
                Clock.schedule_once(lambda dt: self.show_snackbar(f"Error: {str(e)}"), 0)
                return False

        # Run the update and refresh UI
        future = asyncio.run_coroutine_threadsafe(update_permissions(), app.loop)
        future.add_done_callback(lambda f: Clock.schedule_once(lambda dt: self.refresh_data(), 0))

    def _handle_revoke_access(self, username, folder):
        """Revoke folder access from user"""
        Logger.info(f"Revoking access to {folder} for user {username}")
        
        if not username:
            self.show_snackbar("Please enter a username")
            return

        # Show loading message
        self.show_snackbar(f"Updating access for {username}...")

        app = MDApp.get_running_app()
        if not hasattr(app, 'loop'):
            try:
                app.loop = asyncio.get_event_loop()
            except RuntimeError:
                app.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(app.loop)

        async def revoke_permissions():
            try:
                # Update permissions table to mark as revoked
                await asyncio.to_thread(
                    self.dynamo_manager.permissions_table.update_item,
                    Key={
                        'username': username,
                        'folder_path': folder
                    },
                    UpdateExpression="SET #status = :status, #revoked_at = :revoked_at, #revoked_by = :revoked_by",
                    ExpressionAttributeNames={
                        '#status': 'status',
                        '#revoked_at': 'revoked_at',
                        '#revoked_by': 'revoked_by'
                    },
                    ExpressionAttributeValues={
                        ':status': 'revoked',
                        ':revoked_at': datetime.utcnow().isoformat(),
                        ':revoked_by': getattr(app, 'current_user', {}).get('username', 'system')
                    }
                )

                # Update user's folder_access in users table
                user = None
                for u in self.users_list:
                    if u.get('username') == username:
                        user = u
                        break

                if user:
                    folder_access = list(user.get('folder_access', []))
                    if folder in folder_access:
                        folder_access.remove(folder)
                        updates = {'folder_access': folder_access}

                        # Update user in DynamoDB
                        await self._update_user_directly_in_dynamo(username, updates)
                        
                        # Reload users to refresh the data
                        await self._load_users()
                        
                        # Log the action
                        if self.audit_logger:
                            await self.audit_logger.log_event(
                                action="revoke_folder_access",
                                user_id=username,
                                details={
                                    "folder": folder,
                                    "revoked_by": getattr(app, 'current_user', {}).get('username', 'system')
                                },
                                severity="info",
                                success=True
                            )

                        self.show_snackbar(f"Access revoked for {username} from {folder}")
                        return True
                    else:
                        self.show_snackbar(f"User {username} does not have access to {folder}")
                        return False
                else:
                    self.show_snackbar(f"User {username} not found")
                    return False

            except Exception as e:
                Logger.error(f"Error revoking access: {str(e)}")
                Logger.error(traceback.format_exc())
                self.show_snackbar(f"Error: {str(e)}")
                return False

        # Run the update
        asyncio.run_coroutine_threadsafe(revoke_permissions(), app.loop)

    async def _create_user_directly_in_dynamo(self, user_data):
        """Create user directly in DynamoDB as a fallback"""
        try:
            Logger.info(f"Attempting direct DynamoDB user creation for: {user_data['username']}")
            
            if not hasattr(self.user_manager, 'users_table'):
                Logger.error("DynamoDB users table not available")
                return {'success': False, 'error': 'DynamoDB users table not available'}
                
            # Get the users table
            users_table = self.user_manager.users_table
            
            # Check if user already exists
            existing_user = await asyncio.to_thread(
                users_table.get_item,
                Key={'username': user_data['username'], 'sk': '#USER'}
            )
            
            if 'Item' in existing_user:
                Logger.warning(f"User {user_data['username']} already exists in DynamoDB")
                return {'success': False, 'error': 'Username already exists'}
            
            # Prepare user data for DynamoDB
            import uuid
            import bcrypt
            from datetime import datetime
            
            # Hash the password
            password_hash = bcrypt.hashpw(
                user_data['password'].encode('utf-8'),
                bcrypt.gensalt()
            ).decode('utf-8')

            # Create user item with username as primary key
            user_item = {
                'username': user_data['username'],  # Primary key
                'sk': '#USER',  # Sort key
                'uuid': str(uuid.uuid4()),
                'email': user_data['email'],
                'password_hash': password_hash,
                'role': user_data.get('role', 'user'),
                'access_level': user_data.get('access_level', 'pull'),
                'created_at': datetime.utcnow().isoformat(),
                'status': 'active',
                'folder_access': user_data.get('folder_access', [])
            }
            
            # Ensure username is present
            if 'username' not in user_item:
                raise ValueError('Missing required key: username')
            
            Logger.info(f"Direct DynamoDB user item prepared: {user_item}")
            
            # Put the item in DynamoDB
            await asyncio.to_thread(
                users_table.put_item,
                Item=user_item
            )
            
            # Verify the user was created
            verify_response = await asyncio.to_thread(
                users_table.get_item,
                Key={'username': user_data['username'], 'sk': '#USER'}
            )
            
            if 'Item' in verify_response:
                Logger.info(f"User {user_data['username']} successfully created directly in DynamoDB")
                # Remove sensitive data before returning
                result_item = user_item.copy()
                result_item.pop('password_hash')
                return {'success': True, 'user': result_item}
            else:
                Logger.error(f"User {user_data['username']} not found after creation attempt")
                return {'success': False, 'error': 'User creation failed - not found after creation'}

        except Exception as e:
            Logger.error(f"Error in direct DynamoDB user creation: {str(e)}")
            Logger.error(traceback.format_exc())
            return {'success': False, 'error': str(e)}

    async def _load_activity_logs(self):
        """Load activity logs from database"""
        try:
            logs = await self.db_manager.get_audit_logs(limit=10)
            Clock.schedule_once(lambda dt: self._update_logs_list(logs))
        except Exception as e:
            Logger.error(f"Activity log error: {str(e)}")
            self._update_mock_logs()

    def _update_logs_list(self, logs):
        """Update logs list display"""
        if not hasattr(self.ids, 'logs_list'):
            return

        logs_list = self.ids.logs_list
        logs_list.clear_widgets()

        for log in logs:
            timestamp = log.get('timestamp', 'Unknown')
            action = log.get('action', 'Unknown')
            user_id = log.get('user_id', 'System')

            item = MDListItem(
                MDListItemLeadingIcon(
                    icon="information"
                ),
                MDListItemHeadlineText(
                    text=f"{action}"
                ),
                MDListItemSupportingText(
                    text=f"{timestamp} - {user_id}"
                )
            )
            logs_list.add_widget(item)

    def _update_mock_logs(self):
        """Update with mock logs"""
        current_time = datetime.now().isoformat()
        mock_logs = [
            {'timestamp': current_time, 'action': 'login_success', 'user_id': 'admin'},
            {'timestamp': current_time, 'action': 'create_folder', 'user_id': 'admin'},
            {'timestamp': current_time, 'action': 'file_uploaded', 'user_id': 'user2'}
        ]
        self._update_logs_list(mock_logs)

    def _load_mock_data(self):
        """Load all mock data"""
        self._update_mock_storage_stats()
        self._update_mock_users()
        self._update_mock_folders()
        self._update_mock_logs()
        # Update dashboard stats after loading mock data
        Clock.schedule_once(lambda dt: self._update_dashboard_stats(), 0.1)

    def show_snackbar(self, message):
        """Show snackbar message"""
        try:
            snackbar = MDSnackbar(
                MDSnackbarText(
                    text=message,
                ),
                y=dp(24),
                pos_hint={"center_x": 0.5},
                size_hint_x=0.8,
                duration=2
            )
            snackbar.open()
        except Exception as e:
            Logger.error(f"Error showing snackbar: {str(e)}")

    def show_add_user_dialog(self):
        """Show a popup dialog for adding a new user"""
        Logger.info("Showing add user dialog popup")
        
        if hasattr(self, 'add_user_popup') and self.add_user_popup:
            self.add_user_popup.dismiss()
            self.add_user_popup = None
        
        # Create scroll view for content
        scroll_view = ScrollView(
            size_hint=(1, 1),
            do_scroll_x=False
        )
        
        # Create main content box with increased height
        main_content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(24),  # Increased spacing between widgets
            padding=[dp(24), dp(24), dp(24), dp(24)],  # Increased padding
            size_hint_y=None,
            height=dp(600),  # Increased height
            md_bg_color=[1, 1, 1, 1]  # White background
        )
        main_content.bind(minimum_height=main_content.setter('height'))

        # Add title with more space
        title = MDLabel(
            text="Add New User",
            font_size="24sp",
            bold=True,
            halign="center",
            size_hint_y=None,
            height=dp(60)  # Increased height
        )
        main_content.add_widget(title)
        
        # Store field references
        self.dialog_fields = {}
        
        # Fields container with increased spacing
        fields_box = MDBoxLayout(
            orientation='vertical',
            spacing=dp(24),  # Increased spacing between fields
            size_hint_y=None,
            height=dp(320)  # Increased height for fields section
        )
        
        # Username/Email field
        username_field = MDTextField(
            hint_text="Username/Email",
            mode="outlined",
            size_hint_y=None,
            height=dp(56)  # Increased height
        )
        self.dialog_fields['username_email'] = username_field
        fields_box.add_widget(username_field)

        # Password field
        password_field = MDTextField(
            hint_text="Password",
            mode="outlined",
            password=True,
            size_hint_y=None,
            height=dp(56)  # Increased height
        )
        self.dialog_fields['password'] = password_field
        fields_box.add_widget(password_field)

        # Role field
        role_field = MDTextField(
            hint_text="Role (user/admin)",
            mode="outlined",
            text="user",
            size_hint_y=None,
            height=dp(56)  # Increased height
        )
        self.dialog_fields['role'] = role_field
        fields_box.add_widget(role_field)

        # Access Level field
        access_field = MDTextField(
            hint_text="Access Level (pull/push/both)",
            mode="outlined",
            text="pull",
            size_hint_y=None,
            height=dp(56)  # Increased height
        )
        self.dialog_fields['access_level'] = access_field
        fields_box.add_widget(access_field)

        main_content.add_widget(fields_box)

        # Add spacer
        spacer = MDBoxLayout(
            size_hint_y=None,
            height=dp(20)  # Space before help text
        )
        main_content.add_widget(spacer)

        # Help text with increased height and better spacing
        help_text = MDLabel(
            text="Roles: 'user' for normal access, 'admin' for full control\nAccess: 'pull' for read, 'push' for write, 'both' for read/write",
            theme_text_color="Secondary",
            font_size="14sp",
            size_hint_y=None,
            height=dp(80),  # Increased height for help text
            halign="center"
        )
        main_content.add_widget(help_text)

        # Add another spacer
        spacer2 = MDBoxLayout(
            size_hint_y=None,
            height=dp(20)  # Space before buttons
        )
        main_content.add_widget(spacer2)

        # Create buttons box with increased spacing
        buttons_box = MDBoxLayout(
            orientation='horizontal',
            spacing=dp(24),  # Increased spacing between buttons
            size_hint_y=None,
            height=dp(56),  # Increased height
            padding=[dp(12), dp(12), dp(12), dp(12)]
        )

        # Cancel button with proper binding
        cancel_button = MDButton(
            style="text",
            size_hint_x=0.5,
            on_release=lambda x: self._dismiss_add_user_dialog()
        )
        cancel_button.add_widget(MDButtonText(text="CANCEL"))
        buttons_box.add_widget(cancel_button)

        # Add user button
        add_button = MDButton(
            style="filled",
            size_hint_x=0.5,
            on_release=lambda x: self._handle_add_user_from_dialog()
        )
        add_button.add_widget(MDButtonText(text="ADD USER"))
        buttons_box.add_widget(add_button)

        # Add buttons to main content
        main_content.add_widget(buttons_box)

        # Add main content to scroll view
        scroll_view.add_widget(main_content)

        # Create popup with increased size
        self.add_user_popup = Popup(
            title="",  # Empty title since we have it in the content
            content=scroll_view,
            size_hint=(None, None),
            size=(dp(450), dp(700)),  # Increased height
            auto_dismiss=False,
            background_color=[0.95, 0.95, 0.95, 1.0]  # Light gray background
        )
        
        # Open popup
        self.add_user_popup.open()
        
        # Log success
        Logger.info("Add user dialog opened")

    def _dismiss_add_user_dialog(self):
        """Dismiss the add user dialog"""
        if hasattr(self, 'add_user_popup') and self.add_user_popup:
            self.add_user_popup.dismiss()
            self.add_user_popup = None
        Logger.info("Add user dialog dismissed")

    def _handle_add_user_from_dialog(self):
        """Handle user creation from the add user dialog"""
        try:
            # Get values from dialog fields
            username = self.dialog_fields['username_email'].text.strip()
            password = self.dialog_fields['password'].text.strip()
            role = self.dialog_fields['role'].text.strip()
            access_level = self.dialog_fields['access_level'].text.strip()

            # Call existing add user handler
            result = self._handle_add_user(username, password, role, access_level)

            if result:
                # Close dialog on success
                self._dismiss_add_user_dialog()
                self.show_snackbar("User created successfully")
                # Refresh users list
                self._refresh_tab_data("users")
            else:
                self.show_snackbar("Failed to create user")

        except Exception as e:
            Logger.error(f"Error in _handle_add_user_from_dialog: {str(e)}")
            self.show_snackbar(f"Error: {str(e)}")

    def _handle_add_user(self, username, password, role, access_level):
        """Process user creation and save to DynamoDB"""
        Logger.info(f"_handle_add_user called with username: {username}, role: {role}, access_level: {access_level}")
        
        if not username or not password:
            Logger.warning("Username or password missing")
            self.show_snackbar("Username and password are required")
            return False

        # Validate role
        if role.lower() not in ['user', 'admin']:
            Logger.warning(f"Invalid role: {role}")
            self.show_snackbar("Role must be either 'user' or 'admin'")
            return False

        # Validate access level
        if access_level.lower() not in ['pull', 'push', 'both']:
            Logger.warning(f"Invalid access level: {access_level}")
            self.show_snackbar("Access level must be 'pull', 'push', or 'both'")
            return False

        # Create user data according to UserManager expectations
        user_data = {
            'username': username,  # Ensure username is included as a key
            'sk': '#USER',  # Add sort key for DynamoDB
            'password': password,
            'email': username if '@' in username else f"{username}@example.com",
            'role': role.lower(),
            'access_level': access_level.lower(),
            'folder_access': [],
            'status': 'active',
            'created_at': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat()
        }
        
        Logger.info(f"User data prepared: {user_data}")

        try:
            Logger.info(f"Starting user creation in DynamoDB: {username}")
            
            # Get or create event loop
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Run the coroutine and wait for it to complete
            Logger.info("Running user creation task synchronously")
            result = loop.run_until_complete(self._create_user_task(user_data))
            
            Logger.info(f"User creation completed with result: {result}")
            return result

        except Exception as e:
            Logger.error(f"Error starting user creation: {str(e)}")
            Logger.error(traceback.format_exc())
            self.show_snackbar(f"Error: {str(e)}")
            return False

    def on_add_user_quick_action(self, *args):
        """Handle Add User quick action button press"""
        Logger.info("Add User quick action pressed")
        # First switch to users tab
        self.show_tab("users")
        # Then show the add user dialog
        Clock.schedule_once(lambda dt: self.show_add_user_dialog(), 0.2)

    def on_logout_button_press(self, *args):
        """Handle logout button press"""
        Logger.info("Logout button pressed")
        self.logout()
        
    def logout(self):
        """Handle logout"""
        try:
            Logger.info("Logout method called")
            
            # Clear username display
            self.current_user_name = ""
            
            # Clear user data
            if hasattr(self, 'user_manager') and self.user_manager:
                # Log the logout event
                if hasattr(self, 'audit_logger') and self.audit_logger:
                    try:
                        # Get current user ID
                        app = MDApp.get_running_app()
                        user_id = getattr(app, 'current_user', {}).get('username', 'unknown_user') if hasattr(app, 'current_user') else 'unknown_user'
                        
                        # Log the event with correct parameters using the event loop
                        if hasattr(app, 'loop') and app.loop:
                            asyncio.run_coroutine_threadsafe(
                                self.audit_logger.log_event(
                                    action="logout",
                                    user_id=user_id,
                                    details={"method": "manual"},
                                    severity="info",
                                    success=True
                                ),
                                app.loop
                            )
                    except Exception as log_error:
                        Logger.error(f"Error logging logout: {str(log_error)}")
                        Logger.error(traceback.format_exc())
            
            # Switch to login screen
            app = MDApp.get_running_app()
            if not hasattr(app, "root") or not app.root:
                Logger.error("App root not available for logout")
                return

            # Clear current user data
            if hasattr(app, 'current_user'):
                app.current_user = None
            
            # Clear tokens
            if hasattr(app, 'access_token'):
                app.access_token = None
            if hasattr(app, 'refresh_token'):
                app.refresh_token = None
            
            # Switch to login screen
            try:
                app.root.current = 'login'
                Logger.info("Switched to login screen")
            except Exception as screen_error:
                Logger.error(f"Error switching screens: {str(screen_error)}")
                Logger.error(traceback.format_exc())
                # Try one more time with a delay
                Clock.schedule_once(lambda dt: setattr(app.root, 'current', 'login'), 0.1)

        except Exception as e:
            Logger.error(f"Error during logout: {str(e)}")
            Logger.error(traceback.format_exc())

    def _show_folder_contents(self, folder_path):
        """Show folder contents and available actions"""
        Logger.info(f"Showing contents of folder: {folder_path}")
        
        try:
            # Create content layout
            content = MDBoxLayout(
                orientation='vertical',
                spacing=dp(16),
                padding=[dp(24), dp(16), dp(24), dp(16)],
                md_bg_color=[1, 1, 1, 1],
                size_hint_y=None,
                height=dp(500)
            )
            
            # Add title with current path
            title = MDLabel(
                text=f"Folder: {folder_path}",
                font_size="20sp",
                bold=True,
                halign="center",
                size_hint_y=None,
                height=dp(40)
            )
            content.add_widget(title)
            
            # Add action buttons
            actions = MDBoxLayout(
                orientation='horizontal',
                spacing=dp(8),
                size_hint_y=None,
                height=dp(48),
                padding=[0, dp(8), 0, dp(8)]
            )
            
            # Get current user's permissions
            app = MDApp.get_running_app()
            current_user = getattr(app, 'current_user', {})
            access_level = current_user.get('access_level', 'none')
            
            # Upload button (requires push or full access)
            if access_level in ['push', 'full', 'both']:
                upload_button = MDButton(
                    style="filled",
                    size_hint=(None, None),
                    size=(dp(120), dp(48))
                )
                upload_button.add_widget(MDButtonText(text="Upload File"))
                upload_button.bind(on_release=lambda x: self._show_upload_dialog(folder_path))
                actions.add_widget(upload_button)
            
            # New Subfolder button (requires push or full access)
            if access_level in ['push', 'full', 'both']:
                subfolder_button = MDButton(
                    style="filled",
                    size_hint=(None, None),
                    size=(dp(140), dp(48))
                )
                subfolder_button.add_widget(MDButtonText(text="New Subfolder"))
                subfolder_button.bind(on_release=lambda x: self._show_create_subfolder_dialog(folder_path))
                actions.add_widget(subfolder_button)
            
            # Add actions to content
            content.add_widget(actions)
            
            # Create scrollable list for files
            scroll = ScrollView(
                size_hint=(1, 1),
                do_scroll_x=False,
                bar_width=dp(4)
            )
            
            files_list = MDList()
            
            # Get folder contents from S3
            app = MDApp.get_running_app()
            if not hasattr(app, 'loop'):
                app.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(app.loop)
            
            # List files in folder
            import boto3
            from core.aws.config import AWSConfig
            
            aws_config = AWSConfig.get_aws_config()
            s3_client = boto3.client('s3', **aws_config)
            bucket_name = "test-fm-user-bucket"
            
            # Ensure folder path ends with /
            if not folder_path.endswith('/'):
                folder_path += '/'
            
            try:
                response = s3_client.list_objects_v2(
                    Bucket=bucket_name,
                    Prefix=folder_path,
                    Delimiter='/'
                )
                
                # Add parent folder option if not in root
                if folder_path != '/':
                    parent_path = '/'.join(folder_path.rstrip('/').split('/')[:-1])
                    if not parent_path:
                        parent_path = '/'
                    
                    parent_item = MDListItem(
                        MDListItemLeadingIcon(
                            icon="folder-upload"
                        ),
                        MDListItemHeadlineText(
                            text=f".. (Parent Directory)"
                        )
                    )
                    parent_item.bind(on_release=lambda x: self._show_folder_contents(parent_path))
                    files_list.add_widget(parent_item)
                
                # Add subfolders first
                if 'CommonPrefixes' in response:
                    for prefix in response['CommonPrefixes']:
                        folder_name = prefix['Prefix'].rstrip('/').split('/')[-1]
                        folder_item = MDListItem(
                            MDListItemLeadingIcon(
                                icon="folder"
                            ),
                            MDListItemHeadlineText(
                                text=folder_name
                            )
                        )
                        folder_item.bind(on_release=lambda x, p=prefix['Prefix']: self._show_folder_contents(p))
                        files_list.add_widget(folder_item)
                
                # Then add files
                for item in response.get('Contents', []):
                    # Skip the folder itself
                    if item['Key'] == folder_path:
                        continue

                    file_name = item['Key'].split('/')[-1]
                    if not file_name:  # Skip empty names
                        continue
                        
                    file_item = MDListItem(
                        MDListItemLeadingIcon(
                            icon="file"
                        ),
                        MDListItemHeadlineText(
                            text=file_name
                        ),
                        MDListItemSupportingText(
                            text=f"Size: {self._format_size(item['Size'])}"
                        )
                    )

                    # Add actions menu for the file
                    actions_menu = [
                        ["Download", "download", lambda x: self._handle_download_file(item['Key'])]
                    ]

                    # Add delete option if user has push/full access
                    if access_level in ['push', 'full', 'both']:
                        actions_menu.append(
                            ["Delete", "delete", lambda x: self._handle_delete_file(item['Key'])]
                        )
                    
                    file_item.bind(on_release=lambda x, f=item['Key']: self._show_file_actions(f, actions_menu))
                    files_list.add_widget(file_item)
                
                if not response.get('Contents', []) and not response.get('CommonPrefixes', []):
                    empty_item = MDListItem(
                        MDListItemHeadlineText(
                            text="Folder is empty"
                        )
                    )
                    files_list.add_widget(empty_item)

            except Exception as e:
                Logger.error(f"Error listing folder contents: {str(e)}")
                error_item = MDListItem(
                    MDListItemHeadlineText(
                        text=f"Error: {str(e)}"
                    )
                )
                files_list.add_widget(error_item)
            
            scroll.add_widget(files_list)
            content.add_widget(scroll)
            
            # Create popup
            self.folder_contents_popup = Popup(
                title=f"Contents of {folder_path}",
                content=content,
                size_hint=(None, None),
                size=(dp(600), dp(500)),
                auto_dismiss=True
            )

            # Show popup
            self.folder_contents_popup.open()
            
        except Exception as e:
            Logger.error(f"Error showing folder contents: {str(e)}")
            Logger.error(traceback.format_exc())
            self.show_snackbar(f"Error: {str(e)}")
            
    def _format_size(self, size_bytes):
        """Format file size in human readable format"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"
        
    def _show_file_actions(self, file_path, actions):
        """Show actions menu for a file"""
        # Create content layout
        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(16),
            padding=dp(20),
            adaptive_height=True
        )
        
        # Add title
        title = MDLabel(
            text=f"File: {file_path.split('/')[-1]}",
            font_size="18sp",
            bold=True,
            size_hint_y=None,
            height=dp(40)
        )
        content.add_widget(title)
        
        # Create buttons layout
        buttons = MDBoxLayout(
            orientation='vertical',
            spacing=dp(8),
            adaptive_height=True
        )
        
        # Add action buttons
        for action in actions:
            button = MDButton(
                style="text",
                size_hint_y=None,
                height=dp(48),
                on_release=lambda x, a=action[2]: self._handle_file_action(a)
            )
            button.add_widget(MDButtonText(text=action[0]))
            buttons.add_widget(button)
            
        content.add_widget(buttons)
        
        # Create dialog with correct properties
        self.file_menu = Popup(
            title="File Actions",
            content=content,
            size_hint=(None, None),
            size=(dp(300), dp(200)),
            auto_dismiss=True
        )
        self.file_menu.open()

    def _handle_file_action(self, action_func):
        """Handle file action and dismiss menu"""
        # Close the menu
        if hasattr(self, 'file_menu'):
            self.file_menu.dismiss()
        # Execute the action
        action_func(None)

    def _handle_download_file(self, file_path):
        """Handle file download"""
        Logger.info(f"Downloading file: {file_path}")
        
        try:
            import boto3
            from core.aws.config import AWSConfig
            from tkinter import filedialog
            import tkinter as tk

            # Create temporary root window for file dialog
            root = tk.Tk()
            root.withdraw()  # Hide the root window
            
            # Get save location from user
            save_path = filedialog.asksaveasfilename(
                defaultextension="",
                initialfile=file_path.split('/')[-1]
            )
            import os
            if save_path:
                # Show loading message
                file_name = os.path.basename(file_path)
                self.show_snackbar(f"Downloading {file_name}...")
                
                # Get AWS config and create S3 client
                aws_config = AWSConfig.get_aws_config()
                s3_client = boto3.client('s3', **aws_config)
                bucket_name = "test-fm-user-bucket"
                
                # Download file
                s3_client.download_file(bucket_name, file_path, save_path)

                self.show_snackbar("Download completed successfully")

        except Exception as e:
            Logger.error(f"Error downloading file: {str(e)}")
            self.show_snackbar(f"Error downloading file: {str(e)}")
            
    def _handle_delete_file(self, file_path):
        """Delete file directly from S3 without confirmation"""
        try:
            # Get S3 client
            s3_client = self.s3_helper.s3_client

            # Delete file
            s3_client.delete_object(
                Bucket=self.s3_helper.bucket_name,
                Key=file_path
            )

            # Log the deletion
            if self.audit_logger:
                asyncio.create_task(
                    self.audit_logger.log_action(
                        "file_deleted",
                        {"file_path": file_path},
                        user_id=self.user_manager.current_user.get("user_id") if self.user_manager else None
                    )
                )

            # Refresh the storage tab
            self._refresh_tab_data("storage")

            # Show success message
            self.show_snackbar(f"File {file_path.split('/')[-1]} deleted successfully")

        except Exception as e:
            logger.error(f"Error deleting file: {str(e)}")
            self.show_snackbar(f"Failed to delete file: {str(e)}")

# Improved file upload handling for admin_interface.py

    def _show_upload_dialog(self, folder_path):
        """Show dialog to upload one or multiple files with progress tracking"""
        try:
            from tkinter import filedialog, Tk
            import os
            import threading
            
            # Create proper root window for file dialog
            root = Tk()
            root.withdraw()  # Hide the root window
            
            # Try multiple file selection method with explicit multiple selection mode
            # Some versions of Tkinter require this explicit flag
            file_paths = filedialog.askopenfilenames(
                parent=root,
                title="Select one or more files to upload",
                multiple=True,  # Explicitly specify multiple selection
                filetypes=[("All Files", "*.*")]  # Allow all file types
            )
            
            # Convert the file_paths tuple to a list if it's not already
            # Sometimes Tkinter returns a string with space-separated paths
            if isinstance(file_paths, str):
                file_paths = file_paths.split(" ")
            
            # Ensure we have a valid list of paths
            file_paths = list(file_paths)
            
            # Clean up the Tkinter root window
            root.destroy()
            
            if not file_paths or len(file_paths) == 0:
                return  # User cancelled file selection
                
            # Prepare file info list for the progress dialog
            files_info = []
            for file_path in file_paths:
                # Skip if path is empty or invalid
                if not file_path or not os.path.exists(file_path):
                    continue
                    
                file_size = os.path.getsize(file_path)
                file_name = os.path.basename(file_path)
                files_info.append({
                    'path': file_path,
                    'name': file_name,
                    'size': file_size
                })
            
            # If no valid files were selected, exit
            if not files_info:
                self.show_snackbar("No valid files selected")
                return
            
            # Display selected file count in a snackbar
            file_count = len(files_info)
            self.show_snackbar(f"Selected {file_count} file{'s' if file_count > 1 else ''} for upload")
                
            # Create progress dialog
            self.upload_progress = EnhancedUploadDialog(
                files_info=files_info,
                on_cancel=self._cancel_upload
            )

            # Create a flag for upload cancellation
            self.cancel_upload_flag = False
            
            # Create a thread for the upload to keep UI responsive
            def upload_thread():
                try:
                    self._upload_files(files_info, folder_path)
                except Exception as e:
                    import logging
                    logging.error(f"Upload thread error: {str(e)}")
                    # Update UI on main thread
                    from kivy.clock import Clock
                    Clock.schedule_once(lambda dt: self.show_snackbar(f"Upload error: {str(e)}"), 0)
            
            # Start upload thread
            self.upload_thread = threading.Thread(target=upload_thread)
            self.upload_thread.daemon = True
            self.upload_thread.start()
            
            # Show the progress dialog
            self.upload_progress.open()

        except Exception as e:
            import logging
            logging.error(f"Error in _show_upload_dialog: {str(e)}")
            self.show_snackbar(f"Error showing upload dialog: {str(e)}")
    
    def _upload_files(self, files_info, folder_path):
        """Upload one or multiple files with progress tracking"""
        try:
            import boto3
            import os
            import time
            from core.aws.config import AWSConfig
            from botocore.exceptions import ClientError
            from kivy.clock import Clock
            
            # Ensure folder path ends with /
            if not folder_path.endswith('/'):
                folder_path += '/'
                
            # Initialize boto3 client
            aws_config = AWSConfig.get_aws_config()
            s3_client = boto3.client('s3', **aws_config)
            bucket_name = "test-fm-user-bucket"  # Replace with your actual bucket name if needed
            
            # Show initial message
            file_count = len(files_info)
            message = f"Starting upload of {file_count} file{'s' if file_count > 1 else ''}..."
            Clock.schedule_once(lambda dt: self.show_snackbar(message), 0)
            
            # Upload each file
            for index, file_info in enumerate(files_info):
                # Check if upload was cancelled
                if hasattr(self, 'cancel_upload_flag') and self.cancel_upload_flag:
                    raise Exception("Upload cancelled by user")
                    
                local_path = file_info['path']
                file_name = file_info['name']
                file_size = file_info['size']
                
                # Construct S3 key
                s3_key = folder_path + file_name
                
                # Reset progress for this file
                bytes_transferred = 0
                
                def progress_callback(bytes_amount):
                    nonlocal bytes_transferred
                    bytes_transferred += bytes_amount
                    
                    # Check cancel flag
                    if hasattr(self, 'cancel_upload_flag') and self.cancel_upload_flag:
                        # Raise exception to abort
                        raise Exception("Upload cancelled by user")
                        
                    # Update progress on UI thread
                    Clock.schedule_once(
                        lambda dt: self._update_upload_progress(index, bytes_transferred, file_size) 
                        if hasattr(self, 'upload_progress') else None,
                        0
                    )
                
                # Upload the file
                s3_client.upload_file(
                    local_path,
                    bucket_name,
                    s3_key,
                    Callback=progress_callback
                )
                
                # Small delay between files
                time.sleep(0.1)
            
            # All files uploaded successfully
            success_message = f"Successfully uploaded {file_count} file{'s' if file_count > 1 else ''}"
            Clock.schedule_once(lambda dt: self.show_snackbar(success_message), 1)
            
            # Refresh folder contents after all uploads
            Clock.schedule_once(lambda dt: self._refresh_folder_contents(folder_path), 2)
            
        except Exception as e:
            import logging
            logging.error(f"Upload error: {str(e)}")
            
            if "Upload cancelled by user" in str(e):
                # Handle cancellation
                Clock.schedule_once(
                    lambda dt: self.show_snackbar("Upload cancelled"),
                    0
                )
            else:
                # Handle other errors
                Clock.schedule_once(
                    lambda dt: self.show_snackbar(f"Upload error: {str(e)}"),
                    0
                )
    
    def _update_upload_progress(self, file_index, bytes_transferred, file_size):
        """Update the upload progress dialog"""
        if hasattr(self, 'upload_progress') and self.upload_progress:
            self.upload_progress.update_progress(file_index, bytes_transferred, file_size)
    
    def _cancel_upload(self):
        """Cancel the upload process"""
        self.cancel_upload_flag = True
        # Dialog will close automatically from its cancel button handler
    
    def _refresh_folder_contents(self, folder_path):
        """Refresh folder contents after upload"""
        # Close any existing folder contents popup
        if hasattr(self, 'folder_contents_popup') and self.folder_contents_popup:
            self.folder_contents_popup.dismiss()
        
        # Show folder contents
        self._show_folder_contents(folder_path)
                
    def _show_create_subfolder_dialog(self, parent_folder):
        """Show dialog to create a subfolder"""
        # Dismiss any existing dialog
        if hasattr(self, 'subfolder_popup') and self.subfolder_popup:
            self.subfolder_popup.dismiss()
            self.subfolder_popup = None
            
        # Create content layout
        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(16),
            padding=[dp(24), dp(16), dp(24), dp(16)],
            md_bg_color=[1, 1, 1, 1],
            size_hint_y=None,
            height=dp(280)
        )
        
        # Add title
        title = MDLabel(
            text=f"Create Subfolder in {parent_folder}",
            font_size="22sp",
            bold=True,
            halign="center",
            size_hint_y=None,
            height=dp(50)
        )
        content.add_widget(title)
        
        # Add description
        description = MDLabel(
            text="Enter a name for the new subfolder.",
            theme_text_color="Secondary",
            font_size="14sp",
            halign="center",
            size_hint_y=None,
            height=dp(40)
        )
        content.add_widget(description)
        
        # Add input field
        self.subfolder_name_input = MDTextField(
            hint_text="Subfolder Name",
            mode="outlined",
            size_hint_y=None,
            height=dp(48)
        )
        content.add_widget(self.subfolder_name_input)

        # Add spacer
        content.add_widget(MDBoxLayout(size_hint_y=None, height=dp(10)))
        
        # Add buttons
        buttons = MDBoxLayout(
            orientation='horizontal',
            spacing=dp(16),
            size_hint_y=None,
            height=dp(50)
        )
        
        # Cancel button
        cancel_button = MDButton(
            style="text",
            on_release=lambda x: self.subfolder_popup.dismiss()
        )
        cancel_button.add_widget(MDButtonText(text="CANCEL"))
        buttons.add_widget(cancel_button)
        
        # Create button
        create_button = MDButton(
            style="filled",
            md_bg_color=[0.2, 0.7, 0.3, 1.0],
            on_release=lambda x: self._handle_create_subfolder(parent_folder)
        )
        create_button.add_widget(MDButtonText(text="CREATE"))
        buttons.add_widget(create_button)
        
        content.add_widget(buttons)

        # Create popup
        self.subfolder_popup = Popup(
            title="",
            content=content,
            size_hint=(None, None),
            size=(dp(400), dp(300)),
            auto_dismiss=False,
            background_color=[0.95, 0.95, 0.95, 1.0]
        )
        
        # Show popup
        self.subfolder_popup.open()
        Logger.info("Create subfolder dialog opened")
        
    def _handle_create_subfolder(self, parent_folder):
        """Handle subfolder creation"""
        if not hasattr(self, 'subfolder_name_input'):
            return
            
        subfolder_name = self.subfolder_name_input.text.strip()
        if not subfolder_name:
            self.show_snackbar("Please enter a subfolder name")
            return
            
        # Construct full path
        if not parent_folder.endswith('/'):
            parent_folder += '/'
        full_path = f"{parent_folder}{subfolder_name}/"
        
        # Create the subfolder
        self._create_folder_directly(full_path)
        
        # Close dialogs
        if hasattr(self, 'subfolder_dialog'):
            self.subfolder_dialog.dismiss()
        if hasattr(self, 'folder_contents_popup'):
            self.folder_contents_popup.dismiss()
            
        # Refresh folder contents
        self._show_folder_contents(parent_folder)

    def _filter_users(self, search_text):
        """Filter users based on search text"""
        if not hasattr(self, 'all_users'):
            self.all_users = self.users_list.copy()
            
        if not search_text:
            self.users_list = self.all_users.copy()
        else:
            search_text = search_text.lower()
            self.users_list = [
                user for user in self.all_users
                if search_text in user.get('username', '').lower() or 
                   search_text in user.get('email', '').lower()
            ]
        self._update_users_list()

    def _filter_by_role(self, role):
        """Filter users by role"""
        if not hasattr(self, 'all_users'):
            self.all_users = self.users_list.copy()
            
        if role == 'all':
            self.users_list = self.all_users.copy()
        else:
            self.users_list = [
                user for user in self.all_users
                if user.get('role', '').lower() == role.lower()
            ]
        self._update_users_list()

    def _filter_by_status(self, status):
        """Filter users by status"""
        if not hasattr(self, 'all_users'):
            self.all_users = self.users_list.copy()
            
        if status == 'all':
            self.users_list = self.all_users.copy()
        else:
            self.users_list = [
                user for user in self.all_users
                if user.get('status', '').lower() == status.lower()
            ]
        self._update_users_list()

    def _show_delete_user_dialog(self, user):
        """Show confirmation dialog before deleting a user"""
        try:
            Logger.info(f"Showing delete dialog for user {user['username']}")
            
            # Dismiss any existing dialog
            if hasattr(self, 'dialog') and self.dialog:
                self.dialog.dismiss()
                
            # Store user reference for deletion
            self.user_to_delete = user
            
            # Create the main content layout
            content = MDBoxLayout(
                orientation='vertical',
                spacing=dp(20),
                padding=dp(20),
                md_bg_color=[1, 1, 1, 1]  # White background
            )
            
            # Add title
            title = MDLabel(
                text=f"Delete User: {user['username']}",
                font_size="24sp",
                bold=True,
                size_hint_y=None,
                height=dp(40)
            )
            content.add_widget(title)
            
            # Warning message
            warning = MDLabel(
                text=f"Are you sure you want to delete this user?\nThis action cannot be undone.",
                theme_text_color="Error",
                size_hint_y=None,
                height=dp(60)
            )
            content.add_widget(warning)
            
            # Add spacer
            spacer = MDBoxLayout(size_hint_y=None, height=dp(20))
            content.add_widget(spacer)
            
            # Create buttons container
            buttons = MDBoxLayout(
                orientation='horizontal',
                spacing=dp(10),
                size_hint_y=None,
                height=dp(48),
                padding=[0, 0, 0, dp(10)],
                pos_hint={'right': 1}
            )
            
            # Cancel button
            cancel_btn = MDButton(
                style="text",
                size_hint_x=None,
                width=dp(120),
                on_release=lambda x: self.dialog.dismiss()
            )
            cancel_btn.add_widget(MDButtonText(text="CANCEL"))
            buttons.add_widget(cancel_btn)
            
            # Delete button
            delete_btn = MDButton(
                style="filled",
                size_hint_x=None,
                width=dp(120),
                md_bg_color=[0.8, 0.2, 0.2, 1.0],  # Red color for delete
                on_release=lambda x: self._confirm_delete_user()
            )
            delete_btn.add_widget(MDButtonText(text="DELETE"))
            buttons.add_widget(delete_btn)
            
            content.add_widget(buttons)
            
            # Create popup
            self.dialog = Popup(
                title="",
                content=content,
                size_hint=(None, None),
                size=(dp(400), dp(250)),
                background_color=[0.9, 0.9, 0.9, 1.0],  # Light gray background
                auto_dismiss=True
            )
            
            # Show dialog
            self.dialog.open()
            Logger.info("Delete user dialog opened successfully")
            
        except Exception as e:
            Logger.error(f"Error showing delete dialog: {str(e)}")
            Logger.error(traceback.format_exc())
            self.show_snackbar(f"Error: {str(e)}")

    def _confirm_delete_user(self):
        """Handle delete button press"""
        try:
            if hasattr(self, 'user_to_delete') and self.user_to_delete:
                username = self.user_to_delete.get('username')
                Logger.info(f"Confirming deletion of user: {username}")
                
                # Dismiss dialog
                if hasattr(self, 'dialog') and self.dialog:
                    self.dialog.dismiss()
                    self.dialog = None
                
                # Show loading message
                self.show_snackbar(f"Deleting user {username}...")
                
                # Get or create event loop
                app = MDApp.get_running_app()
                if not hasattr(app, 'loop'):
                    try:
                        app.loop = asyncio.get_event_loop()
                    except RuntimeError:
                        app.loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(app.loop)
                
                # Remove user from local list immediately for immediate UI feedback
                self.users_list = [u for u in self.users_list if u.get('username') != username]
                Clock.schedule_once(lambda dt: self._update_users_list(), 0)
                
                # Run deletion in background with callback
                future = asyncio.run_coroutine_threadsafe(
                    self._handle_delete_user(self.user_to_delete), 
                    app.loop
                )
                
                # Add callback to handle completion
                future.add_done_callback(self._handle_delete_completion)
            else:
                Logger.error("No user selected for deletion")
                self.show_snackbar("Error: No user selected for deletion")
        
        except Exception as e:
            Logger.error(f"Error in delete confirmation: {str(e)}")
            Logger.error(traceback.format_exc())
            self.show_snackbar(f"Error: {str(e)}")

    def _handle_delete_completion(self, future):
        """Handle completion of delete operation with improved UI refresh"""
        try:
            result = future.result()
            if result and result.get('success'):
                username = result.get('username')
                # Show success message
                self.show_snackbar(f"User {username} deleted successfully")
                
                # Remove user from local list immediately
                self.users_list = [u for u in self.users_list if u.get('username') != username]
                
                # Update the UI immediately
                Clock.schedule_once(lambda dt: self._update_users_list(), 0)
                
                # Force a complete reload of users from DynamoDB
                Clock.schedule_once(self._force_reload_users, 0.5)
                
                # Refresh all data to ensure consistency
                Clock.schedule_once(lambda dt: self.refresh_data(), 1.0)
                
                Logger.info(f"User {username} deleted successfully, UI refreshed")
            else:
                # Show error message
                error = result.get('error', 'Unknown error occurred')
                self.show_snackbar(f"Error deleting user: {error}")
                Logger.error(f"User deletion failed: {error}")
        except Exception as e:
            Logger.error(f"Error in delete completion handler: {str(e)}")
            Logger.error(traceback.format_exc())
            self.show_snackbar(f"Error: {str(e)}")

    def _force_reload_users(self, *args):
        """Force a complete reload of users from DynamoDB"""
        try:
            Logger.info("Forcing reload of users from DynamoDB")
            
            # Get the app instance
            app = MDApp.get_running_app()
            
            # Create or get event loop
            if not hasattr(app, 'loop'):
                try:
                    app.loop = asyncio.get_event_loop()
                except RuntimeError:
                    app.loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(app.loop)
            
            # Run the load operation in the event loop
            future = asyncio.run_coroutine_threadsafe(
                self._reload_users_from_dynamo(),
                app.loop
            )
            
            # Add callback to update UI when complete
            future.add_done_callback(lambda f: Clock.schedule_once(lambda dt: self._update_users_list(), 0))
            
        except Exception as e:
            Logger.error(f"Error in force reload users: {str(e)}")
            Logger.error(traceback.format_exc())

    async def _reload_users_from_dynamo(self):
        """Reload users directly from DynamoDB"""
        try:
            Logger.info("Reloading users from DynamoDB")
            
            if not hasattr(self, 'dynamo_manager') or not self.dynamo_manager:
                Logger.error("DynamoDB manager not available")
                return
            
            # Clear the users list
            self.users_list = []
            
            # Load users from DynamoDB
            try:
                # Use scan operation to get all users
                response = await asyncio.to_thread(
                    self.dynamo_manager.users_table.scan,
                    FilterExpression="sk = :sk",
                    ExpressionAttributeValues={':sk': '#USER'}
                )
                
                # Process user records
                users = response.get('Items', [])
                
                # Remove sensitive data
                for user in users:
                    user.pop('password_hash', None)
                
                # Update the users list
                self.users_list = users
                
                # Update the UI on the main thread
                Clock.schedule_once(lambda dt: self._update_users_list(), 0)
                
                # Update dashboard stats
                Clock.schedule_once(lambda dt: self._update_dashboard_stats(), 0.1)
                
                Logger.info(f"Reloaded {len(users)} users from DynamoDB")
            except Exception as e:
                Logger.error(f"Error loading users from DynamoDB: {str(e)}")
                Logger.error(traceback.format_exc())
        
        except Exception as e:
            Logger.error(f"Error in reload users from DynamoDB: {str(e)}")
            Logger.error(traceback.format_exc())

    async def _handle_delete_user(self, user):
        """Handle user deletion using DynamoManager's delete_user method"""
        try:
            username = user['username']
            Logger.info(f"Deleting user {username}")
            
            # Check if we have the necessary managers
            if not hasattr(self, 'dynamo_manager') or not self.dynamo_manager:
                raise Exception("DynamoDB manager not available")
            
            # Implement retry logic for more reliability
            max_retries = 3
            retry_count = 0
            last_error = None
            
            while retry_count < max_retries:
                try:
                    # Use DynamoManager's delete_user method
                    success = await self.dynamo_manager.delete_user(username)
                    
                    if success:
                        Logger.info(f"User {username} deleted successfully")
                        
                        # Return success
                        return {
                            'success': True, 
                            'username': username,
                            'message': f"User {username} deleted successfully"
                        }
                    else:
                        Logger.warning(f"Failed to delete user {username}")
                        retry_count += 1
                        await asyncio.sleep(0.5)
                        
                except Exception as e:
                    retry_count += 1
                    last_error = str(e)
                    Logger.warning(f"Delete attempt {retry_count} failed: {str(e)}")
                    
                    # Wait a bit before retrying
                    await asyncio.sleep(0.5)
            
            # If we get here, all retries failed
            Logger.error(f"All delete attempts failed after {max_retries} retries. Last error: {last_error}")
            return {
                'success': False, 
                'error': f"Failed after {max_retries} attempts: {last_error}"
            }
                
        except Exception as e:
            Logger.error(f"Error in _handle_delete_user: {str(e)}")
            Logger.error(traceback.format_exc())
            return {'success': False, 'error': str(e)}

    async def _async_update_user(self, username, updates):
        """Update user data asynchronously"""
        try:
            # First try using UserManager
            if self.user_manager:
                try:
                    result = await self.user_manager.update_user(username, updates)
                    if result.get('success'):
                        return result
                except Exception as e:
                    Logger.error(f"UserManager update failed: {str(e)}")
            
            # Fallback to direct DynamoDB update
            result = await self._update_user_directly_in_dynamo(username, updates)
            if result.get('success'):
                # Update local list
                for user in self.users_list:
                    if user['username'] == username:
                        user.update(updates)

                # Update UI
                Clock.schedule_once(lambda dt: self._update_users_list())
                return result

        except Exception as e:
            Logger.error(f"Error updating user: {str(e)}")
            return {'success': False, 'error': str(e)}