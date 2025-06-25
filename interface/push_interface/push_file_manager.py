import os
import asyncio
import threading
from typing import Dict, List, Tuple, Optional, Set
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import StringProperty, ObjectProperty
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.list import (
    MDList,
    MDListItem,
    MDListItemHeadlineText,
    MDListItemSupportingText,
    MDListItemLeadingIcon
)
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDButton, MDButtonText, MDIconButton
from kivymd.uix.textfield import MDTextField
from kivymd.uix.snackbar import MDSnackbar
from kivymd.uix.label import MDLabel
from kivymd.uix.filemanager import MDFileManager
from kivymd.app import MDApp
import logging
from datetime import datetime

from core.aws.s3_helper import S3Helper
from core.auth.permission_manager import PermissionManager

logger = logging.getLogger(__name__)

class PushFileManagerScreen(MDScreen):
    current_path = StringProperty('/')
    current_user = ObjectProperty(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.s3_helper = S3Helper()
        self.permission_manager = PermissionManager()
        self.selected_items = set()
        self.context_menu = None
        self.file_manager = None
        self.dialog = None
        self.theme_cls = MDApp.get_running_app().theme_cls
        self.name = 'push_file_manager'
        self.accessible_folders = []
        self.breadcrumb_paths = ['/']
        logger.info("PushFileManagerScreen initialized")

    def on_enter(self):
        """Initialize view when screen is entered"""
        try:
            app = MDApp.get_running_app()
            self.current_user = app.current_user
            self.set_user(self.current_user)
            
            # Schedule folder loading
            Clock.schedule_once(
                lambda dt: asyncio.run_coroutine_threadsafe(
                    self._load_accessible_folders(), 
                    app.loop if hasattr(app, 'loop') else asyncio.get_event_loop()
                ), 0
            )
            
            logger.info("PushFileManagerScreen entered")
        except Exception as e:
            logger.error(f"Error initializing view: {str(e)}")
            self.show_error(f"Error initializing view: {str(e)}")

    async def _load_accessible_folders(self):
        """Load folders that the user has access to upload to"""
        try:
            user_data = self.current_user or {}
            
            # Get folders accessible to the user for uploading
            if user_data.get('role') == 'admin':
                # Admin has access to all folders
                folders, _ = await self.s3_helper.list_folder_contents(prefix='')
                self.accessible_folders = folders
            else:
                # Regular user - use folders from user data based on access level
                access_level = user_data.get('access_level', '')
                
                # Only allow upload if user has 'push' or 'both' access level
                if access_level in ['push', 'both', 'full']:
                    folder_access = user_data.get('folder_access', [])
                    
                    # Handle empty folder_access list
                    if not folder_access:
                        # Give access to user's own folder by default
                        username = user_data.get('username', '')
                        if username:
                            default_folder = f"users/{username}/"
                            folder_access.append(default_folder)
                    
                    self.accessible_folders = folder_access
                else:
                    # No upload access
                    self.accessible_folders = []
                    self.show_error("You don't have permission to upload files")
            
            # Update interface
            Clock.schedule_once(lambda dt: self.load_folders(), 0)
            Clock.schedule_once(lambda dt: self.load_files(), 0)
            
            logger.info(f"Loaded {len(self.accessible_folders)} upload-accessible folders for user")
            
        except Exception as e:
            logger.error(f"Error loading accessible folders: {str(e)}")
            self.show_error(f"Error loading folders: {str(e)}")

    def refresh_view(self):
        """Refresh the current view"""
        try:
            app = MDApp.get_running_app()
            Clock.schedule_once(
                lambda dt: asyncio.run_coroutine_threadsafe(
                    self._load_accessible_folders(), 
                    app.loop if hasattr(app, 'loop') else asyncio.get_event_loop()
                ), 0
            )
        except Exception as e:
            logger.error(f"Error refreshing view: {str(e)}")
            self.show_error(f"Error refreshing view: {str(e)}")

    def load_folders(self):
        """Load folders into the sidebar"""
        try:
            folder_list = self.ids.folder_list
            folder_list.clear_widgets()
            
            # Add accessible folders to sidebar
            for folder in self.accessible_folders:
                # Clean up folder name for display
                display_name = folder.rstrip('/')
                if display_name.startswith('/'):
                    display_name = display_name[1:]
                
                # Create list item for folder
                item = MDListItem(
                    MDListItemLeadingIcon(icon="folder"),
                    MDListItemHeadlineText(text=display_name or "Root"),
                    on_release=self.change_folder
                )
                folder_list.add_widget(item)
            
            logger.info(f"Loaded {len(self.accessible_folders)} folders in sidebar")
        except Exception as e:
            logger.error(f"Error loading folders: {str(e)}")
            self.show_error(f"Error loading folders: {str(e)}")

    async def load_files(self):
        """Load files in the current path"""
        try:
            file_list = self.ids.file_list
            file_list.clear_widgets()

            # Check if current path is accessible for uploading
            current_path = self.current_path

            # For admin, allow access to all paths
            if self.current_user and self.current_user.get('role') == 'admin':
                has_access = True
            else:
                # For regular users, check if current path is in accessible folders
                # or is a subfolder of an accessible folder
                has_access = any(
                    current_path == folder or current_path.startswith(folder)
                    for folder in self.accessible_folders
                )
            
            if not has_access:
                self.show_error("You don't have upload access to this folder")
                # Reset to root or first accessible folder
                self.current_path = self.accessible_folders[0] if self.accessible_folders else '/'
                await self.load_files()
                return
            
            # Load files and folders in current path
            folders, files = await self.s3_helper.list_folder_contents(prefix=current_path)
            
            # Add parent folder item if not at root
            if current_path != '/' and len(self.breadcrumb_paths) > 1:
                parent_item = MDListItem(
                    MDListItemLeadingIcon(icon="folder-upload"),
                    MDListItemHeadlineText(text=".."),
                    MDListItemSupportingText(text="Parent Directory"),
                    on_release=self.navigate_to_parent
                )
                file_list.add_widget(parent_item)
            
            # Add folder items
            for folder in folders:
                # Skip folders that are the same as current path (can happen with S3)
                if folder == current_path:
                    continue
                    
                # Get folder name from path
                folder_name = os.path.basename(folder.rstrip('/'))
                if not folder_name:
                    continue
                
                # Create list item for folder
                item = MDListItem(
                    MDListItemLeadingIcon(icon="folder"),
                    MDListItemHeadlineText(text=folder_name),
                    MDListItemSupportingText(text="Folder"),
                    on_release=self.folder_item_clicked
                )
                file_list.add_widget(item)
            
            # Add file items
            for file in files:
                # Get file details
                file_name = os.path.basename(file['key'])
                file_size = self.format_size(file['size'])
                last_modified = file['last_modified'].strftime('%Y-%m-%d %H:%M') if hasattr(file['last_modified'], 'strftime') else str(file['last_modified'])
                
                # Create list item for file
                item = MDListItem(
                    MDListItemLeadingIcon(icon="file"),
                    MDListItemHeadlineText(text=file_name),
                    MDListItemSupportingText(
                        text=f"{file_size} • {last_modified}"
                    ),
                    on_release=self.toggle_item_selection
                )
                # Store the full path in a custom attribute
                item.file_path = file['key']
                file_list.add_widget(item)
            
            logger.info(f"Loaded {len(folders)} folders and {len(files)} files in {current_path}")
            
        except Exception as e:
            logger.error(f"Error loading files: {str(e)}")
            self.show_error(f"Error loading files: {str(e)}")

    def change_folder(self, instance):
        """Change to selected folder from sidebar"""
        try:
            # Get folder path from list item text
            folder_name = instance.ids.text_container.children[0].text
            
            # Handle "Root" folder
            if folder_name == "Root":
                folder_path = "/"
            else:
                # Find the actual folder path from accessible_folders
                matching_folders = [f for f in self.accessible_folders if f.endswith(f"{folder_name}/") or f == folder_name]
                folder_path = matching_folders[0] if matching_folders else f"{folder_name}/"
            
            # Update current path and breadcrumbs
            self.current_path = folder_path
            self.breadcrumb_paths = ['/']
            if folder_path != '/':
                self.breadcrumb_paths.append(folder_path)
            
            # Reset selection
            self.clear_selection()
            
            # Load files in new path
            app = MDApp.get_running_app()
            Clock.schedule_once(
                lambda dt: asyncio.run_coroutine_threadsafe(
                    self.load_files(), 
                    app.loop if hasattr(app, 'loop') else asyncio.get_event_loop()
                ), 0
            )
            
            logger.info(f"Changed folder to {folder_path}")
        except Exception as e:
            logger.error(f"Error changing folder: {str(e)}")
            self.show_error(f"Error changing folder: {str(e)}")

    def folder_item_clicked(self, instance):
        """Handle clicking on a folder in the file list"""
        try:
            # Get folder name from list item
            folder_name = instance.ids.text_container.children[1].text
            
            # Build new path
            if self.current_path.endswith('/'):
                new_path = f"{self.current_path}{folder_name}/"
            else:
                new_path = f"{self.current_path}/{folder_name}/"
            
            # Update current path and breadcrumbs
            self.current_path = new_path
            self.breadcrumb_paths.append(new_path)
            
            # Reset selection
            self.clear_selection()
            
            # Load files in new path
            app = MDApp.get_running_app()
            Clock.schedule_once(
                lambda dt: asyncio.run_coroutine_threadsafe(
                    self.load_files(), 
                    app.loop if hasattr(app, 'loop') else asyncio.get_event_loop()
                ), 0
            )
            
            logger.info(f"Navigated to folder {new_path}")
        except Exception as e:
            logger.error(f"Error navigating to folder: {str(e)}")
            self.show_error(f"Error navigating to folder: {str(e)}")

    def navigate_to_parent(self, instance):
        """Navigate to parent folder"""
        try:
            if len(self.breadcrumb_paths) > 1:
                # Remove current path from breadcrumbs
                self.breadcrumb_paths.pop()
                # Set current path to last item in breadcrumbs
                self.current_path = self.breadcrumb_paths[-1]
                
                # Reset selection
                self.clear_selection()
                
                # Load files in parent path
                app = MDApp.get_running_app()
                Clock.schedule_once(
                    lambda dt: asyncio.run_coroutine_threadsafe(
                        self.load_files(), 
                        app.loop if hasattr(app, 'loop') else asyncio.get_event_loop()
                    ), 0
                )
                
                logger.info(f"Navigated to parent folder {self.current_path}")
        except Exception as e:
            logger.error(f"Error navigating to parent: {str(e)}")
            self.show_error(f"Error navigating to parent: {str(e)}")

    def toggle_item_selection(self, instance):
        """Toggle item selection for file operations"""
        try:
            if instance in self.selected_items:
                self.selected_items.remove(instance)
                instance.md_bg_color = self.theme_cls.bg_normal
            else:
                self.selected_items.add(instance)
                instance.md_bg_color = [*self.theme_cls.primary_color[:3], 0.1]
                
            logger.debug(f"Selected {len(self.selected_items)} items")
        except Exception as e:
            logger.error(f"Error toggling selection: {str(e)}")
            self.show_error(f"Error selecting item: {str(e)}")

    def clear_selection(self):
        """Clear all selected items"""
        try:
            for item in self.selected_items.copy():
                if hasattr(item, 'md_bg_color'):
                    item.md_bg_color = self.theme_cls.bg_normal
            self.selected_items.clear()
            logger.debug("Cleared all selections")
        except Exception as e:
            logger.error(f"Error clearing selection: {str(e)}")
            self.show_error(f"Error clearing selection: {str(e)}")

    def show_upload_dialog(self):
        """Show file upload dialog"""
        try:
            # Check if current path is accessible for upload
            if not self._check_upload_permission():
                self.show_error("You don't have permission to upload to this folder")
                return
                
            # Create file manager if needed
            if not self.file_manager:
                self.file_manager = MDFileManager(
                    exit_manager=self.exit_file_manager,
                    select_path=self.select_file_for_upload,
                    preview=True
                )
                
            # Show file manager starting at home directory
            self.file_manager.show(os.path.expanduser('~'))
            
        except Exception as e:
            logger.error(f"Error showing upload dialog: {str(e)}")
            self.show_error(f"Error showing upload dialog: {str(e)}")

    def exit_file_manager(self, *args):
        """Close file manager"""
        try:
            self.file_manager.close()
        except Exception as e:
            logger.error(f"Error closing file manager: {str(e)}")

    def select_file_for_upload(self, path):
        """Handle file selection for upload"""
        try:
            self.file_manager.close()
            
            # Check if path is a file
            if not os.path.isfile(path):
                self.show_error("Please select a file for upload")
                return
                
            # Start upload process
            app = MDApp.get_running_app()
            Clock.schedule_once(
                lambda dt: asyncio.run_coroutine_threadsafe(
                    self._async_upload_file(path), 
                    app.loop if hasattr(app, 'loop') else asyncio.get_event_loop()
                ), 0
            )
            
        except Exception as e:
            logger.error(f"Error selecting file: {str(e)}")
            self.show_error(f"Error selecting file: {str(e)}")

    def _check_upload_permission(self):
        """Check if user has permission to upload to current path"""
        user_data = self.current_user or {}
        
        # Admin has all permissions
        if user_data.get('role') == 'admin':
            return True
            
        # Check access level
        access_level = user_data.get('access_level', '')
        if access_level not in ['push', 'both', 'full']:
            return False
            
        # Check folder access
        current_path = self.current_path
        return any(
            current_path == folder or current_path.startswith(folder)
            for folder in self.accessible_folders
        )

    async def _async_upload_file(self, local_path):
        """Upload file asynchronously"""
        try:
            # Update progress bar
            progress_bar = self.ids.upload_progress
            progress_bar.value = 0
            progress_bar.opacity = 1
            
            # Get file name
            file_name = os.path.basename(local_path)
            
            # Build S3 path
            if self.current_path.endswith('/'):
                s3_path = f"{self.current_path}{file_name}"
            else:
                s3_path = f"{self.current_path}/{file_name}"
            
            # Create file object
            with open(local_path, 'rb') as file_obj:
                # Perform upload with progress callback
                await self.s3_helper.upload_file(
                    file_obj,
                    s3_path,
                    user_id=self.current_user.get('uuid') if self.current_user else None,
                    callback=lambda transferred, total: self._update_upload_progress(
                        progress_bar, transferred, total
                    )
                )
            
            # Update UI
            progress_bar.value = 100
            self.show_success(f"Successfully uploaded {file_name}")
            
            # Refresh file list
            await self.load_files()
            
            # Hide progress bar after delay
            await asyncio.sleep(1)
            progress_bar.opacity = 0
            progress_bar.value = 0
            
        except Exception as e:
            logger.error(f"Upload error: {str(e)}")
            self.show_error(f"Upload failed: {str(e)}")
            if hasattr(self.ids, 'upload_progress'):
                self.ids.upload_progress.opacity = 0
                self.ids.upload_progress.value = 0

    def _update_upload_progress(self, progress_bar, transferred, total):
        """Update progress bar during file upload"""
        if total > 0:
            progress_bar.value = (transferred / total) * 100
            progress_bar.opacity = 1

    def show_new_folder_dialog(self):
        """Show dialog to create a new folder"""
        try:
            # Check if current path is accessible for upload
            if not self._check_upload_permission():
                self.show_error("You don't have permission to create folders here")
                return
                
            content = MDBoxLayout(
                orientation='vertical',
                spacing=dp(10),
                padding=dp(20),
                adaptive_height=True
            )
            
            folder_name = MDTextField(
                hint_text="Folder Name",
                helper_text="Enter new folder name",
                size_hint_x=1
            )
            content.add_widget(folder_name)
            
            self.dialog = MDDialog(
                title="Create New Folder",
                content_cls=content,
                buttons=[
                    MDButton(
                        style="text",
                        on_release=lambda x: self.dialog.dismiss()
                    ).add_widget(MDButtonText(text="CANCEL")),
                    MDButton(
                        style="filled",
                        on_release=lambda x: self._handle_create_folder(folder_name.text)
                    ).add_widget(MDButtonText(text="CREATE"))
                ]
            )
            self.dialog.open()
            
        except Exception as e:
            logger.error(f"Error showing folder dialog: {str(e)}")
            self.show_error(f"Error showing folder dialog: {str(e)}")

    def _handle_create_folder(self, folder_name):
        """Handle folder creation from dialog"""
        if not folder_name:
            self.show_error("Please enter a folder name")
            return
            
        # Remove any invalid characters
        folder_name = ''.join(c for c in folder_name if c.isalnum() or c in '_ -.')
        
        app = MDApp.get_running_app()
        Clock.schedule_once(
            lambda dt: asyncio.run_coroutine_threadsafe(
                self._async_create_folder(folder_name), 
                app.loop if hasattr(app, 'loop') else asyncio.get_event_loop()
            ), 0
        )
        
        # Close dialog
        self.dialog.dismiss()

    async def _async_create_folder(self, folder_name):
        """Create folder asynchronously"""
        try:
            # Build folder path
            if self.current_path.endswith('/'):
                folder_path = f"{self.current_path}{folder_name}/"
            else:
                folder_path = f"{self.current_path}/{folder_name}/"
            
            # Create folder
            success = await self.s3_helper.create_folder(
                folder_path,
                user_id=self.current_user.get('uuid') if self.current_user else None
            )
            
            if success:
                self.show_success(f"Created folder {folder_name}")
                # Refresh file list
                await self.load_files()
            else:
                self.show_error(f"Failed to create folder {folder_name}")
            
        except Exception as e:
            logger.error(f"Folder creation error: {str(e)}")
            self.show_error(f"Error creating folder: {str(e)}")

    def delete_selected(self):
        """Delete selected files and folders"""
        if not self.selected_items:
            self.show_error("No items selected")
            return
            
        # Check delete permission
        if not self._check_upload_permission():
            self.show_error("You don't have permission to delete from this folder")
            return
            
        # Confirm deletion
        content = MDLabel(
            text=f"Are you sure you want to delete {len(self.selected_items)} item(s)? This cannot be undone.",
            adaptive_height=True,
            padding=[dp(20), dp(20)]
        )
        
        self.dialog = MDDialog(
            title="Confirm Delete",
            content_cls=content,
            buttons=[
                MDButton(
                    style="text",
                    on_release=lambda x: self.dialog.dismiss()
                ).add_widget(MDButtonText(text="CANCEL")),
                MDButton(
                    style="filled",
                    theme_bg_color="Error",
                    on_release=lambda x: self._handle_delete_items(x)
                ).add_widget(MDButtonText(text="DELETE"))
            ]
        )
        self.dialog.open()

    def _handle_delete_items(self, *args):
        """Handle deletion after confirmation"""
        self.dialog.dismiss()
        
        app = MDApp.get_running_app()
        Clock.schedule_once(
            lambda dt: asyncio.run_coroutine_threadsafe(
                self._async_delete_items(), 
                app.loop if hasattr(app, 'loop') else asyncio.get_event_loop()
            ), 0
        )

    async def _async_delete_items(self):
        """Delete selected items asynchronously"""
        try:
            progress_bar = self.ids.upload_progress
            progress_bar.value = 0
            progress_bar.opacity = 1
            
            total_items = len(self.selected_items)
            deleted_items = 0
            
            for item in list(self.selected_items):
                try:
                    # Update progress
                    progress_bar.value = (deleted_items / total_items) * 100
                    
                    # Get item name and determine if folder or file
                    item_name = item.ids.text_container.children[1].text
                    is_folder = "folder" in item.ids.text_container.children[0].icon
                    
                    # Build item path
                    if hasattr(item, 'file_path'):
                        item_path = item.file_path
                    else:
                        if self.current_path.endswith('/'):
                            item_path = f"{self.current_path}{item_name}"
                        else:
                            item_path = f"{self.current_path}/{item_name}"
                        
                        # Add trailing slash for folders
                        if is_folder and not item_path.endswith('/'):
                            item_path += '/'
                    
                    # Delete item
                    if is_folder:
                        success = await self.s3_helper.delete_folder(
                            item_path,
                            user_id=self.current_user.get('uuid') if self.current_user else None
                        )
                    else:
                        success = await self.s3_helper.delete_file(
                            item_path,
                            user_id=self.current_user.get('uuid') if self.current_user else None
                        )
                    
                    if success:
                        deleted_items += 1
                    
                except Exception as item_error:
                    logger.error(f"Error deleting item {item_name}: {str(item_error)}")
            
            # Update UI
            progress_bar.value = 100
            await self.load_files()
            self.clear_selection()
            
            # Show result
            if deleted_items == total_items:
                self.show_success(f"Successfully deleted {deleted_items} item(s)")
            else:
                self.show_warning(f"Deleted {deleted_items} of {total_items} item(s)")
            
            # Hide progress bar after delay
            await asyncio.sleep(1)
            progress_bar.opacity = 0
            progress_bar.value = 0
            
        except Exception as e:
            logger.error(f"Delete operation error: {str(e)}")
            self.show_error(f"Error deleting items: {str(e)}")
            if hasattr(self.ids, 'upload_progress'):
                self.ids.upload_progress.opacity = 0
                self.ids.upload_progress.value = 0

    def filter_files(self, search_text):
        """Filter files based on search text"""
        try:
            if not hasattr(self.ids, 'file_list'):
                return
                
            file_list = self.ids.file_list
            if not search_text:
                # Reset visibility
                for item in file_list.children:
                    if isinstance(item, MDListItem):
                        item.opacity = 1
                return
            
            # Filter items
            for item in file_list.children:
                if isinstance(item, MDListItem) and hasattr(item.ids, 'text_container'):
                    # Get item text from headline (may be index 0 or 1 depending on structure)
                    try:
                        item_text = item.ids.text_container.children[1].text
                    except:
                        try:
                            item_text = item.ids.text_container.children[0].text
                        except:
                            item_text = ""
                    
                    # Set visibility based on search
                    item.opacity = 1 if search_text.lower() in item_text.lower() else 0
                    
            logger.debug(f"Applied filter '{search_text}'")
        except Exception as e:
            logger.error(f"Error filtering files: {str(e)}")
            self.show_error(f"Error filtering files: {str(e)}")

    def perform_search(self):
        """Perform search using search field text"""
        try:
            search_text = self.ids.search_field.text
            self.filter_files(search_text)
        except Exception as e:
            logger.error(f"Error performing search: {str(e)}")
            self.show_error(f"Error performing search: {str(e)}")

    def show_context_menu(self):
        """Show context menu for additional options"""
        try:
            menu_items = [
                {
                    "text": "Refresh",
                    "icon": "refresh",
                    "on_release": lambda x: self.refresh_view()
                },
                {
                    "text": "Select All",
                    "icon": "select-all",
                    "on_release": lambda x: self.select_all_items()
                },
                {
                    "text": "Clear Selection",
                    "icon": "select-off",
                    "on_release": lambda x: self.clear_selection()
                },
                {
                    "text": "Show Folder Details",
                    "icon": "information",
                    "on_release": lambda x: self.show_folder_details()
                }
            ]
            
            # Create and open menu
            if not self.context_menu:
                self.context_menu = MDDropdownMenu(
                    caller=self.ids.right_action_items[1],
                    items=menu_items,
                    width_mult=3
                )
            self.context_menu.open()
        except Exception as e:
            logger.error(f"Error showing context menu: {str(e)}")
            self.show_error(f"Error showing menu: {str(e)}")

    def select_all_items(self):
        """Select all items in the current view"""
        try:
            file_list = self.ids.file_list
            for item in file_list.children:
                # Skip folder items and already selected items
                if (isinstance(item, MDListItem) and 
                    "folder-upload" not in (item.ids.text_container.children[0].icon if hasattr(item.ids.text_container.children[0], 'icon') else "") and
                    item not in self.selected_items):
                    self.toggle_item_selection(item)
                    
            logger.debug(f"Selected all applicable items: {len(self.selected_items)}")
        except Exception as e:
            logger.error(f"Error selecting all items: {str(e)}")
            self.show_error(f"Error selecting items: {str(e)}")

    def show_folder_details(self):
        """Show details about current folder"""
        app = MDApp.get_running_app()
        Clock.schedule_once(
            lambda dt: asyncio.run_coroutine_threadsafe(
                self._async_folder_details(), 
                app.loop if hasattr(app, 'loop') else asyncio.get_event_loop()
            ), 0
        )

    async def _async_folder_details(self):
        """Show folder details asynchronously"""
        try:
            # Get folder contents
            folders, files = await self.s3_helper.list_folder_contents(prefix=self.current_path)
            
            # Calculate stats
            total_folders = len(folders)
            total_files = len(files)
            total_size = sum(file.get('size', 0) for file in files)
            
            # Create details text
            details_text = (
                f"Path: {self.current_path}\n"
                f"Total Subfolders: {total_folders}\n"
                f"Total Files: {total_files}\n"
                f"Total Size: {self.format_size(total_size)}"
            )
            
            # Show dialog
            self.dialog = MDDialog(
                title="Folder Details",
                text=details_text,
                buttons=[
                    MDButton(
                        style="text",
                        on_release=lambda x: self.dialog.dismiss()
                    ).add_widget(MDButtonText(text="CLOSE"))
                ]
            )
            self.dialog.open()
            
        except Exception as e:
            logger.error(f"Error getting folder details: {str(e)}")
            self.show_error(f"Error getting folder details: {str(e)}")

    def set_user(self, user_data):
        """Set the current user and update UI"""
        try:
            self.current_user = user_data
            logger.info(f"Set user: {user_data.get('username') if user_data else None}")
        except Exception as e:
            logger.error(f"Error setting user: {str(e)}")
            self.show_error(f"Error setting user: {str(e)}")

    def show_error(self, message):
        """Show error message"""
        try:
            snackbar = MDSnackbar(
                MDLabel(
                    text=message,
                    theme_text_color="Custom",
                    text_color="white"
                ),
                y=dp(24),
                pos_hint={"center_x": 0.5},
                size_hint_x=0.8,
                md_bg_color=[0.8, 0.2, 0.2, 1],
                duration=3
            )
            snackbar.open()
            logger.error(message)
        except Exception as e:
            logger.error(f"Error showing error message: {str(e)}")
            print(f"Error: {message}")

    def show_success(self, message):
        """Show success message"""
        try:
            snackbar = MDSnackbar(
                MDLabel(
                    text=message,
                    theme_text_color="Custom",
                    text_color="white"
                ),
                y=dp(24),
                pos_hint={"center_x": 0.5},
                size_hint_x=0.8,
                md_bg_color=[0.2, 0.8, 0.2, 1],
                duration=2
            )
            snackbar.open()
            logger.info(message)
        except Exception as e:
            logger.error(f"Error showing success message: {str(e)}")
            print(f"Success: {message}")

    def show_warning(self, message):
        """Show warning message"""
        try:
            snackbar = MDSnackbar(
                MDLabel(
                    text=message,
                    theme_text_color="Custom",
                    text_color="white"
                ),
                y=dp(24),
                pos_hint={"center_x": 0.5},
                size_hint_x=0.8,
                md_bg_color=[0.9, 0.6, 0.0, 1],
                duration=2
            )
            snackbar.open()
            logger.warning(message)
        except Exception as e:
            logger.error(f"Error showing warning message: {str(e)}")
            print(f"Warning: {message}")

    @staticmethod
    def format_size(size_bytes):
        """Format file size with appropriate units"""
        try:
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if size_bytes < 1024:
                    return f"{size_bytes:.1f} {unit}"
                size_bytes /= 1024
            return f"{size_bytes:.1f} PB"
        except Exception as e:
            logger.error(f"Error formatting size: {str(e)}")
            return "Unknown size"