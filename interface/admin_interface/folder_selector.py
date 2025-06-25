import asyncio
from datetime import datetime
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.logger import Logger
from kivy.properties import ListProperty, ObjectProperty
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonText
from kivymd.uix.selectioncontrol import MDCheckbox
from kivymd.uix.label import MDLabel
from kivymd.uix.list import MDList, MDListItem, MDListItemLeadingIcon, MDListItemHeadlineText
from kivymd.app import MDApp
from kivymd.uix.textfield import MDTextField
from KivyMD.build.lib.kivymd.uix.selectioncontrol.selectioncontrol import MDCheckbox


class FolderSelector(Popup):
    """Popup dialog for selecting folders from S3 bucket"""
    selected_folders = ListProperty([])
    on_selection_complete = ObjectProperty(None)
    
    def __init__(self, available_folders=None, current_folders=None, on_selection_complete=None, **kwargs):
        # Initialize with empty lists if none provided
        self.available_folders = available_folders or []
        self.current_folders = current_folders or []
        self.selected_folders = list(self.current_folders)  # Start with current selections
        
        # IMPORTANT: Store the callback directly in the instance
        self.on_selection_complete = on_selection_complete
        Logger.info(f"FolderSelector initialized with callback: {on_selection_complete is not None}")
        
        # Configure popup
        self.title = ""
        self.size_hint = (None, None)
        self.size = (dp(500), dp(600))
        self.auto_dismiss = False
        self.background_color = [0.95, 0.95, 0.95, 1.0]
        
        super(FolderSelector, self).__init__(**kwargs)
        
        # Create content
        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(16),
            padding=dp(24),
            md_bg_color=[1, 1, 1, 1]
        )
        
        # Title
        title = MDLabel(
            text="Select Folders for User Access",
            font_size="22sp",
            bold=True,
            halign="center",
            size_hint_y=None,
            height=dp(40)
        )
        content.add_widget(title)
        
        # Description
        description = MDLabel(
            text="Check the folders you want to grant access to:",
            theme_text_color="Secondary",
            font_size="14sp",
            size_hint_y=None,
            height=dp(30)
        )
        content.add_widget(description)
        
        # Scroll view for folder list
        scroll = ScrollView(
            size_hint=(1, 1),
            do_scroll_x=False,
            do_scroll_y=True,
            bar_width=dp(4),
            bar_color=[0.7, 0.7, 0.7, 0.5],
            bar_inactive_color=[0.7, 0.7, 0.7, 0.2]
        )
        
        # Create folders list
        self.folders_list = MDList(
            spacing=dp(4),
            padding=[0, dp(4), 0, dp(4)]
        )
        self._populate_folders_list()
        
        scroll.add_widget(self.folders_list)
        content.add_widget(scroll)
        
        # Buttons
        buttons = MDBoxLayout(
            orientation='horizontal',
            spacing=dp(16),
            size_hint_y=None,
            height=dp(50),
            padding=[0, dp(16), 0, 0]
        )
        
        # Cancel button
        cancel_button = MDButton(
            style="text",
            on_release=self.dismiss
        )
        cancel_button.add_widget(MDButtonText(text="CANCEL"))
        buttons.add_widget(cancel_button)
        
        # Apply button
        apply_button = MDButton(
            style="filled",
            on_release=self._on_apply
        )
        apply_button.add_widget(MDButtonText(text="APPLY"))
        buttons.add_widget(apply_button)
        
        content.add_widget(buttons)
        self.content = content
    
    def _populate_folders_list(self):
        """Populate the folders list with checkboxes"""
        self.folders_list.clear_widgets()
        self.checkbox_dict = {}  # Store references to checkboxes
        
        # If list is empty, show message
        if not self.available_folders:
            item = MDListItem(
                MDListItemHeadlineText(
                    text="No folders available"
                )
            )
            self.folders_list.add_widget(item)
            return
            
        # Add each folder as a list item with checkbox
        for folder in sorted(self.available_folders):
            # Create checkbox
            checkbox = MDCheckbox(
                size_hint=(None, None),
                size=(dp(32), dp(32)),
                pos_hint={'center_y': 0.5},
                active=folder in self.selected_folders
            )
            # Store reference
            self.checkbox_dict[folder] = checkbox
            
            # Create custom item layout to include checkbox
            item_layout = MDBoxLayout(
                orientation='horizontal',
                spacing=dp(16),
                size_hint_y=None,
                height=dp(48),
                padding=[dp(8), 0, 0, 0]
            )
            
            # Add checkbox
            item_layout.add_widget(checkbox)
            
            # Determine folder name and icon
            if folder == '/':
                folder_name = "Root Directory"
                icon = "folder-home"
            else:
                # Get the folder name (last part of path)
                folder_name = folder.rstrip('/').split('/')[-1] or folder
                icon = "folder"
            
            # Create icon
            folder_icon = MDListItemLeadingIcon(
                icon=icon,
                pos_hint={'center_y': 0.5}
            )
            item_layout.add_widget(folder_icon)
            
            # Create label with full path as subtitle
            folder_info = MDBoxLayout(
                orientation='vertical',
                size_hint_x=1,
                padding=[0, dp(4), 0, dp(4)]
            )
            
            # Main folder name
            name_label = MDLabel(
                text=folder_name,
                font_style="Body",
                bold=True,
                size_hint_y=None,
                height=dp(20)
            )
            folder_info.add_widget(name_label)
            
            # Full path (if not root)
            if folder != '/' and folder != folder_name + '/':
                path_label = MDLabel(
                    text=folder,
                    font_style="Body",
                    font_size="12sp",
                    theme_text_color="Secondary",
                    size_hint_y=None,
                    height=dp(16)
                )
                folder_info.add_widget(path_label)
            
            item_layout.add_widget(folder_info)
            
            # Create list item that wraps our custom layout
            list_item = MDListItem()
            list_item.add_widget(item_layout)
            
            # Bind to toggle checkbox when item is clicked
            list_item.bind(on_release=lambda x, f=folder: self._toggle_folder(f))
            
            # Add to list
            self.folders_list.add_widget(list_item)
    
    def _toggle_folder(self, folder):
        """Toggle selection of a folder"""
        if folder in self.selected_folders:
            self.selected_folders.remove(folder)
            self.checkbox_dict[folder].active = False
        else:
            self.selected_folders.append(folder)
            self.checkbox_dict[folder].active = True
    
    def _on_apply(self, *args):
        """Handle apply button press with enhanced error handling"""
        try:
            Logger.info(f"APPLY BUTTON PRESSED with selected folders: {self.selected_folders}")
            
            # Double check that callback is set
            if self.on_selection_complete:
                Logger.info("Calling on_selection_complete callback")
                # Call the callback with selected folders
                self.on_selection_complete(self.selected_folders)
                self.dismiss()
            else:
                Logger.error("on_selection_complete callback is not set")
                # Display this error in UI to make it visible
                MDApp.get_running_app().show_snackbar("Error: Callback function not set")
                # Keep popup open so user can see the error
        except Exception as e:
            Logger.error(f"Error in _on_apply: {str(e)}")
            Logger.exception("_on_apply error")
            # Show error to user
            MDApp.get_running_app().show_snackbar(f"Error: {str(e)}")