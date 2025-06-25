from asyncio.log import logger
from kivymd.app import MDApp
from kivy.lang import Builder
from kivy.core.window import Window
from kivy.uix.screenmanager import ScreenManager, FadeTransition
from kivy.logger import Logger
import os
from kivymd.uix.button import MDButton
import sys
import asyncio
import threading
from functools import partial
from kivy.clock import Clock
from views.auth.login import LoginScreen
from views.auth.register import RegisterScreen
from interface.push_interface.push_file_manager import PushFileManagerScreen
from interface.pull_interface.pull_interface_org import PullFileManagerScreen
from interface.admin_interface.admin_interface_org import AdminDashboard
from core.aws.config import AWSConfig
from core.utils.database_manager import DatabaseManager
import codecs
from kivy.factory import Factory
from kivymd.uix.dropdownitem import MDDropDownItem
from kivymd.uix.menu import MDDropdownMenu
from views.common.styles import AppTheme
Factory.register('MDDropDownItem', cls=MDDropDownItem)
Factory.register('MDDropdownMenu', cls=MDDropdownMenu)
Factory.register('MDSnackbar', module='kivymd.uix.snackbar')
Factory.register('MDSnackbarText', module='kivymd.uix.snackbar')
Factory.register('MDCard', module='kivymd.uix.card')
Factory.register('MDTextField', module='kivymd.uix.textfield')
Factory.register('MDLabel', module='kivymd.uix.label')

class CustomScreenManager(ScreenManager):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.transition = FadeTransition()
        self._thread_local = threading.local()
        self._switch_complete = asyncio.Event()

    def get_event_loop(self):
        if not hasattr(self._thread_local, 'loop'):
            try:
                self._thread_local.loop = asyncio.get_running_loop()
            except RuntimeError:
                self._thread_local.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._thread_local.loop)
        return self._thread_local.loop
    

    def switch_screen(self, screen_name, **kwargs):
        try:
            if screen_name not in self.screen_names:
                Logger.error(f"Screen {screen_name} not found")
                return False

            self.current = screen_name
            screen = self.get_screen(screen_name)

            if hasattr(screen, 'pre_enter'):
                screen.pre_enter(**kwargs)

            if hasattr(screen, 'on_enter'):
                Clock.schedule_once(
                    partial(self._handle_screen_enter, screen, kwargs),
                    0
                )

            return True

        except Exception as e:
            Logger.error(f"Screen switch error: {str(e)}")
            return False

    def _handle_screen_enter(self, screen, kwargs, dt):
        try:
            if asyncio.iscoroutinefunction(screen.on_enter):
                loop = self.get_event_loop()
                asyncio.run_coroutine_threadsafe(
                    screen.on_enter(**kwargs),
                    loop
                )
            else:
                screen.on_enter(**kwargs)

        except Exception as e:
            Logger.error(f"Screen enter error: {str(e)}")

    def add_screen(self, screen, name=None):
        try:
            if name:
                screen.name = name
            if screen.name not in self.screen_names:
                self.add_widget(screen)
                return True
            return False

        except Exception as e:
            Logger.error(f"Error adding screen: {str(e)}")
            return False

    def remove_screen(self, name):
        try:
            if name in self.screen_names:
                screen = self.get_screen(name)
                self.remove_widget(screen)
                return True
            return False

        except Exception as e:
            Logger.error(f"Error removing screen: {str(e)}")
            return False

