import asyncio
import uuid
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.logger import Logger
from kivymd.uix.screen import MDScreen
from kivymd.uix.button import MDButton, MDButtonText, MDButtonIcon
from kivymd.uix.dialog import MDDialog
from kivymd.uix.list import (
    MDList,
    MDListItem, 
    MDListItemLeadingIcon, 
    MDListItemHeadlineText, 
    MDListItemSupportingText
)
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.snackbar import MDSnackbar
from kivymd.uix.textfield import MDTextField
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.app import MDApp

class AdminDashboard(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = 'admin_interface'
        self._init_managers()
        self._init_state()
        self.bind(size=self._on_resize)
        self.user_list = []
        self.bucket_stats = {}
        Logger.info("AdminDashboard initialized")

    def _init_managers(self):
        """Initialize all required managers"""
        app = MDApp.get_running_app()
        self.s3_helper = app.s3_helper
        self.user_manager = app.user_manager
        self.permission_manager = app.permission_manager
        self.db_manager = app.db_manager
        self.audit_logger = app.audit_logger

    def _init_state(self):
        """Initialize component state"""
        self.refresh_task = None
        self.dialog = None
        self.selected_items = set()
        self.account_menu = None
        self.current_folder = ""

    def on_pre_enter(self):
        """Called before screen is entered"""
        if not hasattr(MDApp.get_running_app(), 's3_helper'):
            Logger.error("s3_helper not initialized")
            return
            
        # Ensure all essential components are available
        if not self.s3_helper:
            self.s3_helper = MDApp.get_running_app().s3_helper

    def on_enter(self):
        print("Admin interface entered")
        print(f"Nav drawer exists: {hasattr(self.ids, 'nav_drawer')}")
        print(f"Available IDs: {self.ids.keys() if hasattr(self, 'ids') else 'No IDs'}")
        """Screen enter handler"""
        app = MDApp.get_running_app()
        if not hasattr(app, 'loop'):
            app.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(app.loop)
        
        # Make sure navigation drawer is initialized
        if hasattr(self.ids, 'nav_drawer'):
            self.ids.nav_drawer.set_state("close")

        # Schedule data loading
        Clock.schedule_once(
            lambda dt: asyncio.run_coroutine_threadsafe(
                self._initialize_data(), 
                app.loop
            )
        )

    def on_leave(self):
        """Screen leave handler"""
        if self.refresh_task:
            self.refresh_task.cancel()
            self.refresh_task = None

    async def _initialize_data(self):
        """Initialize dashboard data"""
        try:
            await asyncio.gather(
                self._load_users(),
                self._load_storage_stats(),
                self._load_activity_logs()
            )
            self._start_refresh_task()
            Logger.info("Admin dashboard data initialized")
        except Exception as e:
            Logger.error(f"Dashboard initialization error: {str(e)}")
            self.show_error("Failed to initialize dashboard")

    async def _load_users(self):
        """Load user data"""
        try:
            users = await self.user_manager.get_all_users()
            self.user_list = users
            Clock.schedule_once(lambda dt: self._update_users_display(users))
            Logger.info(f"Loaded {len(users)} users")
            return users
        except Exception as e:
            Logger.error(f"User loading error: {str(e)}")
            raise

    def _update_users_display(self, users):
        """Update users list display"""
        # Make sure users_list widget exists
        if not hasattr(self.ids, 'users_list'):
            Logger.error("users_list widget not found in AdminDashboard")
            return
            
        users_list = self.ids.users_list
        users_list.clear_widgets()
        
        for user in users:
            item = MDListItem(
                MDListItemLeadingIcon(
                    icon="account"
                ),
                MDListItemHeadlineText(
                    text=user.get('username', 'Unknown')
                ),
                MDListItemSupportingText(
                    text=f"{user.get('role', 'user')} • {user.get('access_level', 'unknown')}"
                ),
                on_release=lambda x, u=user: self._show_user_details(u)
            )
            users_list.add_widget(item)
            
        # Update active users count
        if hasattr(self.ids, 'active_users_label'):
            self.ids.active_users_label.text = str(len([u for u in users if u.get('status') == 'active']))

    async def _load_storage_stats(self):
        """Load storage statistics"""
        try:
            stats = await self.s3_helper.get_bucket_stats()
            self.bucket_stats = stats
            Clock.schedule_once(lambda dt: self._update_storage_display(stats))
            Logger.info(f"Loaded storage stats: {stats.get('total_size_gb', 0):.2f}GB used")
            return stats
        except Exception as e:
            Logger.error(f"Storage stats error: {str(e)}")
            raise

    def _update_storage_display(self, stats):
        """Update storage statistics display"""
        if hasattr(self.ids, 'storage_label'):
            self.ids.storage_label.text = f"{stats.get('total_size_gb', 0):.1f}GB / 50GB"
            
        if hasattr(self.ids, 'storage_progress'):
            self.ids.storage_progress.value = min(100, stats.get('usage_percentage', 0))
            
        if hasattr(self.ids, 'operations_label'):
            self.ids.operations_label.text = str(stats.get('total_files', 0))

    async def _load_activity_logs(self):
        """Load recent activity logs"""
        try:
            logs = await self.db_manager.get_audit_logs(limit=10)
            Clock.schedule_once(lambda dt: self._update_activity_list(logs))
            Logger.info(f"Loaded {len(logs)} activity logs")
            return logs
        except Exception as e:
            Logger.error(f"Activity log error: {str(e)}")
            raise

    def _update_activity_list(self, logs):
        """Update activity list display"""
        if not hasattr(self.ids, 'activity_list'):
            Logger.error("activity_list widget not found in AdminDashboard")
            return
            
        activity_list = self.ids.activity_list
        activity_list.clear_widgets()
        
        for log in logs:
            item = MDListItem(
                MDListItemLeadingIcon(
                    icon="information" if log.get('severity', '') == 'info' else "alert"
                ),
                MDListItemHeadlineText(
                    text=f"{log.get('action', 'Unknown')} - {log.get('user_id', 'System')}"
                ),
                MDListItemSupportingText(
                    text=log.get('timestamp', 'Unknown time')
                )
            )
            activity_list.add_widget(item)

    def show_add_user_dialog(self):
        """Show dialog for adding new user"""
        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(10),
            padding=dp(20),
            adaptive_height=True
        )

        username_field = MDTextField(
            hint_text="Username/Email",
            helper_text="Enter username or email",
            size_hint_x=1
        )
        content.add_widget(username_field)

        password_field = MDTextField(
            hint_text="Password",
            helper_text="Enter password",
            password=True,
            size_hint_x=1
        )
        content.add_widget(password_field)

        role_field = MDTextField(
            hint_text="Role",
            helper_text="user/admin/manager",
            size_hint_x=1,
            text="user"
        )
        content.add_widget(role_field)
        
        access_level_field = MDTextField(
            hint_text="Access Level",
            helper_text="pull/push/both/full",
            size_hint_x=1,
            text="pull"
        )
        content.add_widget(access_level_field)
        
        # Folder access field
        folder_access_field = MDTextField(
            hint_text="Folder Access (comma-separated)",
            helper_text="e.g. folder1,folder2,folder3",
            size_hint_x=1
        )
        content.add_widget(folder_access_field)

        self.dialog = MDDialog(
            title="Add New User",
            content_cls=content,
            buttons=[
                MDButton(
                    style="text",
                    on_release=lambda x: self.dialog.dismiss()
                ).add_widget(MDButtonText(text="CANCEL")),
                MDButton(
                    style="filled",
                    on_release=lambda x: self._handle_add_user(
                        username_field.text,
                        password_field.text,
                        role_field.text,
                        access_level_field.text,
                        folder_access_field.text
                    )
                ).add_widget(MDButtonText(text="ADD"))
            ]
        )
        self.dialog.open()

    def _handle_add_user(self, username, password, role, access_level, folder_access):
        """Handle user creation"""
        if not all([username, password, role, access_level]):
            self.show_error("Please fill all required fields")
            return

        # Process folder access
        folder_list = [f.strip() for f in folder_access.split(',')] if folder_access else []
        
        # Create user data structure
        user_data = {
            'username': username,
            'password': password,
            'email': username if '@' in username else f"{username}@example.com",
            'role': role,
            'access_level': access_level,
            'folder_access': folder_list
        }

        # Create user asynchronously
        app = MDApp.get_running_app()
        Clock.schedule_once(
            lambda dt: asyncio.run_coroutine_threadsafe(
                self._async_add_user(user_data),
                app.loop
            )
        )

    async def _async_add_user(self, user_data):
        """Handle user creation asynchronously"""
        try:
            result = await self.user_manager.create_user(user_data)

            if result.get('success'):
                await self._load_users()  # Refresh user list
                self.show_success("User created successfully")
                self.dialog.dismiss()
            else:
                self.show_error(result.get('error', 'Failed to create user'))

        except Exception as e:
            Logger.error(f"User creation error: {str(e)}")
            self.show_error(str(e))

    def _show_user_details(self, user):
        """Show user details dialog"""
        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(10),
            padding=dp(20),
            adaptive_height=True
        )

        fields = [
            ('Username', user.get('username', 'Unknown')),
            ('Role', user.get('role', 'Unknown')),
            ('Access Level', user.get('access_level', 'Unknown')),
            ('Status', user.get('status', 'Unknown')),
            ('Created', user.get('created_at', 'Unknown'))
        ]

        # Add folder access information
        folder_access = user.get('folder_access', [])
        if folder_access:
            fields.append(('Folder Access', ", ".join(folder_access)))
        else:
            fields.append(('Folder Access', 'None'))

        for label, value in fields:
            content.add_widget(MDLabel(
                text=f"{label}: {value}",
                font_size="16sp"
            ))

        self.dialog = MDDialog(
            title="User Details",
            content_cls=content,
            buttons=[
                MDButton(
                    style="text",
                    on_release=lambda x: self.dialog.dismiss()
                ).add_widget(MDButtonText(text="CLOSE")),
                MDButton(
                    style="filled",
                    on_release=lambda x: self._show_edit_user_dialog(user)
                ).add_widget(MDButtonText(text="EDIT"))
            ]
        )
        self.dialog.open()

    def _show_edit_user_dialog(self, user):
        """Show dialog for editing user"""
        self.dialog.dismiss()
        
        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(10),
            padding=dp(20),
            adaptive_height=True
        )

        # Role selector
        role_field = MDTextField(
            hint_text="Role",
            text=user.get('role', 'user'),
            size_hint_x=1
        )
        content.add_widget(role_field)
        
        # Access level selector
        access_level_field = MDTextField(
            hint_text="Access Level",
            text=user.get('access_level', 'pull'),
            size_hint_x=1
        )
        content.add_widget(access_level_field)
        
        # Status selector
        status_field = MDTextField(
            hint_text="Status",
            text=user.get('status', 'active'),
            size_hint_x=1
        )
        content.add_widget(status_field)
        
        # Folder access field
        folder_access = ", ".join(user.get('folder_access', []))
        folder_access_field = MDTextField(
            hint_text="Folder Access (comma-separated)",
            text=folder_access,
            size_hint_x=1
        )
        content.add_widget(folder_access_field)

        self.dialog = MDDialog(
            title=f"Edit User: {user.get('username')}",
            content_cls=content,
            buttons=[
                MDButton(
                    style="text",
                    on_release=lambda x: self.dialog.dismiss()
                ).add_widget(MDButtonText(text="CANCEL")),
                MDButton(
                    style="filled",
                    on_release=lambda x: self._handle_edit_user(
                        user.get('username'),
                        {
                            'role': role_field.text,
                            'access_level': access_level_field.text,
                            'status': status_field.text,
                            'folder_access': [f.strip() for f in folder_access_field.text.split(',') if f.strip()]
                        }
                    )
                ).add_widget(MDButtonText(text="SAVE"))
            ]
        )
        self.dialog.open()

    def _handle_edit_user(self, username, updates):
        """Handle user edit operation"""
        app = MDApp.get_running_app()
        Clock.schedule_once(
            lambda dt: asyncio.run_coroutine_threadsafe(
                self._async_update_user(username, updates),
                app.loop
            )
        )

    async def _async_update_user(self, username, updates):
        """Update user asynchronously"""
        try:
            result = await self.user_manager.update_user(username, updates)
            
            if result:
                await self._load_users()  # Refresh user list
                self.dialog.dismiss()
                self.show_success(f"User {username} updated successfully")
            else:
                self.show_error(f"Failed to update user {username}")
                
        except Exception as e:
            Logger.error(f"Error updating user: {str(e)}")
            self.show_error(f"Error: {str(e)}")

    def show_storage_management(self):
        """Show storage management dialog"""
        app = MDApp.get_running_app()
        Clock.schedule_once(
            lambda dt: asyncio.run_coroutine_threadsafe(
                self._load_folders_for_management(),
                app.loop
            )
        )

    async def _load_folders_for_management(self):
        """Load folders for management dialog"""
        try:
            folders, _ = await self.s3_helper.list_folder_contents()
            
            content = MDBoxLayout(
                orientation='vertical',
                spacing=dp(10),
                padding=dp(20),
                adaptive_height=True
            )
            
            # Storage stats
            stats = await self.s3_helper.get_bucket_stats()
            stats_label = MDLabel(
                text=f"Total Size: {stats.get('total_size_gb', 0):.2f}GB\nTotal Files: {stats.get('total_files', 0)}",
                font_size="16sp"
            )
            content.add_widget(stats_label)
            
            # Folder list
            folder_list = MDList()
            content.add_widget(folder_list)
            
            for folder in folders:
                folder_name = folder.rstrip('/')
                item = MDListItem(
                    MDListItemLeadingIcon(icon="folder"),
                    MDListItemHeadlineText(text=folder_name),
                    on_release=lambda x, f=folder: self._show_folder_details(f)
                )
                folder_list.add_widget(item)
            
            # Add new folder button
            new_folder_field = MDTextField(
                hint_text="New Folder Name",
                size_hint_x=1
            )
            content.add_widget(new_folder_field)
            
            self.dialog = MDDialog(
                title="Storage Management",
                content_cls=content,
                buttons=[
                    MDButton(
                        style="text",
                        on_release=lambda x: self.dialog.dismiss()
                    ).add_widget(MDButtonText(text="CLOSE")),
                    MDButton(
                        style="filled",
                        on_release=lambda x: self._handle_create_folder(new_folder_field.text)
                    ).add_widget(MDButtonText(text="CREATE FOLDER"))
                ]
            )
            self.dialog.open()
            
        except Exception as e:
            Logger.error(f"Error loading folders: {str(e)}")
            self.show_error(f"Error: {str(e)}")

    def _handle_create_folder(self, folder_name):
        """Handle folder creation"""
        if not folder_name:
            self.show_error("Please enter a folder name")
            return
            
        app = MDApp.get_running_app()
        Clock.schedule_once(
            lambda dt: asyncio.run_coroutine_threadsafe(
                self._async_create_folder(folder_name),
                app.loop
            )
        )

    async def _async_create_folder(self, folder_name):
        """Create folder asynchronously"""
        try:
            # Ensure folder name has trailing slash for S3
            if not folder_name.endswith('/'):
                folder_name += '/'
                
            result = await self.s3_helper.create_folder(
                folder_name,
                user_id=MDApp.get_running_app().current_user.get('user_id')
            )
            
            if result:
                self.dialog.dismiss()
                self.show_success(f"Folder {folder_name} created successfully")
                await self._load_storage_stats()  # Refresh stats
            else:
                self.show_error(f"Failed to create folder {folder_name}")
                
        except Exception as e:
            Logger.error(f"Error creating folder: {str(e)}")
            self.show_error(f"Error: {str(e)}")

    def _show_folder_details(self, folder):
        """Show folder details dialog"""
        app = MDApp.get_running_app()
        Clock.schedule_once(
            lambda dt: asyncio.run_coroutine_threadsafe(
                self._async_show_folder_details(folder),
                app.loop
            )
        )

    async def _async_show_folder_details(self, folder):
        """Show folder details asynchronously"""
        try:
            # Get folder contents
            subfolder, files = await self.s3_helper.list_folder_contents(prefix=folder)
            
            # Calculate folder size
            total_size = sum(file.get('size', 0) for file in files)
            
            content = MDBoxLayout(
                orientation='vertical',
                spacing=dp(10),
                padding=dp(20),
                adaptive_height=True
            )
            
            # Folder details
            details_text = (
                f"Folder: {folder}\n"
                f"Total Files: {len(files)}\n"
                f"Total Subfolders: {len(subfolder)}\n"
                f"Total Size: {total_size / (1024 * 1024):.2f} MB"
            )
            
            content.add_widget(MDLabel(
                text=details_text,
                font_size="16sp"
            ))
            
            # Users with access
            users_with_access = [
                user for user in self.user_list 
                if folder in user.get('folder_access', [])
            ]
            
            if users_with_access:
                content.add_widget(MDLabel(
                    text="Users with access:",
                    font_size="16sp",
                    bold=True
                ))
                
                users_list = MDList()
                content.add_widget(users_list)
                
                for user in users_with_access:
                    item = MDListItem(
                        MDListItemHeadlineText(text=user.get('username', 'Unknown')),
                        MDListItemSupportingText(text=user.get('access_level', 'Unknown'))
                    )
                    users_list.add_widget(item)
            else:
                content.add_widget(MDLabel(
                    text="No users have access to this folder",
                    font_size="16sp"
                ))
            
            self.dialog = MDDialog(
                title="Folder Details",
                content_cls=content,
                buttons=[
                    MDButton(
                        style="text",
                        on_release=lambda x: self.dialog.dismiss()
                    ).add_widget(MDButtonText(text="CLOSE")),
                    MDButton(
                        style="filled",
                        on_release=lambda x: self._show_manage_folder_access(folder)
                    ).add_widget(MDButtonText(text="MANAGE ACCESS"))
                ]
            )
            self.dialog.open()
            
        except Exception as e:
            Logger.error(f"Error showing folder details: {str(e)}")
            self.show_error(f"Error: {str(e)}")

    def _show_manage_folder_access(self, folder):
        """Show dialog to manage folder access"""
        self.dialog.dismiss()
        
        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(10),
            padding=dp(20),
            adaptive_height=True
        )
        
        # Label
        content.add_widget(MDLabel(
            text=f"Manage access for folder: {folder}",
            font_size="16sp"
        ))
        
        # User selector
        user_selector = MDTextField(
            hint_text="Select User",
            size_hint_x=1
        )
        content.add_widget(user_selector)
        
        # Create user list for dropdown
        user_menu_items = [
            {
                "text": user.get('username', 'Unknown'),
                "viewclass": "OneLineListItem",
                "on_release": lambda x=user.get('username', ''): self._set_selected_user(user_selector, x)
            }
            for user in self.user_list
        ]
        
        user_menu = MDDropdownMenu(
            caller=user_selector,
            items=user_menu_items,
            width_mult=4
        )
        
        user_selector.on_focus = lambda x, y: user_menu.open() if y else None
        
        self.dialog = MDDialog(
            title="Manage Folder Access",
            content_cls=content,
            buttons=[
                MDButton(
                    style="text",
                    on_release=lambda x: self.dialog.dismiss()
                ).add_widget(MDButtonText(text="CANCEL")),
                MDButton(
                    style="filled",
                    theme_bg_color="Success",
                    on_release=lambda x: self._handle_grant_access(user_selector.text, folder)
                ).add_widget(MDButtonText(text="GRANT ACCESS")),
                MDButton(
                    style="filled",
                    theme_bg_color="Error",
                    on_release=lambda x: self._handle_revoke_access(user_selector.text, folder)
                ).add_widget(MDButtonText(text="REVOKE ACCESS"))
            ]
        )
        self.dialog.open()

    def _set_selected_user(self, text_field, username):
        """Set selected user in text field"""
        text_field.text = username

    def _handle_grant_access(self, username, folder):
        """Handle granting folder access to user"""
        if not username:
            self.show_error("Please select a user")
            return
            
        app = MDApp.get_running_app()
        Clock.schedule_once(
            lambda dt: asyncio.run_coroutine_threadsafe(
                self._async_grant_folder_access(username, folder),
                app.loop
            )
        )

    async def _async_grant_folder_access(self, username, folder):
        """Grant folder access asynchronously"""
        try:
            # Find user
            user = next((u for u in self.user_list if u.get('username') == username), None)
            if not user:
                self.show_error(f"User {username} not found")
                return
                
            # Update folder access
            folder_access = user.get('folder_access', [])
            if folder not in folder_access:
                folder_access.append(folder)
                
            # Update user
            result = await self.user_manager.update_user(
                username,
                {'folder_access': folder_access}
            )
            
            if result:
                await self._load_users()  # Refresh user list
                self.dialog.dismiss()
                self.show_success(f"Access granted for user {username} to folder {folder}")
            else:
                self.show_error(f"Failed to grant access")
                
        except Exception as e:
            Logger.error(f"Error granting access: {str(e)}")
            self.show_error(f"Error: {str(e)}")

    def _handle_revoke_access(self, username, folder):
        """Handle revoking folder access from user"""
        if not username:
            self.show_error("Please select a user")
            return
            
        app = MDApp.get_running_app()
        Clock.schedule_once(
            lambda dt: asyncio.run_coroutine_threadsafe(
                self._async_revoke_folder_access(username, folder),
                app.loop
            )
        )

    async def _async_revoke_folder_access(self, username, folder):
        """Revoke folder access asynchronously"""
        try:
            # Find user
            user = next((u for u in self.user_list if u.get('username') == username), None)
            if not user:
                self.show_error(f"User {username} not found")
                return
                
            # Update folder access
            folder_access = user.get('folder_access', [])
            if folder in folder_access:
                folder_access.remove(folder)
                
            # Update user
            result = await self.user_manager.update_user(
                username,
                {'folder_access': folder_access}
            )
            
            if result:
                await self._load_users()  # Refresh user list
                self.dialog.dismiss()
                self.show_success(f"Access revoked for user {username} to folder {folder}")
            else:
                self.show_error(f"Failed to revoke access")
                
        except Exception as e:
            Logger.error(f"Error revoking access: {str(e)}")
            self.show_error(f"Error: {str(e)}")

    def show_logs(self):
        """Show system logs dialog"""
        app = MDApp.get_running_app()
        Clock.schedule_once(
            lambda dt: asyncio.run_coroutine_threadsafe(
                self._async_load_logs(),
                app.loop
            )
        )

    async def _async_load_logs(self):
        """Load logs asynchronously"""
        try:
            logs = await self.db_manager.get_audit_logs(limit=50)
            
            content = MDBoxLayout(
                orientation='vertical',
                spacing=dp(10),
                padding=dp(20),
                adaptive_height=True
            )
            
            # Create scrollable list
            logs_list = MDList()
            content.add_widget(logs_list)
            
            for log in logs:
                timestamp = log.get('timestamp', 'Unknown')
                action = log.get('action', 'Unknown')
                user_id = log.get('user_id', 'System')
                severity = log.get('severity', 'info')
                
                item = MDListItem(
                    MDListItemLeadingIcon(
                        icon="information" if severity == 'info' else "alert"
                    ),
                    MDListItemHeadlineText(text=f"{action}"),
                    MDListItemSupportingText(text=f"{timestamp} - {user_id}")
                )
                logs_list.add_widget(item)
            
                self.dialog = MDDialog(
                title="System Logs",
                content_cls=content,
                buttons=[
                    MDButton(
                        style="text",
                        on_release=lambda x: self.dialog.dismiss()
                    ).add_widget(MDButtonText(text="CLOSE"))
                ]
            )
            self.dialog.open()
            
        except Exception as e:
            Logger.error(f"Error loading logs: {str(e)}")
            self.show_error(f"Error: {str(e)}")

    def show_settings(self):
        """Show settings dialog"""
        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(10),
            padding=dp(20),
            adaptive_height=True
        )

        # Add settings fields
        fields = [
            ("Dashboard Refresh Interval (seconds)", "30"),
            ("Default File Sort Order", "Name"),
            ("Show Hidden Files", "False"),
            ("Default User Role", "user"),
            ("Default Access Level", "pull")
        ]
        
        for label, default_value in fields:
            field = MDTextField(
                hint_text=label,
                text=default_value,
                size_hint_x=1
            )
            content.add_widget(field)

        self.dialog = MDDialog(
            title="Settings",
            content_cls=content,
            buttons=[
                MDButton(
                    style="text",
                    on_release=lambda x: self.dialog.dismiss()
                ).add_widget(MDButtonText(text="CANCEL")),
                MDButton(
                    style="filled",
                    on_release=lambda x: self.dialog.dismiss()
                ).add_widget(MDButtonText(text="SAVE"))
            ]
        )
        self.dialog.open()

    def show_success(self, message):
        """Show success message"""
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

    def show_error(self, message):
        """Show error message"""
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

    def _start_refresh_task(self):
        """Start periodic refresh task"""
        async def refresh_loop():
            while True:
                await asyncio.sleep(30)
                await self._initialize_data()

        self.refresh_task = asyncio.create_task(refresh_loop())

    def toggle_nav_drawer(self):
        """Toggle navigation drawer"""
        try:
            nav_drawer = self.ids.nav_drawer
            nav_drawer.set_state("toggle")
        except Exception as e:
            Logger.error(f"Nav drawer error: {str(e)}")

    def refresh_data(self):
        """Manually refresh dashboard data"""
        app = MDApp.get_running_app()
        Clock.schedule_once(
            lambda dt: asyncio.run_coroutine_threadsafe(
                self._initialize_data(),
                app.loop
            )
        )

    def show_account_menu(self):
        """Show account menu"""
        if not self.account_menu:
            menu_items = [
                {
                    "text": "My Account",
                    "viewclass": "OneLineListItem",
                    "on_release": lambda x: self._show_account_details()
                },
                {
                    "text": "Change Password",
                    "viewclass": "OneLineListItem",
                    "on_release": lambda x: self._show_change_password_dialog()
                },
                {
                    "text": "Logout",
                    "viewclass": "OneLineListItem",
                    "on_release": lambda x: self.logout()
                }
            ]
            self.account_menu = MDDropdownMenu(
                caller=self.ids.right_action_items[1],
                items=menu_items,
                width_mult=3
            )
        self.account_menu.open()

    def _show_account_details(self):
        """Show current user account details"""
        app = MDApp.get_running_app()
        user = app.current_user
        
        if not user:
            self.show_error("User information not available")
            return
        
        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(10),
            padding=dp(20),
            adaptive_height=True
        )
        
        fields = [
            ('Username', user.get('username', 'Unknown')),
            ('Role', user.get('role', 'Unknown')),
            ('Access Level', user.get('access_level', 'Unknown'))
        ]
        
        for label, value in fields:
            content.add_widget(MDLabel(
                text=f"{label}: {value}",
                font_size="16sp"
            ))
        
        self.dialog = MDDialog(
            title="My Account",
            content_cls=content,
            buttons=[
                MDButton(
                    style="text",
                    on_release=lambda x: self.dialog.dismiss()
                ).add_widget(MDButtonText(text="CLOSE"))
            ]
        )
        self.dialog.open()

    def _show_change_password_dialog(self):
        """Show dialog to change password"""
        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(10),
            padding=dp(20),
            adaptive_height=True
        )
        
        current_password = MDTextField(
            hint_text="Current Password",
            password=True,
            size_hint_x=1
        )
        content.add_widget(current_password)
        
        new_password = MDTextField(
            hint_text="New Password",
            password=True,
            size_hint_x=1
        )
        content.add_widget(new_password)
        
        confirm_password = MDTextField(
            hint_text="Confirm New Password",
            password=True,
            size_hint_x=1
        )
        content.add_widget(confirm_password)
        
        self.dialog = MDDialog(
            title="Change Password",
            content_cls=content,
            buttons=[
                MDButton(
                    style="text",
                    on_release=lambda x: self.dialog.dismiss()
                ).add_widget(MDButtonText(text="CANCEL")),
                MDButton(
                    style="filled",
                    on_release=lambda x: self._handle_password_change(
                        current_password.text,
                        new_password.text,
                        confirm_password.text
                    )
                ).add_widget(MDButtonText(text="CHANGE"))
            ]
        )
        self.dialog.open()

    def _handle_password_change(self, current_password, new_password, confirm_password):
        """Handle password change"""
        if not all([current_password, new_password, confirm_password]):
            self.show_error("All fields are required")
            return
            
        if new_password != confirm_password:
            self.show_error("New passwords do not match")
            return
            
        if len(new_password) < 6:
            self.show_error("Password must be at least 6 characters")
            return
            
        app = MDApp.get_running_app()
        Clock.schedule_once(
            lambda dt: asyncio.run_coroutine_threadsafe(
                self._async_change_password(
                    app.current_user.get('username'),
                    current_password,
                    new_password
                ),
                app.loop
            )
        )

    async def _async_change_password(self, username, current_password, new_password):
        """Change password asynchronously"""
        try:
            # Verify current password
            auth_result = await self.user_manager.authenticate_user(
                username,
                current_password
            )
            
            if not auth_result.get('success'):
                self.show_error("Current password is incorrect")
                return
                
            # Update password
            result = await self.user_manager.update_user(
                username,
                {'password': new_password}
            )
            
            if result:
                self.dialog.dismiss()
                self.show_success("Password changed successfully")
            else:
                self.show_error("Failed to change password")
                
        except Exception as e:
            Logger.error(f"Error changing password: {str(e)}")
            self.show_error(f"Error: {str(e)}")

    def logout(self):
        """Handle logout"""
        try:
            app = MDApp.get_running_app()
            if self.refresh_task:
                self.refresh_task.cancel()
            if hasattr(app, 'logout'):
                Clock.schedule_once(lambda dt: asyncio.create_task(app.logout()), 0)
        except Exception as e:
            Logger.error(f"Logout error: {str(e)}")
            self.show_error("Logout failed")

    def _on_resize(self, *args):
        """Handle window resize"""
        pass