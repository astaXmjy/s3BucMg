import asyncio
from kivy.clock import Clock
from kivymd.uix.screen import MDScreen
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDButton, MDButtonText
from kivymd.uix.snackbar import MDSnackbar, MDSnackbarText
from kivymd.app import MDApp
from kivy.metrics import dp
import logging

logger = logging.getLogger(__name__)

class LoginScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.dialog = None
        self.name = 'login'
        logger.info("LoginScreen initialized")

    def validate_login(self):
        """Entry point for login validation"""
        username = self.ids.username.text.strip()
        password = self.ids.password.text.strip()

        if not username or not password:
            self.show_snackbar("Please enter both username and password")
            return

        # For testing purposes - bypass authentication
        if username == "admin" and password == "admin":
            self.test_login(username, "admin")
            return
            
        # Schedule the async login task
        Clock.schedule_once(lambda dt: self._run_async_login(username, password), 0)

    def test_login(self, username, role):
        """Testing login function that bypasses authentication"""
        app = MDApp.get_running_app()
        if not app:
            logger.error("Could not get application instance")
            return

        # Create mock user data
        user_data = {
            'username': username,
            'user_id': '12345',
            'role': role,
            'access_level': 'full' if role == 'admin' else 'pull',
            'folder_access': ['/']
        }

        # Store session data
        app.current_user = user_data
        app.access_token = "test_token"
        app.refresh_token = "test_refresh_token"

        # Navigate to appropriate screen
        target_screen = 'admin_interface' if role == 'admin' else 'pull_interface'
        logger.info(f"Test login successful, navigating to {target_screen}")

        def switch():
            try:
                app.root.current = target_screen
                logger.info(f"Switched to screen: {app.root.current}")
            except Exception as e:
                logger.error(f"Screen switch error: {str(e)}")
                self.show_snackbar("Navigation error")

        Clock.schedule_once(lambda dt: switch(), 0)

    def _run_async_login(self, username, password):
        """Run the async login task"""
        try:
            # Get or create event loop
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Create coroutine
            async def login_task():
                try:
                    await self._validate_login(username, password)
                except Exception as e:
                    logger.error(f"Login error: {str(e)}")
                    self.show_snackbar("Login failed")
            
            # Run the coroutine
            loop.run_until_complete(login_task())
            
        except Exception as e:
            logger.error(f"Error scheduling login task: {str(e)}")
            self.show_snackbar("Login error occurred")

    async def _validate_login(self, username: str, password: str):
        """Validate user credentials"""
        try:
            logger.info(f"Attempting login for user: {username}")
            
            # Get app instance and user manager
            app = MDApp.get_running_app()
            if not app or not hasattr(app, 'user_manager'):
                logger.error("App or UserManager not available")
                self.show_snackbar("System error: UserManager not available")
                return

            result = await app.user_manager.authenticate_user(username, password)
            logger.debug(f"Authentication result: {result}")

            if result.get('success'):
                user_data = result['user']
                await self.store_session(user_data)
                await self.handle_successful_login(user_data)

                # Log successful login
                if hasattr(app, 'audit_logger'):
                    try:
                        await app.audit_logger.log_event(
                            'login_success',
                            user_data.get('user_id'),
                            {'username': username}
                        )
                    except Exception as log_error:
                        logger.error(f"Error logging success: {str(log_error)}")

            else:
                error_msg = result.get('message', 'Authentication failed')
                logger.warning(f"Login failed for user {username}: {error_msg}")
                self.show_snackbar(error_msg)

                # Log failed login attempt
                if hasattr(app, 'audit_logger'):
                    try:
                        await app.audit_logger.log_event(
                            'login_failed',
                            None,
                            {'username': username, 'reason': error_msg}
                        )
                    except Exception as log_error:
                        logger.error(f"Error logging failure: {str(log_error)}")

        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            self.show_snackbar(f"Login error occurred")
            
            # Log error
            app = MDApp.get_running_app()
            if app and hasattr(app, 'audit_logger'):
                try:
                    await app.audit_logger.log_event(
                        'login_error',
                        None,
                        {'username': username, 'error': str(e)}
                    )
                except Exception as log_error:
                    logger.error(f"Error logging error: {str(log_error)}")

    async def handle_successful_login(self, user_data: dict):
        try:
            app = MDApp.get_running_app()
            if not app:
                logger.error("Could not get application instance")
                return

            app.current_user = user_data
            app.access_token = user_data.get('access_token')
            app.refresh_token = user_data.get('refresh_token')

            # Determine target screen based on role and access level
            if user_data.get('role') == 'admin':
                target_screen = 'admin_interface'
            else:
                access_level = user_data.get('access_level', '').lower()
                if access_level == 'push':
                    target_screen = 'push_interface'
                else:  # pull or any other access level
                    target_screen = 'pull_interface'

            logger.info(f"Navigating to screen: {target_screen} for user {user_data.get('username')} with role {user_data.get('role')} and access level {user_data.get('access_level')}")

            def switch():
                try:
                    app.root.current = target_screen
                    logger.info(f"Switched to screen: {app.root.current}")
                except Exception as e:
                    logger.error(f"Screen switch error: {str(e)}")
                    self.show_snackbar("Navigation error")

            Clock.schedule_once(lambda dt: switch(), 0)

        except Exception as e:
            logger.error(f"Login handling error: {str(e)}")
            self.show_snackbar("Error navigating after login")

    async def store_session(self, user_data: dict):
        """Store session data"""
        try:
            app = MDApp.get_running_app()
            if not app:
                logger.error("Could not get application instance")
                return

            # Store session data
            app.current_user = user_data
            app.access_token = user_data.get('access_token')
            app.refresh_token = user_data.get('refresh_token')

            # Cache session data
            if hasattr(app, 'cache_manager'):
                try:
                    await app.cache_manager.set(
                        f"session:{user_data.get('user_id')}",
                        {
                            'user_data': user_data,
                            'access_token': app.access_token,
                            'refresh_token': app.refresh_token
                        }
                    )
                except Exception as cache_error:
                    logger.error(f"Cache error: {str(cache_error)}")

        except Exception as e:
            logger.error(f"Error storing session: {str(e)}")

    def show_snackbar(self, message: str):
        """Show message to user"""
        try:
            snackbar = MDSnackbar(
                MDSnackbarText(
                    text=message,
                ),
                y=dp(24),
                pos_hint={"center_x": 0.5},
                size_hint_x=0.8,
                duration=3
            )
            snackbar.open()
        except Exception as e:
            logger.error(f"Error showing snackbar: {str(e)}")

    def goto_register(self):
        """Navigate to registration screen"""
        try:
            app = MDApp.get_running_app()
            if app:
                app.root.current = 'register'
            else:
                logger.error("Could not navigate to register screen")
                self.show_snackbar("Navigation error occurred")
        except Exception as e:
            logger.error(f"Error navigating to register: {str(e)}")
            self.show_snackbar("Navigation error occurred")

    def forgot_password(self):
        """Handle forgot password"""
        try:
            # Show forgot password dialog
            if not self.dialog:
                self.dialog = MDDialog(
                    title="Reset Password",
                    text="Please contact your administrator to reset your password.",
                    buttons=[
                        MDButton(
                            MDButtonText(text="OK"),
                            on_release=self.close_dialog
                        )
                    ]
                )
            self.dialog.open()
        except Exception as e:
            logger.error(f"Error showing forgot password dialog: {str(e)}")
            self.show_snackbar("Error showing dialog")

    def close_dialog(self, *args):
        """Close any open dialog"""
        try:
            if self.dialog:
                self.dialog.dismiss()
                self.dialog = None
        except Exception as e:
            logger.error(f"Error closing dialog: {str(e)}")