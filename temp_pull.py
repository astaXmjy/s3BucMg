import logging
import os
import asyncio
from typing import List, Dict, Set, Optional
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import StringProperty, ObjectProperty
from kivymd.uix.screen import MDScreen
from kivymd.uix.list import MDList, MDListItem, MDListItemLeadingIcon, MDListItemHeadlineText, MDListItemSupportingText
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDButton, MDButtonText
from kivymd.uix.textfield import MDTextField
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.snackbar import MDSnackbar
from kivymd.uix.label import MDLabel
from kivymd.app import MDApp
from models.permission import AccessLevel
import time
from kivy.logger import Logger

class PullFileManagerScreen(MDScreen):
    current_path = StringProperty('/')
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = 'pull_interface'
        self.dialog = None
        self.selected_items = set()
        self.accessible_folders = []
        self.files_in_current_path = []
        self.s3_helper = None
        self.folder_permission_manager = None
        print("PullFileManagerScreen initialized")  # Debug log
        
        # Initialize with app instance when it's available
        Clock.schedule_once(self._initialize_managers, 0)
    
    def _initialize_managers(self, dt):
        """Get references to managers from the app"""
        try:
            app = MDApp.get_running_app()
            if hasattr(app, 's3_helper'):
                self.s3_helper = app.s3_helper
                print("S3 helper initialized")  # Debug log
            else:
                print("Warning: s3_helper not found in app")  # Debug log
                
            if hasattr(app, 'folder_permission_manager'):
                self.folder_permission_manager = app.folder_permission_manager
                print("Folder permission manager initialized")  # Debug log
            else:
                print("Warning: folder_permission_manager not found in app")  # Debug log
            
            # Force a UI update
            self.refresh_view()
        except Exception as e:
            print(f"Error initializing managers: {str(e)}")
            self.show_snackbar(f"Error initializing: {str(e)}")
    
    def on_enter(self):
        """Called when screen enters the window"""
        try:
            Logger.info("PullFileManagerScreen.on_enter called")
            
            app = MDApp.get_running_app()
            self.current_user = app.current_user if hasattr(app, 'current_user') else None
            Logger.info(f"Current user: {self.current_user}")
            
            # Use threading to properly await the async method
            import threading

            def load_folders_thread():
                try:
                    # Get or create event loop for this thread
                    import asyncio
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                    
                    # Run the coroutine in the event loop
                    result = loop.run_until_complete(self._load_accessible_folders())
                    
                    # Update UI on the main thread
                    from kivy.clock import Clock
                    Clock.schedule_once(lambda dt: self._update_folder_list(), 0)
                    
                except Exception as e:
                    Logger.error(f"Error in folder loading thread: {str(e)}")
                    Logger.exception("Thread error")
                    
                    # Update UI on main thread with error
                    from kivy.clock import Clock
                    Clock.schedule_once(lambda dt: self.show_snackbar(f"Error loading folders: {str(e)}"), 0)
                    
                    # Fall back to mock folders
                    Clock.schedule_once(lambda dt: self._update_mock_folders(), 0)
            
            # Start folder loading in a separate thread
            Logger.info("Starting folder loading thread")
            thread = threading.Thread(target=load_folders_thread)
            thread.daemon = True
            thread.start()

        except Exception as e:
            Logger.error(f"Error in on_enter: {str(e)}")
            Logger.exception("on_enter error")
            self.show_snackbar(f"Error loading view: {str(e)}")
            
    
    async def _load_accessible_folders(self):
        """Load folders accessible to the current user with enhanced logging"""
        try:
            Logger.info("======= STARTING FOLDER ACCESS LOADING =======")

            # Get current user data
            user_data = self.current_user or {}
            username = user_data.get('username', 'unknown')
            Logger.info(f"Loading folders for user: {username}")
            Logger.info(f"User data: {user_data}")

            # Get folder access from user data
            folder_access = user_data.get('folder_access', [])
            Logger.info(f"Raw folder_access from user data: {folder_access}")
            
            # DIRECT S3 LISTING - Get all folders from the bucket
            import boto3
            from core.aws.config import AWSConfig
            
            # Get AWS config
            aws_config = AWSConfig.get_aws_config()
            bucket_name = "test-fm-user-bucket"  # Use your bucket name
            
            Logger.info(f"Listing ALL folders in S3 bucket: {bucket_name}")
            
            # Create S3 client
            s3_client = boto3.client('s3', **aws_config)
            
            # List all objects with delimiter to get root folders
            Logger.info("Listing root folders with delimiter")
            response = s3_client.list_objects_v2(
                Bucket=bucket_name,
                Delimiter='/'
            )
            
            all_folders = []
            
            # Process common prefixes (folders)
            if 'CommonPrefixes' in response:
                for prefix in response['CommonPrefixes']:
                    folder = prefix.get('Prefix')
                    all_folders.append(folder)
                    Logger.info(f"Found root-level folder: {folder}")
            
            # List all objects to infer folder structure
            Logger.info("Listing all objects to infer nested folders")
            paginator = s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=bucket_name)
            
            # Process all objects to infer folder structure
            for page in pages:
                for item in page.get('Contents', []):
                    key = item.get('Key', '')
                    
                    # If the key has slashes, it's in a folder
                    if '/' in key:
                        # Get the folder path
                        folder_path = key.rsplit('/', 1)[0] + '/'
                        if folder_path not in all_folders:
                            all_folders.append(folder_path)
                            Logger.info(f"Found nested folder: {folder_path}")

            # Include root folder
            if '/' not in all_folders:
                all_folders.append('/')
                Logger.info("Added root folder to list")

            Logger.info(f"ALL folders in S3 bucket: {all_folders}")
            
            # Determine accessible folders for this user
            if user_data.get('role') == 'admin':
                # Admin sees everything
                self.accessible_folders = all_folders
                Logger.info(f"Admin user has access to all folders: {self.accessible_folders}")
            else:
                # Regular user - use folder_access + default folders
                self.accessible_folders = []

                # Add explicitly granted folders from user profile
                for folder in folder_access:
                    if folder not in self.accessible_folders:
                        self.accessible_folders.append(folder)
                        Logger.info(f"Added granted folder: {folder}")
                
                # Add default folders based on access level
                access_level = user_data.get('access_level', 'pull')
                if access_level in ['pull', 'both', 'full']:
                    default_folders = ['public/', 'shared/']
                    for folder in default_folders:
                        if folder not in self.accessible_folders:
                            self.accessible_folders.append(folder)
                            Logger.info(f"Added default folder: {folder}")
                
                # Add user's personal folder
                user_folder = f"users/{username}/"
                if user_folder not in self.accessible_folders:
                    self.accessible_folders.append(user_folder)
                    Logger.info(f"Added user folder: {user_folder}")

                # Create any missing folders
                for folder in self.accessible_folders:
                    if folder not in all_folders:
                        try:
                            Logger.info(f"Creating missing folder: {folder}")
                            s3_client.put_object(
                                Bucket=bucket_name,
                                Key=folder,
                                Body=b''
                            )
                        except Exception as e:
                            Logger.error(f"Error creating folder {folder}: {str(e)}")
            
            # Sort folders for consistent display
            self.accessible_folders.sort()

            Logger.info(f"Final accessible folders: {self.accessible_folders}")
            Logger.info("======= COMPLETED FOLDER ACCESS LOADING =======")

            return True
            
        except Exception as e:
            Logger.error(f"Error loading accessible folders: {str(e)}")
            Logger.exception("Folder access error")

            # Fallback to defaults
            username = self.current_user.get('username', 'unknown') if self.current_user else 'unknown'
            self.accessible_folders = ['public/', 'shared/', f'users/{username}/']
            Logger.info(f"Using fallback folders: {self.accessible_folders}")

            return False

    def _update_folder_list(self):
        """Update folder list display with user's accessible folders and debugging"""
        try:
            Logger.info("======= UPDATING FOLDER LIST UI =======")
            if not hasattr(self.ids, 'folder_list'):
                Logger.error("folder_list not found in ids")
                return
            
            folder_list = self.ids.folder_list
            folder_list.clear_widgets()
            
            Logger.info(f"Number of accessible folders: {len(self.accessible_folders)}")
            Logger.info(f"Accessible folders to show in UI: {self.accessible_folders}")
            
            # Check if we actually have folders
            if not self.accessible_folders:
                Logger.warning("No accessible folders available to display")
                # Add a message indicating no folders
                item = MDListItem(
                    MDListItemHeadlineText(
                        text="No folders available"
                    )
                )
                folder_list.add_widget(item)
                Logger.info("Added 'No folders available' message to UI")
                return
                
            # Add root folder first if present
            if '/' in self.accessible_folders:
                root_item = MDListItem(
                    MDListItemLeadingIcon(
                        icon="folder-home"
                    ),
                    MDListItemHeadlineText(
                        text="Root"
                    ),
                    on_release=lambda x: self.change_folder('/')
                )
                folder_list.add_widget(root_item)
                Logger.info("Added root folder to UI")
            
            # Add other folders
            for folder in sorted(self.accessible_folders):
                # Skip root as it's already added
                if folder == '/':
                    continue
                    
                folder_name = folder.rstrip('/')
                if not folder_name:
                    continue
                
                # Get the display name (last part of the path)
                display_name = os.path.basename(folder_name) or folder_name
                
                # Create list item
                item = MDListItem(
                    MDListItemLeadingIcon(
                        icon="folder"
                    ),
                    MDListItemHeadlineText(
                        text=display_name
                    ),
                    MDListItemSupportingText(
                        text=folder  # Show full path as supporting text
                    ),
                    on_release=lambda x, f=folder: self.change_folder(f)
                )
                folder_list.add_widget(item)
                Logger.info(f"Added folder to UI: {folder} (display: {display_name})")
            
            Logger.info(f"Updated folder list with {len(folder_list.children)} items")
            Logger.info("======= COMPLETED FOLDER LIST UI UPDATE =======")

        except Exception as e:
            Logger.error(f"Error updating folder list: {str(e)}")
            Logger.exception("Folder list update error")
            self.show_snackbar(f"Error updating folder list: {str(e)}")

        
    def change_folder(self, folder_path):
        """Change to the selected folder if user has access"""
        # Check if user has access to this folder
        if not self._check_folder_access(folder_path):
            self.show_snackbar("You don't have access to this folder")
            return
        
        # Update current path
        self.current_path = folder_path if folder_path else '/'
        
        # Update path label
        if hasattr(self.ids, 'current_path_label'):
            self.ids.current_path_label.text = f"Current Path: {self.current_path}"
        
        # Clear selection
        self.selected_items.clear()

        # Load files (using sync version)
        self._load_files_sync()

    def _load_files_sync(self):
        """Synchronous version of file loading that doesn't use async/await"""
        try:
            Logger.info(f"Loading files for path: {self.current_path}")
            
            # First, check if user has access to this folder
            if not self._check_folder_access(self.current_path):
                Logger.warning(f"User does not have access to folder: {self.current_path}")
                self.show_snackbar("You don't have access to this folder")
                # Redirect to a folder they do have access to
                if self.accessible_folders:
                    self.current_path = self.accessible_folders[0]
                    Logger.info(f"Redirected to accessible folder: {self.current_path}")
                else:
                    # If no accessible folders, show empty
                    self._update_file_list([], [])
                    return
            
            # Get current user ID
            user_id = self.current_user.get('uuid') if self.current_user else None
            
            # Direct S3 access using boto3
            try:
                import boto3
                from core.aws.config import AWSConfig
                
                # Get AWS config
                aws_config = AWSConfig.get_aws_config()
                bucket_name = "test-fm-user-bucket"  # Use your bucket name
                
                Logger.info(f"Listing files in folder: {self.current_path}")
                
                # Create S3 client
                s3_client = boto3.client('s3', **aws_config)
                
                # Ensure folder path ends with /
                if self.current_path and not self.current_path.endswith('/'):
                    prefix = self.current_path + '/'
                else:
                    prefix = self.current_path
                
                # Get all objects with this prefix
                folders = []
                files = []
                
                # List all objects with delimiter to get subfolder structure
                response = s3_client.list_objects_v2(
                    Bucket=bucket_name,
                    Prefix=prefix,
                    Delimiter='/'
                )
                
                # Process common prefixes (subfolders)
                if 'CommonPrefixes' in response:
                    for common_prefix in response['CommonPrefixes']:
                        folder = common_prefix.get('Prefix')
                        if folder != prefix:  # Skip the current folder
                            folders.append(folder)
                            Logger.info(f"Found subfolder: {folder}")
                
                # Process contents (files)
                for content in response.get('Contents', []):
                    key = content.get('Key')
                    
                    # Skip folders (objects ending with /)
                    if key.endswith('/'):
                        continue
                    
                    # Skip the folder itself
                    if key == prefix:
                        continue
                    
                    # Add as file
                    file_info = {
                        'key': key,
                        'size': content.get('Size', 0),
                        'last_modified': content.get('LastModified', 0)
                    }
                    files.append(file_info)
                    Logger.info(f"Found file: {key}, size: {file_info['size']}")
                
                # Store current files
                self.files_in_current_path = files
                
                # Update UI
                self._update_file_list(folders, files)
                
            except Exception as s3_error:
                Logger.error(f"Error accessing S3: {str(s3_error)}")
                Logger.exception("S3 file listing error")
                
                # Fallback to mock data
                self._update_mock_files()
                
        except Exception as e:
            Logger.error(f"Error loading files: {str(e)}")
            Logger.exception("File loading error")

            # Fallback for demo
            self._update_mock_files()

    def navigate_to_subfolder(self, folder_path):
        """Navigate to subfolder if user has access"""
        # Check if user has access to this folder
        if not self._check_folder_access(folder_path):
            self.show_snackbar("You don't have access to this folder")
            return

        # Change to the folder
        self.change_folder(folder_path)

    def _check_folder_access(self, folder_path):
        """Check if current user has access to this folder"""
        # Admin has access to everything
        if self.current_user and self.current_user.get('role') == 'admin':
            return True

        # Check if the folder is in accessible_folders list
        if folder_path in self.accessible_folders:
            return True

        # Check if folder is a subfolder of an accessible folder
        for accessible_folder in self.accessible_folders:
            if folder_path.startswith(accessible_folder):
                return True
        
        # Special case for root folder
        if folder_path == '/' and any(folder.startswith('/') for folder in self.accessible_folders):
            return True

        return False
    def _load_files(self):
        """Load files in the current path"""
        app = MDApp.get_running_app()

        if hasattr(app, 's3_helper') and hasattr(app, 'loop'):
            asyncio.run_coroutine_threadsafe(self._async_load_files(), app.loop)
        else:
            # Demo mode
            self._update_mock_files()

    async def _load_files(self):
        """Load files in the current path if user has access"""
        try:
            Logger.info(f"Loading files for path: {self.current_path}")
            
            # First, check if user has access to this folder
            if not self._check_folder_access(self.current_path):
                Logger.warning(f"User does not have access to folder: {self.current_path}")
                self.show_snackbar("You don't have access to this folder")
                # Redirect to a folder they do have access to
                if self.accessible_folders:
                    self.current_path = self.accessible_folders[0]
                    Logger.info(f"Redirected to accessible folder: {self.current_path}")
                else:
                    # If no accessible folders, show empty
                    Clock.schedule_once(lambda dt: self._update_file_list([], []), 0)
                    return
            
            # Get current user ID
            user_id = self.current_user.get('uuid') if self.current_user else None

            # Get folders and files
            if self.s3_helper:
                folders, files = await self.s3_helper.list_folder_contents(
                    prefix=self.current_path, 
                    user_id=user_id
                )
                
                # Store current files
                self.files_in_current_path = files

                # Update UI
                Clock.schedule_once(lambda dt: self._update_file_list(folders, files))
            else:
                # Fallback for demo
                self._update_mock_files()
            
        except Exception as e:
            Logger.error(f"Error loading files: {str(e)}")
            Logger.exception("File loading error")
            # Fallback for demo
            self._update_mock_files()

    def _update_file_list(self, folders, files):
        """Update file list display with enhanced logging"""
        try:
            Logger.info(f"Updating file list with {len(folders)} folders and {len(files)} files")
            
            if not hasattr(self.ids, 'file_list'):
                Logger.error("file_list not found in ids")
                return
            
            file_list = self.ids.file_list
            file_list.clear_widgets()
            
            # Add parent folder option if not at root
            if self.current_path != '/':
                # Create list item for parent folder
                parent_item = MDListItem(
                    MDListItemLeadingIcon(
                        icon="folder-upload"
                    ),
                    MDListItemHeadlineText(
                        text=".."
                    ),
                    MDListItemSupportingText(
                        text="Parent Directory"
                    ),
                    on_release=lambda x: self.navigate_to_parent()
                )
                file_list.add_widget(parent_item)
                Logger.info("Added parent directory option")
            
            # Add folders
            for folder in sorted(folders):
                # Skip if folder is same as current path
                if folder == self.current_path:
                    continue
                    
                # Get folder name
                folder_name = os.path.basename(folder.rstrip('/'))
                if not folder_name:
                    continue
                    
                # Create list item for folder
                item = MDListItem(
                    MDListItemLeadingIcon(
                        icon="folder"
                    ),
                    MDListItemHeadlineText(
                        text=folder_name
                    ),
                    MDListItemSupportingText(
                        text=folder  # Show full path
                    ),
                    on_release=lambda x, f=folder: self.navigate_to_subfolder(f)
                )
                file_list.add_widget(item)
                Logger.info(f"Added folder to file list: {folder}")
            
            # Add files
            for file in sorted(files, key=lambda x: x.get('key', '')):
                file_name = os.path.basename(file.get('key', ''))
                file_size = self._format_size(file.get('size', 0))
                
                # Convert last_modified to string if it's a datetime object
                last_modified = file.get('last_modified', 0)
                if hasattr(last_modified, 'timestamp'):
                    # It's a datetime object from boto3
                    last_modified_str = last_modified.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    # It's already a timestamp or something else
                    try:
                        import time
                        last_modified_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_modified))
                    except:
                        last_modified_str = str(last_modified)
                
                # Create list item for file
                item = MDListItem(
                    MDListItemLeadingIcon(
                        icon="file"
                    ),
                    MDListItemHeadlineText(
                        text=file_name
                    ),
                    MDListItemSupportingText(
                        text=f"Size: {file_size} • Modified: {last_modified_str}"
                    ),
                    on_release=lambda x, f=file: self.toggle_selection(x, f)
                )
                # Store file data for later use
                item.file_data = file
                file_list.add_widget(item)
                Logger.info(f"Added file to list: {file_name}")
            
            # If no files or folders, show message
            if not folders and not files:
                empty_item = MDListItem(
                    MDListItemHeadlineText(
                        text="Folder is empty"
                    )
                )
                file_list.add_widget(empty_item)
                Logger.info("Added 'Folder is empty' message")
            
            Logger.info(f"Updated file list with {len(file_list.children)} items")

        except Exception as e:
            Logger.error(f"Error updating file list: {str(e)}")
            Logger.exception("File list update error")
            self.show_snackbar(f"Error updating file list: {str(e)}")
    
    def navigate_to_parent(self):
        """Navigate to parent folder"""
        # If at root, do nothing
        if self.current_path == '/':
            return
            
        # Get parent path
        if self.current_path.endswith('/'):
            parent_path = self.current_path[:-1]
        else:
            parent_path = self.current_path
            
        parent_path = os.path.dirname(parent_path)
        if not parent_path.endswith('/') and parent_path:
            parent_path += '/'
            
        # If empty, set to root
        if not parent_path:
            parent_path = '/'
            
        # Change folder
        self.change_folder(parent_path)
    
    def navigate_to_subfolder(self, folder_path):
        """Navigate to subfolder"""
        self.change_folder(folder_path)
    
    def toggle_selection(self, instance, file_data):
        """Toggle selection of a file"""
        if instance in self.selected_items:
            self.selected_items.remove(instance)
            instance.md_bg_color = [0, 0, 0, 0]  # Reset background
        else:
            self.selected_items.add(instance)
            instance.md_bg_color = [0.2, 0.6, 0.9, 0.2]  # Light blue highlight
    
    def select_all(self):
        """Select all files in the current view"""
        file_list = self.ids.file_list
        
        for item in file_list.children:
            # Only select files (not folders)
            if isinstance(item, MDListItem) and hasattr(item, 'file_data'):
                self.selected_items.add(item)
                item.md_bg_color = [0.2, 0.6, 0.9, 0.2]  # Light blue highlight
        
        self.show_snackbar(f"Selected {len(self.selected_items)} file(s)")
    
    def download_selected(self):
        """Download selected files"""
        if not self.selected_items:
            self.show_snackbar("No files selected")
            return
        
        # Create downloads directory
        downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(downloads_dir, exist_ok=True)
        
        # Download files
        app = MDApp.get_running_app()
        if hasattr(app, 's3_helper') and hasattr(app, 'loop'):
            self._show_progress()
            asyncio.run_coroutine_threadsafe(
                self._async_download_files(downloads_dir),
                app.loop
            )
        else:
            # Demo mode
            self._show_progress()
            
            # Simulate download progress
            total_items = len(self.selected_items)
            for i in range(total_items):
                progress = ((i + 1) / total_items) * 100
                Clock.schedule_once(lambda dt, p=progress: self._update_progress(p), (i + 1) * 0.5)
            
            # Complete
            Clock.schedule_once(lambda dt: self._hide_progress(), (total_items + 1) * 0.5)
            Clock.schedule_once(
                lambda dt: self.show_snackbar(f"Downloaded {total_items} file(s) to {downloads_dir}"),
                (total_items + 1) * 0.5
            )
    
    async def _async_download_files(self, downloads_dir):
        """Download files asynchronously"""
        try:
            # Get current user ID
            user_id = self.current_user.get('uuid') if self.current_user else None
            
            total_items = len(self.selected_items)
            downloaded_count = 0
            
            # Process each item
            for i, item in enumerate(list(self.selected_items)):
                try:
                    # Update progress
                    progress = (i / total_items) * 100
                    Clock.schedule_once(lambda dt: self._update_progress(progress))
                    
                    # Get file data
                    if hasattr(item, 'file_data'):
                        file_path = item.file_data.get('key')
                        file_name = os.path.basename(file_path)
                        local_path = os.path.join(downloads_dir, file_name)
                        
                        # Download file
                        await self.s3_helper.download_file(
                            file_path,
                            local_path,
                            user_id=user_id
                        )
                        
                        downloaded_count += 1
                        
                except Exception as item_error:
                    print(f"Error downloading item: {item_error}")
            
            # Complete progress
            Clock.schedule_once(lambda dt: self._update_progress(100))
            Clock.schedule_once(lambda dt: self._hide_progress(), 1)
            
            # Show result
            message = f"Downloaded {downloaded_count} of {total_items} file(s) to {downloads_dir}"
            Clock.schedule_once(lambda dt: self.show_snackbar(message))
            
            # Clear selection
            Clock.schedule_once(lambda dt: self._clear_selection())
            
        except Exception as e:
            print(f"Error during download: {e}")
            
            # Hide progress
            Clock.schedule_once(lambda dt: self._hide_progress())
            
            # Show error
            Clock.schedule_once(lambda dt: self.show_snackbar(f"Error: {str(e)}"))
    
    def _clear_selection(self):
        """Clear all selected items"""
        for item in self.selected_items:
            item.md_bg_color = [0, 0, 0, 0]  # Reset background
        
        self.selected_items.clear()
    
    def _show_progress(self):
        """Show progress bar"""
        progress_bar = self.ids.progress_bar
        progress_bar.value = 0
        progress_bar.opacity = 1
    
    def _update_progress(self, value):
        """Update progress bar value"""
        progress_bar = self.ids.progress_bar
        progress_bar.value = value
    
    def _hide_progress(self):
        """Hide progress bar"""
        progress_bar = self.ids.progress_bar
        progress_bar.opacity = 0
    
    def refresh_view(self):
        """Refresh the current view"""
        app = MDApp.get_running_app()
        
        if hasattr(app, 's3_helper') and hasattr(app, 'loop'):
            asyncio.run_coroutine_threadsafe(self._load_accessible_folders(), app.loop)
        else:
            # Demo mode
            self._update_mock_folders()
            self._update_mock_files()
    
    def _update_mock_folders(self):
        """Update with mock folders for testing/demo"""
        try:
            self.accessible_folders = [
                '/',
                'public/',
                'shared/',
                'users/demo_user/',
                'users/demo_user/documents/',
                'users/demo_user/images/'
            ]
            print("Updated with mock folders")  # Debug log
            self._update_folder_list()
        except Exception as e:
            print(f"Error updating mock folders: {str(e)}")
            self.show_snackbar("Error loading demo folders")
    
    def _update_mock_files(self):
        """Update with mock files for testing/demo"""
        try:
            mock_folders = []
            mock_files = []
            
            # Add mock data based on current path
            if self.current_path == '/':
                mock_folders = ['public/', 'shared/', 'users/']
                mock_files = [
                    {'key': 'README.md', 'size': 1024, 'last_modified': time.time()},
                    {'key': 'welcome.txt', 'size': 512, 'last_modified': time.time()}
                ]
            elif self.current_path == 'public/':
                mock_files = [
                    {'key': 'public/document1.pdf', 'size': 2048, 'last_modified': time.time()},
                    {'key': 'public/image1.jpg', 'size': 4096, 'last_modified': time.time()}
                ]
            elif self.current_path == 'shared/':
                mock_files = [
                    {'key': 'shared/project1.zip', 'size': 8192, 'last_modified': time.time()},
                    {'key': 'shared/presentation.pptx', 'size': 3072, 'last_modified': time.time()}
                ]
            elif self.current_path.startswith('users/demo_user'):
                if self.current_path == 'users/demo_user/':
                    mock_folders = ['users/demo_user/documents/', 'users/demo_user/images/']
                elif self.current_path == 'users/demo_user/documents/':
                    mock_files = [
                        {'key': 'users/demo_user/documents/doc1.docx', 'size': 2048, 'last_modified': time.time()},
                        {'key': 'users/demo_user/documents/notes.txt', 'size': 512, 'last_modified': time.time()}
                    ]
                elif self.current_path == 'users/demo_user/images/':
                    mock_files = [
                        {'key': 'users/demo_user/images/photo1.jpg', 'size': 4096, 'last_modified': time.time()},
                        {'key': 'users/demo_user/images/photo2.png', 'size': 5120, 'last_modified': time.time()}
                    ]
            
            print(f"Mock data for {self.current_path}: {len(mock_folders)} folders, {len(mock_files)} files")  # Debug log
            self._update_file_list(mock_folders, mock_files)
            
        except Exception as e:
            print(f"Error updating mock files: {str(e)}")
            self.show_snackbar("Error loading demo files")
    
    def show_snackbar(self, message):
        """Show snackbar message"""
        snackbar = MDSnackbar(
            MDLabel(
                text=message,
                theme_text_color="Custom",
                text_color="white"
            ),
            y=dp(24),
            pos_hint={"center_x": 0.5},
            size_hint_x=0.8,
            md_bg_color=[0.2, 0.6, 0.9, 1],
            duration=2
        )
        snackbar.open()
    
    @staticmethod
    def _format_size(size_bytes):
        """Format file size with appropriate units"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} PB"
    
    def logout(self):
        """Handle logout"""
        app = MDApp.get_running_app()
        if hasattr(app, 'logout') and callable(app.logout):
            Clock.schedule_once(lambda dt: app.logout(), 0)
        else:
            # Demo logout - just go to login screen
            app.root.current = 'login'