class S3FileManagerApp(MDApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
        # Set theme properties before loading any KV files
        self.theme_cls.theme_style = "Light"
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.accent_palette = "Amber"
        self.theme_cls.material_style = "M3"

        # Set specific color values
        self.theme_cls.primary_color = AppTheme.PRIMARY
        self.theme_cls.primary_light = AppTheme.PRIMARY_LIGHT
        self.theme_cls.primary_dark = AppTheme.PRIMARY_DARK

        # Set background colors
        self.theme_cls.bg_light = AppTheme.BG_LIGHT
        self.theme_cls.bg_dark = AppTheme.BG_DARK

        # Core configuration
        self.config = AWSConfig()

        # User state
        self.current_user = None
        self.access_token = None
        self.refresh_token = None

        # Thread-local storage
        self._thread_local = threading.local()

        # Initialize managers
        self.user_manager = None
        self.permission_manager = None
        self.audit_logger = None
        self.db_manager = DatabaseManager()

    @property
    def loop(self):
        """Get thread-local event loop"""
        if not hasattr(self._thread_local, 'loop'):
            try:
                self._thread_local.loop = asyncio.get_running_loop()
            except RuntimeError:
                self._thread_local.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._thread_local.loop)
        return self._thread_local.loop

    def build(self):
        try:
            # Set window properties
            Window.size = (1200, 800)

            # Create screen manager
            self.sm = CustomScreenManager()
            self.sm.transition = FadeTransition()

            # Load theme-related settings
            self.theme_cls.theme_style = "Light"
            self.theme_cls.primary_palette = "Blue"
            self.theme_cls.accent_palette = "Amber"

            # Schedule async setup
            Clock.schedule_once(lambda dt: self._async_setup(), 0)

            return self.sm

        except Exception as e:
            Logger.error(f"Error in build: {str(e)}")
            return None

    def _init_ui(self):
        """Initialize UI components"""
        try:
            # Load KV files first
            self.load_kv_files()

            # Then set up screens
            self.setup_screens()

            Logger.info("UI initialized successfully")

        except Exception as e:
            Logger.error(f"UI initialization error: {str(e)}")
            raise

    def _async_setup(self):
        try:
            self.loop.run_until_complete(self._run_setup_tasks())
        except Exception as e:
            Logger.error(f"Setup error: {str(e)}")
            sys.exit(1)

    async def _run_setup_tasks(self):
        try:
            await asyncio.gather(
                self._init_aws(),
                self._init_managers(),
                self._init_admin_user()
            )
            self._init_ui()
            self.sm.switch_screen('login')
            
        except Exception as e:
            Logger.error(f"Setup task error: {str(e)}")
            raise

    async def _init_aws(self):
        try:
            AWSConfig.validate_config()
            success = await AWSConfig.initialize_tables()
            if not success:
                raise Exception("Failed to initialize DynamoDB tables")
            Logger.info("AWS services initialized successfully")
            
        except Exception as e:
            Logger.error(f"AWS initialization error: {str(e)}")
            raise

    async def _init_managers(self):
        try:
            from core.utils.audit_logger import AuditLogger
            from core.utils.cache_manager import CacheManager
            from core.auth.permission_manager import PermissionManager
            from core.auth.user_manager import UserManager
            from core.aws.s3_helper import S3Helper
            self.s3_helper = S3Helper()
            self.audit_logger = AuditLogger(db_manager=self.db_manager)
            cache_manager = CacheManager()
            self.permission_manager = PermissionManager()
            
            self.user_manager = UserManager(
                audit_logger=self.audit_logger,
                cache_manager=cache_manager,
                permission_manager=self.permission_manager
            )
            
            Logger.info("All managers initialized successfully")
            
        except Exception as e:
            Logger.error(f"Manager initialization error: {str(e)}")
            raise

    async def _init_admin_user(self):
        try:
            admin_data = {
                'username': AWSConfig.ADMIN_USERNAME,
                'password': AWSConfig.ADMIN_PASSWORD,
                'email': 'admin@example.com',
                'role': 'admin',
                'access_level': 'full'
            }
            
            result = await self.user_manager.create_user(admin_data)
            if result.get('success'):
                Logger.info("Admin user initialized successfully")
                await self.audit_logger.log_event(
                    'admin_user_created',
                    user_id=admin_data['username'],
                    severity='info'
                )
            else:
                Logger.info("Admin user already exists")
                
        except Exception as e:
            Logger.error(f"Admin user initialization error: {str(e)}")
            raise


    def load_kv_files(self):
        """Load all KV files in correct order"""
        try:
            # First load the base styles
            base_style_path = os.path.join('views', 'common', 'styles.kv')
            logger.info(f"Loading base styles from {base_style_path}")
            Builder.load_file(base_style_path)
            logger.info("Base styles loaded successfully")

            # Then load other KV files
            kv_files = [
                os.path.join('views', 'auth', 'login.kv'),
                os.path.join('views', 'auth', 'register.kv'),
                os.path.join('interface', 'push_interface', 'push_file_manager.kv'),
                os.path.join('interface', 'pull_interface', 'pull_interface.kv'),
                os.path.join('interface', 'admin_interface', 'admin_interface.kv'),
            ]

            for kv_file in kv_files:
                try:
                    logger.info(f"Loading KV file: {kv_file}")
                    Builder.load_file(kv_file)
                    logger.info(f"Loaded KV: {kv_file}")
                except Exception as e:
                    logger.error(f"Error loading {kv_file}: {str(e)}")

        except Exception as e:
            logger.error(f"Error in load_kv_files: {str(e)}")
            raise

    def setup_screens(self):
        try:
            screens = {
                'login': LoginScreen,
                'register': RegisterScreen,
                'push_file_manager': PushFileManagerScreen,
                'pull_interface': PullFileManagerScreen,
                'admin_interface': AdminDashboard
            }

            for name, screen_class in screens.items():
                try:
                    screen = screen_class(name=name)
                    self.sm.add_widget(screen)
                    Logger.info(f"Added screen: {name}")
                except Exception as e:
                    Logger.error(f"Error adding screen {name}: {str(e)}")

        except Exception as e:
            Logger.error(f"Error in setup_screens: {str(e)}")
            raise

    async def handle_auth_error(self, error_msg: str):
        """Handle authentication errors"""
        try:
            await self.audit_logger.log_event(
                'auth_error',
                user_id=self.current_user.get('username') if self.current_user else None,
                severity='warning',
                details={'error': error_msg}
            )
            await self.logout()
        except Exception as e:
            Logger.error(f"Error handling auth error: {str(e)}")

    async def refresh_auth_token(self):
        """Refresh authentication token"""
        try:
            if not self.refresh_token:
                await self.handle_auth_error("No refresh token available")
                return False

            result = await self.user_manager.refresh_token(self.refresh_token)
            if result.get('success'):
                self.access_token = result['access_token']
                return True
            else:
                await self.handle_auth_error("Token refresh failed")
                return False

        except Exception as e:
            Logger.error(f"Token refresh error: {str(e)}")
            return False

    async def validate_session(self):
        """Validate current session"""
        try:
            if not self.access_token:
                return False

            result = await self.user_manager.validate_token(self.access_token)
            if not result.get('valid'):
                return await self.refresh_auth_token()

            return True

        except Exception as e:
            Logger.error(f"Session validation error: {str(e)}")
            return False

    async def logout(self):
        """Handle user logout with cleanup"""
        try:
            # Log the logout event if we have a current user
            if self.current_user:
                try:
                    await self.audit_logger.log_event(
                        'user_logout',
                        user_id=self.current_user.get('user_id'),
                        details={'username': self.current_user.get('username')},
                        severity='info'
                    )
                except Exception as log_error:
                    Logger.error(f"Error logging logout: {str(log_error)}")
            
            # Clear user session data
            self.current_user = None
            self.access_token = None
            self.refresh_token = None

            # Schedule screen switch on the main thread with a delay
            def switch_to_login(dt):
                try:
                    # Try screen manager first
                    if hasattr(self, 'sm') and self.sm:
                        try:
                            self.sm.current = 'login'
                            Logger.info("Successfully switched to login screen")
                            return
                        except Exception as sm_error:
                            Logger.error(f"Screen manager switch failed: {str(sm_error)}")
                    
                    # Fallback to root
                    if hasattr(self, 'root'):
                        try:
                            self.root.current = 'login'
                            Logger.info("Successfully switched to login screen using root")
                            return
                        except Exception as root_error:
                            Logger.error(f"Root switch failed: {str(root_error)}")
                    
                    Logger.error("All screen switching methods failed")
                except Exception as e:
                    Logger.error(f"Critical error during screen switch: {str(e)}")

            # Try multiple times with increasing delays
            Clock.schedule_once(switch_to_login, 0)
            Clock.schedule_once(switch_to_login, 0.1)
            Clock.schedule_once(switch_to_login, 0.5)
            
        except Exception as e:
            Logger.error(f"Error during logout: {str(e)}")
            # Even if there's an error, try to switch to login screen with a delay
            Clock.schedule_once(lambda dt: setattr(self.root, 'current', 'login'), 0.1)

    def on_stop(self):
        """Clean up resources when app closes"""
        try:
            self.db_manager.close()
            if self.audit_logger:
                self.audit_logger.close()
        except Exception as e:
            Logger.error(f"Error during cleanup: {str(e)}")

if __name__ == '__main__':
    try:
        app = S3FileManagerApp()
        app.run()
    except Exception as e:
        Logger.error(f"Application error: {str(e)}")
        sys.exit(1)