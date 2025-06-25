from kivymd.app import MDApp
from kivy.lang import Builder
from kivy.core.window import Window
from kivy.uix.screenmanager import ScreenManager, FadeTransition
from kivy.logger import Logger
import os
import sys
import asyncio
import threading
from functools import partial

# Import helpers and managers
from core.utils.database_manager import DatabaseManager
from core.utils.audit_logger import AuditLogger
from core.utils.cache_manager import CacheManager
from core.auth.permission_manager import PermissionManager
from core.auth.user_manager import UserManager
from core.aws.s3_helper import S3Helper

# We'll import the screens after loading their KV files
Builder.load_file('views/auth/login.kv')
Builder.load_file('views/auth/register.kv')
Builder.load_file('interface/admin_interface/admin_interface.kv')
Builder.load_file('interface/push_interface/push_interface.kv')
Builder.load_file('interface/pull_interface/pull_interface.kv')

# Now import screens
from interface.admin_interface.admin_interface import AdminDashboard
from interface.push_interface.push_interface import PushFileManagerScreen
from interface.pull_interface.pull_interface import PullFileManagerScreen
from views.auth.login import LoginScreen
from views.auth.register import RegisterScreen
# In your main.py or where you load KV files
from kivy.factory import Factory

from kivy.properties import StringProperty, BooleanProperty

class CustomScreenManager(ScreenManager):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.transition = FadeTransition()
   
    def switch_screen(self, screen_name):
        if screen_name in self.screen_names:
            self.current = screen_name
            return True
        Logger.warning(f"Screen '{screen_name}' not found")
        return False

class S3FileManagerApp(MDApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Set theme properties
        self.theme_cls.theme_style = "Light"
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.accent_palette = "Amber"
        
        # User state
        self.current_user = None
        self.access_token = None
        self.refresh_token = None
        
        # Main event loop
        self._main_loop = None
        self._loaded_kv_files = set()
        
        # Core managers
        self.db_manager = DatabaseManager()
        self.audit_logger = AuditLogger(db_manager=self.db_manager)
        self.cache_manager = CacheManager()
        self.permission_manager = PermissionManager()
        self.user_manager = UserManager(
            audit_logger=self.audit_logger,
            cache_manager=self.cache_manager,
            permission_manager=self.permission_manager
        )
        self.s3_helper = S3Helper(
            db_manager=self.db_manager, 
            audit_logger=self.audit_logger,
            permission_manager=self.permission_manager
        )
        
        # Keep strong references
        self._keep_refs = {}

    @property
    def loop(self):
        """Get application event loop"""
        if not hasattr(self, '_main_loop') or self._main_loop is None:
            try:
                self._main_loop = asyncio.get_event_loop()
            except RuntimeError:
                self._main_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._main_loop)
        return self._main_loop

    def build(self):
        try:
            # Set window properties
            Window.size = (1200, 800)
            
            # Create main event loop
            if not hasattr(self, '_main_loop') or self._main_loop is None:
                self._main_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._main_loop)
            
            # Initialize database
            asyncio.run_coroutine_threadsafe(
                self.db_manager.initialize_database(),
                self.loop
            )
            
            # Create screen manager
            self.sm = CustomScreenManager()
            
            # Add screens - KV files are already loaded above
            self.sm.add_widget(LoginScreen())
            self.sm.add_widget(RegisterScreen())
            self.sm.add_widget(AdminDashboard())
            self.sm.add_widget(PushFileManagerScreen())
            self.sm.add_widget(PullFileManagerScreen())
            
            # Set initial screen
            self.sm.current = 'login'
            
            # Keep references to all managers for garbage collection prevention
            self._keep_refs = {
                'db_manager': self.db_manager,
                'audit_logger': self.audit_logger,
                'cache_manager': self.cache_manager,
                'permission_manager': self.permission_manager,
                'user_manager': self.user_manager,
                's3_helper': self.s3_helper
            }
            
            return self.sm
        except Exception as e:
            Logger.error(f"Error in build: {str(e)}")
            return None

    async def logout(self):
        """Handle user logout"""
        try:
            from kivy.clock import Clock
            # Log the logout event first
            if self.current_user:
                user_id = self.current_user.get('user_id') or self.current_user.get('uuid')
                if user_id:
                    await self.audit_logger.log_event(
                        'logout',
                        user_id,
                        {'username': self.current_user.get('username')}
                    )

            # Keep reference to current_user until after screen transition
            temp_user = self.current_user

            # Switch to login screen with slight delay
            def switch_to_login():
                self.sm.current = 'login'

            Clock.schedule_once(lambda dt: switch_to_login(), 0.1)

            # Small delay after screen transition to clear data
            await asyncio.sleep(0.3)

            # Clear session data
            self.current_user = None
            self.access_token = None
            self.refresh_token = None

            # Clear cached data
            await self.cache_manager.clear()

        except Exception as e:
            Logger.error(f"Error during logout: {str(e)}")

    def on_stop(self):
        """App is closing, clean up resources"""
        try:
            # Close database connections
            if hasattr(self, 'db_manager') and self.db_manager:
                self.db_manager.close()
            
            # Close S3 connections
            if hasattr(self, 's3_helper') and self.s3_helper:
                self.s3_helper.close()
            
            # Clear references
            if hasattr(self, '_keep_refs'):
                self._keep_refs.clear()
                
            # Close the event loop
            if hasattr(self, '_main_loop') and self._main_loop:
                self._main_loop.close()

            Logger.info("Application shutting down, resources cleaned up")
        except Exception as e:
            Logger.error(f"Error during cleanup: {str(e)}")

if __name__ == '__main__':
    try:
        app = S3FileManagerApp()
        app.run()
    except Exception as e:
        Logger.error(f"Application error: {str(e)}")
        sys.exit(1)
