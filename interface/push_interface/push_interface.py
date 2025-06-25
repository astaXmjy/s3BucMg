import os
import asyncio
import time
import logging
import threading
import traceback
from typing import List, Dict, Set
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import StringProperty, ObjectProperty
from kivymd.uix.screen import MDScreen
from kivymd.uix.list import MDList, MDListItem, MDListItemLeadingIcon, MDListItemHeadlineText, MDListItemSupportingText
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDButton, MDButtonText
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.snackbar import MDSnackbar, MDSnackbarText
from kivymd.uix.label import MDLabel
from kivymd.app import MDApp
import boto3
from ..admin_interface.upload_progress_dialog import EnhancedUploadDialog

Logger = logging.getLogger(__name__)

class PushFileManagerScreen(MDScreen):
    current_path = StringProperty('/')
    username_text = StringProperty("User: Unknown")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = 'push_interface'
        self.dialog = None
        self.selected_items = set()
        self.accessible_folders = []
        self.files_in_current_path = []
        self.s3_helper = None
        self.current_user = None
        self.upload_being_cancelled = False
        Logger.info("PushFileManagerScreen initialized")
    
    def on_enter(self):
        """Called when screen enters the window"""
        try:
            Logger.info("Push interface entered, initializing...")
            app = MDApp.get_running_app()
            self.current_user = app.current_user if hasattr(app, 'current_user') else None
            Logger.info(f"Current user: {self.current_user}")

            # Update username display in the UI
            if self.current_user and self.current_user.get('username'):
                self.username_text = f"User: {self.current_user.get('username')}"
                Logger.info(f"Updated username display: {self.username_text}")
            
            # Initialize with app instance
            if hasattr(app, 's3_helper'):
                self.s3_helper = app.s3_helper
                Logger.info("S3 helper initialized")
            else:
                Logger.warning("S3 helper not available")

            # Load folders directly - don't use asyncio.run_coroutine_threadsafe
            self._load_folders_sync()
        except Exception as e:
            Logger.error(f"Error in on_enter: {str(e)}")
            self.show_snackbar(f"Error initializing: {str(e)}")
    
    def _load_folders_sync(self):
        """Load folders synchronously without asyncio to avoid coroutine warnings"""
        try:
            Logger.info("===== LOADING FOLDERS SYNC =====")

            # Get user data
            user_data = self.current_user or {}
            username = user_data.get('username', 'unknown')
            Logger.info(f"Loading folders for user: {username}")
            
            # Get folder access permissions based on push access
            folder_access = user_data.get('folder_access', [])
            Logger.info(f"User folder_access: {folder_access}")
            
            # Direct S3 folder listing using boto3
            try:
                from core.aws.config import AWSConfig
                
                # Get AWS config
                aws_config = AWSConfig.get_aws_config()
                bucket_name = "test-fm-user-bucket"
                
                Logger.info(f"Listing folders in bucket: {bucket_name}")
                
                # Create S3 client
                s3_client = boto3.client('s3', **aws_config)
                
                # List top-level folders
                response = s3_client.list_objects_v2(
                    Bucket=bucket_name,
                    Delimiter='/'
                )
                
                all_folders = []
                
                # Process common prefixes (folders at root level)
                if 'CommonPrefixes' in response:
                    for prefix in response['CommonPrefixes']:
                        folder = prefix.get('Prefix')
                        all_folders.append(folder)
                        Logger.info(f"Found top folder: {folder}")
                
                # List all objects to find nested folders
                all_response = s3_client.list_objects_v2(Bucket=bucket_name)

                if 'Contents' in all_response:
                    for obj in all_response['Contents']:
                        key = obj['Key']
                        if '/' in key:
                            # Extract folder path
                            folder_path = key.rsplit('/', 1)[0] + '/'
                            if folder_path not in all_folders:
                                all_folders.append(folder_path)
                                Logger.info(f"Found nested folder: {folder_path}")
                
                # Add root folder
                if '/' not in all_folders:
                    all_folders.append('/')
                
                Logger.info(f"All folders in bucket: {all_folders}")
                
                # Determine accessible folders - for push interface we need to focus on
                # folders the user can write to based on their access level
                if user_data.get('role') == 'admin':
                    # Admin has access to all folders
                    self.accessible_folders = all_folders
                    Logger.info("Admin user: Access to all folders granted")
                else:
                    # For push interface, we need to filter folders based on push/write access
                    access_level = user_data.get('access_level', 'pull')
                    
                    # Only allow access to folders if user has push/write permissions
                    if access_level in ['push', 'both', 'full']:
                        self.accessible_folders = folder_access.copy() if isinstance(folder_access, list) else []
                        Logger.info(f"Starting with explicit folder permissions: {self.accessible_folders}")
                        
                        # Add default push folders 
                        default_folders = ['uploads/', 'temp/']
                        for folder in default_folders:
                            if folder not in self.accessible_folders:
                                self.accessible_folders.append(folder)
                                Logger.info(f"Added default folder: {folder}")
                    else:
                        # User doesn't have push access
                        self.accessible_folders = []
                        Logger.warning(f"User {username} does not have push access")
                        self.show_snackbar("You don't have upload permission")
                    
                    # Add user's personal folder (always allowed for push)
                    if username and username != 'unknown':
                        user_folder = f"users/{username}/"
                        if user_folder not in self.accessible_folders:
                            self.accessible_folders.append(user_folder)
                            Logger.info(f"Added user folder: {user_folder}")
                    
                    # Create missing folders
                    for folder in self.accessible_folders:
                        if folder not in all_folders:
                            try:
                                Logger.info(f"Creating missing folder: {folder}")
                                s3_client.put_object(
                                    Bucket=bucket_name,
                                    Key=folder,
                                    Body=b''
                                )
                                Logger.info(f"Created folder: {folder}")
                            except Exception as folder_error:
                                Logger.error(f"Error creating folder: {str(folder_error)}")
                
                # Sort folders
                self.accessible_folders.sort()
                
                Logger.info(f"Final accessible folders: {self.accessible_folders}")
                
            except Exception as s3_error:
                Logger.error(f"S3 error: {str(s3_error)}")
                # Fallback to default folders
                access_level = user_data.get('access_level', 'pull')
                
                if access_level in ['push', 'both', 'full']:
                    self.accessible_folders = ['uploads/', 'temp/']
                    if username and username != 'unknown':
                        self.accessible_folders.append(f"users/{username}/")
                    Logger.info(f"Using fallback folders: {self.accessible_folders}")
                else:
                    self.accessible_folders = []
                    Logger.warning(f"User {username} does not have push access")
                    self.show_snackbar("You don't have upload permission")
            
            # Update UI
            self._update_folder_list()
            
            # Load files
            self._load_files_sync()
            
            Logger.info("===== FOLDERS LOADED SUCCESSFULLY =====")
            
        except Exception as e:
            Logger.error(f"Error loading folders: {str(e)}")
            # Default folders as fallback - for push we need write permission folders
            self.accessible_folders = ['uploads/', 'temp/']
            self._update_folder_list()
    
    def _load_files_sync(self):
        """Load files in current path synchronously"""
        try:
            Logger.info(f"Loading files for path: {self.current_path}")
            
            # Check if user has access to this folder
            has_access = False
            
            # Admin has access to everything
            if self.current_user and self.current_user.get('role') == 'admin':
                has_access = True
            # Direct folder match
            elif self.current_path in self.accessible_folders:
                has_access = True
            # Subfolder of an accessible folder
            else:
                for folder in self.accessible_folders:
                    if self.current_path.startswith(folder) and folder != '/':
                        has_access = True
                        break
            
            if not has_access:
                Logger.warning(f"User does not have access to folder: {self.current_path}")
                self.show_snackbar("You don't have upload access to this folder")
                # Redirect to an accessible folder
                if self.accessible_folders:
                    self.current_path = self.accessible_folders[0]
                    Logger.info(f"Redirected to: {self.current_path}")
                
                # Try again with new path
                Clock.schedule_once(lambda dt: self._load_files_sync(), 0.1)
                return
            
            # Direct S3 folder listing
            try:
                from core.aws.config import AWSConfig
                
                # Get AWS config
                aws_config = AWSConfig.get_aws_config()
                bucket_name = "test-fm-user-bucket"
                
                # Create S3 client
                s3_client = boto3.client('s3', **aws_config)
                
                # List objects in current path
                Logger.info(f"Listing objects in: {self.current_path}")
                
                # Ensure path ends with / if not root
                prefix = self.current_path
                if prefix != '/' and not prefix.endswith('/'):
                    prefix += '/'
                
                # Use empty prefix for root
                if prefix == '/':
                    prefix = ''
                
                # Get folders (common prefixes)
                folders = []
                folder_response = s3_client.list_objects_v2(
                    Bucket=bucket_name,
                    Prefix=prefix,
                    Delimiter='/'
                )
                
                if 'CommonPrefixes' in folder_response:
                    for common_prefix in folder_response['CommonPrefixes']:
                        prefix_path = common_prefix['Prefix']
                        # Skip current folder
                        if prefix_path != prefix:
                            folders.append(prefix_path)
                            Logger.info(f"Found subfolder: {prefix_path}")
                
                # Get files (not ending in /)
                files = []
                if 'Contents' in folder_response:
                    for item in folder_response['Contents']:
                        key = item['Key']
                        # Skip if this is the folder itself or ends with /
                        if key != prefix and not key.endswith('/'):
                            files.append({
                                'key': key,
                                'size': item['Size'],
                                'last_modified': item['LastModified'].timestamp()
                            })
                            Logger.info(f"Found file: {key}, size: {item['Size']}")
                
                # Update UI
                self._update_file_list(folders, files)
                
            except Exception as s3_error:
                Logger.error(f"S3 file listing error: {str(s3_error)}")
                # Use mock data as fallback
                self._update_mock_files()
            
        except Exception as e:
            Logger.error(f"Error loading files: {str(e)}")
            # Use mock data as fallback
            self._update_mock_files()
    
    def _update_folder_list(self):
        """Update folder list display"""
        try:
            if not hasattr(self.ids, 'folder_list'):
                Logger.warning("folder_list not found in ids")
                return
            
            folder_list = self.ids.folder_list
            folder_list.clear_widgets()
            
            Logger.info(f"Updating folder list with {len(self.accessible_folders)} folders")
            
            # If no folders, show a message
            if not self.accessible_folders:
                item = MDListItem(
                    MDListItemHeadlineText(
                        text="No folders available"
                    )
                )
                folder_list.add_widget(item)
                Logger.info("Added 'No folders available' message")
                return
            
            # Add root folder first if present and user has permission
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
                Logger.info("Added root folder to list")
            
            # Add other folders
            for folder in sorted(self.accessible_folders):
                # Skip root folder as it's already added
                if folder == '/':
                    continue
                    
                folder_name = folder.rstrip('/')
                if not folder_name:
                    continue
                
                # Get display name (last part of path)
                parts = folder_name.split('/')
                display_name = parts[-1] if parts else folder_name
                
                # Create list item
                item = MDListItem(
                    MDListItemLeadingIcon(
                        icon="folder"
                    ),
                    MDListItemHeadlineText(
                        text=display_name
                    ),
                    MDListItemSupportingText(
                        text=folder
                    ),
                    on_release=lambda x, f=folder: self.change_folder(f)
                )
                folder_list.add_widget(item)
                Logger.info(f"Added folder to list: {folder} (display: {display_name})")
            
            Logger.info(f"Updated folder list with {len(folder_list.children)} items")
            
            # Update current path label
            if hasattr(self.ids, 'current_path_label'):
                self.ids.current_path_label.text = f"Current Path: {self.current_path}"
            
        except Exception as e:
            Logger.error(f"Error updating folder list: {str(e)}")
            self.show_snackbar(f"Error updating folder list: {str(e)}")
    
    def _update_file_list(self, folders: List[str], files: List[Dict]):
        """Update file list display"""
        try:
            if not hasattr(self.ids, 'file_list'):
                Logger.warning("file_list not found in ids")
                return
            
            file_list = self.ids.file_list
            file_list.clear_widgets()
            
            Logger.info(f"Updating file list with {len(folders)} folders and {len(files)} files")
            
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
                    
                # Get folder name (last part of path)
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
                        text=folder
                    ),
                    on_release=lambda x, f=folder: self.navigate_to_subfolder(f)
                )
                file_list.add_widget(item)
                Logger.info(f"Added folder to file list: {folder}")
            
            # Add files
            for file in sorted(files, key=lambda x: x.get('key', '')):
                file_name = os.path.basename(file.get('key', ''))
                file_size = self._format_size(file.get('size', 0))
                last_modified = time.strftime(
                    '%Y-%m-%d %H:%M:%S', 
                    time.localtime(file.get('last_modified', 0))
                )
                
                # Create list item for file
                item = MDListItem(
                    MDListItemLeadingIcon(
                        icon="file"
                    ),
                    MDListItemHeadlineText(
                        text=file_name
                    ),
                    MDListItemSupportingText(
                        text=f"Size: {file_size} • Modified: {last_modified}"
                    )
                )
                # Store file data for later use
                item.file_data = file
                file_list.add_widget(item)
                Logger.info(f"Added file to list: {file_name}")
            
            # If no items were added, show empty message
            if not file_list.children:
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
            self.show_snackbar(f"Error updating file list: {str(e)}")
    
    def change_folder(self, folder_path):
        """Change to the selected folder"""
        try:
            Logger.info(f"Changing to folder: {folder_path}")
            
            # Update current path
            self.current_path = folder_path if folder_path else '/'
            
            # Update path label
            if hasattr(self.ids, 'current_path_label'):
                self.ids.current_path_label.text = f"Current Path: {self.current_path}"
            
            # Clear selection
            self.selected_items.clear()
            
            # Load files
            self._load_files_sync()
            
        except Exception as e:
            Logger.error(f"Error changing folder: {str(e)}")
            self.show_snackbar(f"Error: {str(e)}")
    
    def navigate_to_parent(self):
        """Navigate to parent folder"""
        try:
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
            
        except Exception as e:
            Logger.error(f"Error navigating to parent: {str(e)}")
            self.show_snackbar(f"Error: {str(e)}")
    
    def navigate_to_subfolder(self, folder_path):
        """Navigate to subfolder"""
        try:
            self.change_folder(folder_path)
        except Exception as e:
            Logger.error(f"Error navigating to subfolder: {str(e)}")
            self.show_snackbar(f"Error: {str(e)}")
    
    def toggle_selection(self, instance, file_data):
        """Toggle selection of a file"""
        try:
            Logger.info(f"Toggling selection for file: {file_data.get('key', 'unknown')}")
            
            # Check if item is already in selected_items
            if instance in self.selected_items:
                self.selected_items.remove(instance)
                instance.md_bg_color = [0, 0, 0, 0]  # Reset background
                Logger.info(f"Removed file from selection: {file_data.get('key')}")
            else:
                self.selected_items.add(instance)
                # More visually appealing highlight color - light blue with better opacity
                instance.md_bg_color = [0.3, 0.7, 1.0, 0.3]  # Brighter blue highlight
                Logger.info(f"Added file to selection: {file_data.get('key')}")
            
            # Update selection count in UI if available
            if hasattr(self.ids, 'selection_label'):
                self.ids.selection_label.text = f"Selected: {len(self.selected_items)}"
                
        except Exception as e:
            Logger.error(f"Error toggling selection: {str(e)}")
            Logger.exception("Selection toggle error")
    
    def _clear_selection(self):
        """Clear all selected items"""
        for item in self.selected_items:
            item.md_bg_color = [0, 0, 0, 0]  # Reset background
        
        self.selected_items.clear()
    
    def show_upload_dialog(self):
        """Show dialog for file upload using EnhancedUploadDialog"""
        try:
            # Check if user has push access
            access_level = self.current_user.get('access_level', 'pull') if self.current_user else 'pull'
            if access_level not in ['push', 'both', 'full'] and self.current_user.get('role') != 'admin':
                self.show_snackbar("You don't have upload permission")
                return
            
            # Check if current path is accessible for upload
            has_access = False
            
            # Admin has access to everything
            if self.current_user and self.current_user.get('role') == 'admin':
                has_access = True
            # Direct folder match
            elif self.current_path in self.accessible_folders:
                has_access = True
            # Subfolder of an accessible folder
            else:
                for folder in self.accessible_folders:
                    if self.current_path.startswith(folder) and folder != '/':
                        has_access = True
                        break
            
            if not has_access:
                self.show_snackbar("You don't have upload access to this folder")
                return
            
            # Use tkinter for file selection
            from tkinter import filedialog, Tk
            import os
            
            # Create and hide root window
            root = Tk()
            root.withdraw()
            
            # Show file dialog
            try:
                file_paths = filedialog.askopenfilenames(
                    title="Select files to upload",
                    multiple=True
                )
                
                # Convert tuple to list
                file_paths = list(file_paths)
                
                # Clean up Tk root
                root.destroy()
                
                if not file_paths:
                    Logger.info("No files selected for upload")
                    return
                
                # Create file info list
                files_info = []
                for file_path in file_paths:
                    if not os.path.isfile(file_path):
                        continue
                    
                    file_name = os.path.basename(file_path)
                    file_size = os.path.getsize(file_path)
                    
                    files_info.append({
                        'path': file_path,
                        'name': file_name,
                        'size': file_size
                    })
                
                if not files_info:
                    self.show_snackbar("No valid files selected")
                    return
                
                # Create and show enhanced upload dialog
                self.upload_progress_dialog = EnhancedUploadDialog(
                    files_info=files_info,
                    on_cancel=self._cancel_upload
                )
                self.upload_progress_dialog.open()
                
                # Start upload thread
                self._start_upload_thread(files_info)
                
            except Exception as e:
                Logger.error(f"Error selecting files: {str(e)}")
                self.show_snackbar(f"Error selecting files: {str(e)}")
            
        except Exception as e:
            Logger.error(f"Error showing upload dialog: {str(e)}")
            self.show_snackbar(f"Error: {str(e)}")
    
    def _start_upload_thread(self, files_info):
        """Start upload thread for selected files with enhanced progress tracking"""
        try:
            Logger.info(f"Starting upload thread for {len(files_info)} files")
            
            # Reset cancel flag
            self.upload_being_cancelled = False
            
            # Create and start upload thread
            import threading
            
            def upload_thread():
                try:
                    # Get AWS config
                    from core.aws.config import AWSConfig
                    import boto3
                    
                    aws_config = AWSConfig.get_aws_config()
                    bucket_name = "test-fm-user-bucket"
                    
                    # Create S3 client
                    s3_client = boto3.client('s3', **aws_config)
                    
                    total_files = len(files_info)
                    uploaded = 0
                    
                    for i, file_info in enumerate(files_info):
                        try:
                            # Check if upload was cancelled
                            if self.upload_being_cancelled:
                                Logger.info("Upload cancelled by user")
                                break
                            
                            # Get file info
                            file_path = file_info['path']
                            file_name = file_info['name']
                            file_size = file_info['size']
                            
                            # Construct S3 key - ensure current path ends with /
                            prefix = self.current_path
                            if prefix != '/' and not prefix.endswith('/'):
                                prefix += '/'
                            
                            # Use empty prefix for root
                            if prefix == '/':
                                prefix = ''
                            
                            s3_key = f"{prefix}{file_name}"
                            
                            Logger.info(f"Uploading {file_path} to {s3_key}")
                            
                            # Reset tracking variables for this file
                            bytes_transferred = 0
                            
                            def progress_callback(bytes_amount):
                                nonlocal bytes_transferred
                                
                                # Update bytes transferred
                                bytes_transferred += bytes_amount
                                
                                # Check cancel flag
                                if self.upload_being_cancelled:
                                    raise Exception("Upload cancelled by user")
                                
                                # Update progress dialog
                                Clock.schedule_once(
                                    lambda dt: self._update_upload_progress(i, bytes_transferred, file_size),
                                    0
                                )
                            
                            # Perform the upload
                            s3_client.upload_file(
                                Filename=file_path,
                                Bucket=bucket_name,
                                Key=s3_key,
                                Callback=progress_callback
                            )
                            
                            uploaded += 1
                            Logger.info(f"Successfully uploaded: {file_name}")
                            
                        except Exception as file_error:
                            if self.upload_being_cancelled:
                                Logger.info("Upload cancelled during file upload")
                                break
                            else:
                                Logger.error(f"Error uploading file {file_info['name']}: {str(file_error)}")
                    
                    # Refresh view regardless of cancel
                    Clock.schedule_once(lambda dt: self.refresh_view(), 1.5)
                    
                except Exception as thread_error:
                    Logger.error(f"Upload thread error: {str(thread_error)}")
                    Logger.exception("Upload thread error")
                    
                    # Show error if not cancelled
                    if not self.upload_being_cancelled:
                        Clock.schedule_once(
                            lambda dt: self.show_snackbar(f"Upload error: {str(thread_error)}"), 
                            0.1
                        )
            
            # Start upload thread
            thread = threading.Thread(target=upload_thread)
            thread.daemon = True
            thread.start()
            
        except Exception as e:
            Logger.error(f"Error starting upload thread: {str(e)}")
            self.show_snackbar(f"Error: {str(e)}")
    
    def _update_upload_progress(self, file_index, bytes_transferred, file_size):
        """Update the upload progress dialog"""
        if hasattr(self, 'upload_progress_dialog') and self.upload_progress_dialog:
            self.upload_progress_dialog.update_progress(file_index, bytes_transferred, file_size)
    
    def cancel_upload(self):
        """Cancel ongoing upload"""
        self.upload_being_cancelled = True
        self.show_snackbar("Cancelling upload...")
    
    def _cancel_upload(self):
        """Callback for the upload progress dialog's cancel button"""
        self.upload_being_cancelled = True
        self.show_snackbar("Cancelling upload...")
    
    def _show_progress(self):
        """Show progress bar - deprecated, now using EnhancedUploadDialog"""
        pass
    
    def _update_progress(self, value):
        """Update progress bar value - deprecated, now using EnhancedUploadDialog"""
        pass
    
    def _hide_progress(self):
        """Hide progress bar - deprecated, now using EnhancedUploadDialog"""
        pass
    
    def refresh_view(self):
        """Refresh the current view"""
        Logger.info("Refreshing view")
        self._load_folders_sync()
    
    def _update_mock_files(self):
        """Update with mock files for testing/demo"""
        try:
            mock_folders = []
            mock_files = []
            
            # Add mock data based on current path
            if self.current_path == '/':
                mock_folders = ['uploads/', 'temp/', 'users/']
                mock_files = [
                    {'key': 'README.md', 'size': 1024, 'last_modified': time.time()},
                    {'key': 'welcome.txt', 'size': 512, 'last_modified': time.time()}
                ]
            elif self.current_path == 'uploads/':
                mock_files = [
                    {'key': 'uploads/document1.pdf', 'size': 2048, 'last_modified': time.time()},
                    {'key': 'uploads/image1.jpg', 'size': 4096, 'last_modified': time.time()}
                ]
            elif self.current_path == 'temp/':
                mock_files = [
                    {'key': 'temp/temp_file1.zip', 'size': 8192, 'last_modified': time.time()}
                ]
            elif self.current_path.startswith('users'):
                # Extract username from path
                parts = self.current_path.strip('/').split('/')
                username = parts[1] if len(parts) > 1 else 'demo_user'
                
                if len(parts) <= 2:  # Just users/username/
                    mock_folders = [
                        f'users/{username}/documents/',
                        f'users/{username}/images/'
                    ]
                elif 'documents' in parts:
                    mock_files = [
                        {
                            'key': f'users/{username}/documents/doc1.docx', 
                            'size': 2048, 
                            'last_modified': time.time()
                        }
                    ]
                elif 'images' in parts:
                    mock_files = [
                        {
                            'key': f'users/{username}/images/photo1.jpg', 
                            'size': 4096, 
                            'last_modified': time.time()
                        }
                    ]
            
            Logger.info(f"Using mock data for {self.current_path}: {len(mock_folders)} folders, {len(mock_files)} files")
            self._update_file_list(mock_folders, mock_files)
            
        except Exception as e:
            Logger.error(f"Error updating mock files: {str(e)}")
            self.show_snackbar("Error loading demo files")
    
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
    
    @staticmethod
    def _format_size(size_bytes):
        """Format file size with appropriate units"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} PB"
    
    def logout(self):
        """Handle logout with the same implementation as admin_interface"""
        try:
            Logger.info("Logout method called")
            
            # Clear username display
            self.username_text = "User: Unknown"
            
            # Get app instance
            app = MDApp.get_running_app()
            if not hasattr(app, "root") or not app.root:
                Logger.error("App root not available for logout")
                return

            # Log the logout event if we have audit_logger and current user
            if hasattr(app, 'audit_logger') and app.audit_logger and hasattr(app, 'current_user') and app.current_user:
                try:
                    # Get current user ID
                    user_id = app.current_user.get('username', 'unknown_user')
                    
                    # Log the event with correct parameters using the event loop
                    if hasattr(app, 'loop') and app.loop:
                        asyncio.run_coroutine_threadsafe(
                            app.audit_logger.log_event(
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