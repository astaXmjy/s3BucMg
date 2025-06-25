from kivymd.uix.screen import MDScreen
from kivymd.uix.snackbar import MDSnackbar, MDSnackbarText
from kivymd.uix.menu import MDDropdownMenu
from kivymd.app import MDApp
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivy.clock import Clock
import asyncio
import logging

from core.auth.user_manager import UserManager
from core.utils.audit_logger import AuditLogger

logger = logging.getLogger(__name__)

class RegisterScreen(MDScreen):
    selected_access_level = StringProperty("pull")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = 'register'
        
        # Initialize dependencies
        self.audit_logger = AuditLogger()
        self.user_manager = UserManager(audit_logger=self.audit_logger)
        
        # Create dropdown menu for access levels
        self.menu = MDDropdownMenu(
            items=[
                {
                    "text": "Pull Access (Download Only)",
                    "viewclass": "OneLineListItem", 
                    "on_release": lambda: self.set_access_level("pull")
                },
                {
                    "text": "Push Access (Upload Only)",
                    "viewclass": "OneLineListItem", 
                    "on_release": lambda: self.set_access_level("push")
                },
                {
                    "text": "Full Access (Upload & Download)",
                    "viewclass": "OneLineListItem", 
                    "on_release": lambda: self.set_access_level("both")
                }
            ],
            width_mult=4,
            # We'll set the position when/if we open the menu
            position="auto"
        )

    def set_access_level(self, level):
        """Set the selected access level"""
        self.selected_access_level = level
        # Removed reference to access_level which doesn't exist in the layout
        # The access_description label will automatically update based on the property binding
        if hasattr(self.menu, 'dismiss'):
            self.menu.dismiss()

    def on_register_pressed(self):
        """Handle registration button press"""
        username = self.ids.username.text.strip()
        password = self.ids.password.text
        confirm_password = self.ids.confirm_password.text

        # Validation
        if not all([username, password, confirm_password]):
            return self.show_snackbar("All fields are required")

        if password != confirm_password:
            return self.show_snackbar("Passwords do not match")

        if len(password) < 6:
            return self.show_snackbar("Password must be at least 6 characters")
            
        # Determine email (use username if it looks like an email, otherwise create one)
        email = username if '@' in username else f"{username}@example.com"

        # Create user data dictionary
        user_data = {
            'username': username,
            'password': password,
            'email': email,
            'role': 'user',
            'access_level': self.selected_access_level,
            'folder_access': [f'users/{username}/']  # Default personal folder
        }

        # Schedule the async registration task
        Clock.schedule_once(lambda dt: self._run_async_registration(user_data), 0)

    def _run_async_registration(self, user_data):
        """Run the async registration task"""
        try:
            # Get or create event loop
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Create coroutine
            async def registration_task():
                try:
                    await self._handle_registration(user_data)
                except Exception as e:
                    logger.error(f"Registration error: {str(e)}")
                    self.show_snackbar("Registration failed")
            
            # Run the coroutine
            loop.run_until_complete(registration_task())
            
        except Exception as e:
            logger.error(f"Error scheduling registration task: {str(e)}")
            self.show_snackbar("Registration error occurred")

    async def _handle_registration(self, user_data):
        """Process user registration asynchronously"""
        try:
            # Create user in database
            result = await self.user_manager.create_user(user_data)
            
            if result.get('success'):
                # Log successful registration
                await self.audit_logger.log_event(
                    'user_created',
                    result.get('user', {}).get('uuid'),
                    {'username': user_data['username']}
                )
                
                # Create user's personal folder in S3
                app = MDApp.get_running_app()
                if hasattr(app, 's3_helper'):
                    personal_folder = f"users/{user_data['username']}/"
                    await app.s3_helper.create_folder(personal_folder)
                    
                    # Log folder creation
                    await self.audit_logger.log_event(
                        'folder_created',
                        result.get('user', {}).get('uuid'),
                        {'folder': personal_folder}
                    )
                
                # Show success message and navigate to login
                Clock.schedule_once(lambda dt: self.show_snackbar("Registration successful! Please login.", is_success=True), 0)
                Clock.schedule_once(lambda dt: self.goto_login(), 2)
            else:
                # Show error message
                error_msg = result.get('error', 'Registration failed')
                Clock.schedule_once(lambda dt: self.show_snackbar(error_msg), 0)
        
        except Exception as e:
            logger.error(f"Registration error: {str(e)}")
            Clock.schedule_once(lambda dt: self.show_snackbar(f"Registration error: {str(e)}"), 0)

    def show_snackbar(self, message, is_success=False):
        """Show a snackbar message"""
        # Success color is green, default/error color is a dark gray
        bg_color = [0.2, 0.8, 0.2, 1] if is_success else [0.3, 0.3, 0.3, 1]
    
        snackbar = MDSnackbar(
            MDSnackbarText(
                text=message,
            ),
            y=dp(24),
            pos_hint={"center_x": 0.5},
            size_hint_x=0.8,
            md_bg_color=bg_color,
            duration=2
        )
        snackbar.open()

    def goto_login(self):
        """Navigate to the login screen"""
        app = MDApp.get_running_app()
        if app and hasattr(app, 'root'):
            app.root.current = 'login'
        else:
            logger.error("Could not navigate to login screen")
            self.show_snackbar("Navigation error")