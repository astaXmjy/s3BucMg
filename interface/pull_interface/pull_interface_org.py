import os
from datetime import datetime
from typing import Dict, List, Optional, Set
from kivy.properties import StringProperty, ObjectProperty
from kivy.metrics import dp
from kivy.clock import Clock
from kivymd.uix.screen import MDScreen
from kivymd.uix.list import (
    MDList,
    MDListItem,
    MDListItemHeadlineText,
    MDListItemSupportingText,
    MDListItemLeadingIcon,
)
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDButton, MDButtonText, MDFabButton
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.snackbar import MDSnackbar
from kivymd.uix.label import MDLabel
from kivymd.uix.progressindicator import MDLinearProgressIndicator
from kivymd.app import MDApp
import asyncio
import logging
from core.aws.s3_helper import S3Helper
from core.auth.permission_manager import PermissionManager

logger = logging.getLogger(__name__)

class PullFileManagerScreen(MDScreen):
    current_path = StringProperty('/')
    current_user = ObjectProperty(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.theme_cls = MDApp.get_running_app().theme_cls
        self.s3_helper = S3Helper()
        self.permission_manager = PermissionManager()
        self.selected_items: Set[MDListItem] = set()
        self.dialog: Optional[MDDialog] = None
        self.context_menu: Optional[MDDropdownMenu] = None
        self.name = 'pull_interface'
        self.accessible_folders = []
        self.breadcrumb_paths = ['/']
        logger.info("PullFileManagerScreen initialized")

    def on_enter(self):
        """Called when the screen is entered"""
        try:
            app = MDApp.get_running_app()
            self.current_user = app.current_user
            
            # Initialize user session
            self.set_user(self.current_user)
            
            # Schedule folder loading
            Clock.schedule_once(
                lambda dt: asyncio.run_coroutine_threadsafe(
                    self._load_accessible_folders(), 
                    app.loop if hasattr(app, 'loop') else asyncio.get_event_loop()
                ), 0
            )
            
            logger.info("PullFileManagerScreen entered")
        except Exception as e:
            logger.error(f"Error initializing view: {str(e)}")
            self.show_error(f"Error initializing view: {str(e)}")

    async def _load_accessible_folders(self):
        """Load folders that the user has access to"""
        try:
            user_data = self.current_user or {}
            logger.info(f"Loading folders for user: {user_data.get('username')} with role: {user_data.get('role')} and access: {user_data.get('folder_access')}")
            
            # Get folders accessible to the user
            if user_data.get('role') == 'admin':
                # Admin has access to all folders
                folders, _ = await self.s3_helper.list_folder_contents(prefix='')
                self.accessible_folders = folders
                logger.info(f"Admin user - loaded all folders: {folders}")
            else:
                # Regular user - use folders from user data
                folder_access = user_data.get('folder_access', [])
                
                # Handle empty folder_access list
                if not folder_access:
                    # Default access based on access_level
                    access_level = user_data.get('access_level', 'pull')
                    username = user_data.get('username', '')
                    
                    # Default folders based on access level
                    if access_level == 'pull':
                        folder_access.extend(['public/', 'shared/'])
                    
                    # Give access to user's own folder by default
                    if username:
                        default_folder = f"users/{username}/"
                        folder_access.append(default_folder)
                
                self.accessible_folders = folder_access
                logger.info(f"Regular user - loaded accessible folders: {folder_access}")
            
            # Ensure root folder is always included
            if '/' not in self.accessible_folders:
                self.accessible_folders.insert(0, '/')
            
            # Update interface
            Clock.schedule_once(lambda dt: self.load_folders(), 0)
            
            # Load files in current path
            app = MDApp.get_running_app()
            Clock.schedule_once(
                lambda dt: asyncio.run_coroutine_threadsafe(
                    self.load_files(), 
                    app.loop if hasattr(app, 'loop') else asyncio.get_event_loop()
                ), 0
            )
            
            logger.info(f"Loaded {len(self.accessible_folders)} accessible folders for user")
            
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
            for folder in sorted(self.accessible_folders):
                # Clean up folder name for display
                display_name = folder.rstrip('/')
                if display_name.startswith('/'):
                    display_name = display_name[1:]
                
                # Create list item for folder
                item = MDListItem(
                    MDListItemLeadingIcon(
                        icon="folder"
                    ),
                    MDListItemHeadlineText(
                        text=display_name or "Root"
                    ),
                    on_release=lambda x, f=folder: self.change_folder(x, f)
                )
                item.folder_path = folder  # Store the actual folder path
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
            
            # Check if current path is accessible
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
                self.show_error("You don't have access to this folder")
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

    def change_folder(self, instance, folder_path=None):
        """Change to selected folder"""
        try:
            if folder_path is None:
                # Get folder path from list item text
                folder_name = instance.ids.text_container.children[0].text
                # Handle "Root" folder
                if folder_name == "Root":
                    folder_path = "/"
                else:
                    folder_path = getattr(instance, 'folder_path', f"{folder_name}/")
            
            logger.info(f"Changing to folder: {folder_path}")
            
            # Update current path and breadcrumbs
            self.current_path = folder_path
            self.ids.current_path_label.text = f"Current Path: {folder_path}"
            
            # Update breadcrumbs
            self.breadcrumb_paths = ['/']
            if folder_path != '/':
                self.breadcrumb_paths.append(folder_path)
            
            # Load files in new folder
            app = MDApp.get_running_app()
            Clock.schedule_once(
                lambda dt: asyncio.run_coroutine_threadsafe(
                    self.load_files(), 
                    app.loop if hasattr(app, 'loop') else asyncio.get_event_loop()
                ), 0
            )
            
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
        """Toggle item selection for download"""
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

    def download_selected(self):
        """Download selected files"""
        if not self.selected_items:
            self.show_error("No items selected")
            return

        # Create downloads directory
        downloads_dir = os.path.expanduser("~/Downloads/S3Downloads")
        os.makedirs(downloads_dir, exist_ok=True)
        
        # Start download process
        app = MDApp.get_running_app()
        Clock.schedule_once(
            lambda dt: asyncio.run_coroutine_threadsafe(
                self._async_download_files(downloads_dir), 
                app.loop if hasattr(app, 'loop') else asyncio.get_event_loop()
            ), 0
        )

    async def _async_download_files(self, downloads_dir):
        """Download files asynchronously"""
        try:
            # Configure progress indicator
            progress_bar = self.ids.download_progress
            progress_bar.value = 0
            progress_bar.opacity = 1
            
            # Track download progress
            total_files = len(self.selected_items)
            files_completed = 0
            
            for item in self.selected_items:
                # Get file name and path
                file_name = item.ids.text_container.children[1].text
                
                # Get full S3 path - either from stored path or build from current path
                if hasattr(item, 'file_path'):
                    s3_path = item.file_path
                else:
                    if self.current_path.endswith('/'):
                        s3_path = f"{self.current_path}{file_name}"
                    else:
                        s3_path = f"{self.current_path}/{file_name}"
                
                # Set local download path
                local_path = os.path.join(downloads_dir, file_name)
                
                try:
                    # Update progress for current file
                    progress_bar.value = (files_completed / total_files) * 100
                    
                    # Download file with progress callback
                    await self.s3_helper.download_file(
                        s3_path,
                        local_path,
                        user_id=self.current_user.get('uuid') if self.current_user else None,
                        callback=lambda transferred, total: self._update_file_progress(
                            progress_bar, transferred, total, files_completed, total_files
                        )
                    )
                    
                    files_completed += 1
                    
                except Exception as file_error:
                    logger.error(f"Error downloading {s3_path}: {str(file_error)}")
                    # Continue with next file
            
            # Complete progress bar
            progress_bar.value = 100
            
            # Show success message
            self.show_snackbar(f"Downloaded {files_completed} of {total_files} files to {downloads_dir}")
            
            # Clear selection
            self.clear_selection()
            
            # Hide progress bar after delay
            await asyncio.sleep(1)
            progress_bar.opacity = 0
            progress_bar.value = 0
            
        except Exception as e:
            logger.error(f"Download process error: {str(e)}")
            self.show_error(f"Download error: {str(e)}")
            progress_bar.opacity = 0
            progress_bar.value = 0

    def _update_file_progress(self, progress_bar, transferred, total, files_done, total_files):
        """Update progress bar during file download"""
        if total > 0:
            # Calculate overall progress
            file_progress = transferred / total
            total_progress = ((files_done + file_progress) / total_files) * 100
            progress_bar.value = total_progress

    def select_all_items(self):
        """Select all files in the current view"""
        try:
            file_list = self.ids.file_list
            for item in file_list.children:
                # Skip folder items and already selected items
                if (isinstance(item, MDListItem) and 
                    "folder" not in item.ids.text_container.children[0].icon and
                    item not in self.selected_items):
                    self.toggle_item_selection(item)
                    
            logger.debug(f"Selected all applicable items: {len(self.selected_items)}")
        except Exception as e:
            logger.error(f"Error selecting all items: {str(e)}")
            self.show_error(f"Error selecting items: {str(e)}")

    def clear_selection(self):
        """Clear all selected items"""
        try:
            for item in self.selected_items.copy():
                self.toggle_item_selection(item)
            self.selected_items.clear()
            logger.debug("Cleared all selections")
        except Exception as e:
            logger.error(f"Error clearing selection: {str(e)}")
            self.show_error(f"Error clearing selection: {str(e)}")

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
                    "text": "Show File Details",
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

    def show_snackbar(self, message):
        """Show information message"""
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
                md_bg_color=[0.2, 0.6, 0.9, 1],
                duration=2
            )
            snackbar.open()
            logger.info(message)
        except Exception as e:
            logger.error(f"Error showing snackbar: {str(e)}")
            print(f"Info: {message}")

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