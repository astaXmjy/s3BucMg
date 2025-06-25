from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import StringProperty, NumericProperty, BooleanProperty, ObjectProperty, ListProperty
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonText
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.progressindicator import MDLinearProgressIndicator
from kivy.uix.popup import Popup
import os
import logging

logger = logging.getLogger(__name__)

class EnhancedUploadDialog(Popup):
    """
    A dialog box showing upload progress to S3 bucket with a cancel button
    Supports both single and multiple file uploads
    """
    progress = NumericProperty(0)
    total_size = NumericProperty(0)
    transferred = NumericProperty(0)
    transfer_rate = NumericProperty(0)
    remaining_time = StringProperty("Calculating...")
    on_cancel = ObjectProperty(None)
    files_info = ListProperty([])
    current_file_index = NumericProperty(0)
    
    def __init__(self, **kwargs):
        self.title = ""
        self.size_hint = (None, None)
        self.size = (dp(500), dp(300))
        self.auto_dismiss = False
        self.background_color = [0, 0, 0, 0]  # Transparent background
        
        # Get file information from kwargs
        self.files_info = kwargs.pop('files_info', [])
        self.on_cancel = kwargs.pop('on_cancel', None)
        
        # If only one file is being uploaded, set up the single file mode
        self.is_single_file = len(self.files_info) == 1
        
        # Calculate total size
        self.total_size = sum(file_info.get('size', 0) for file_info in self.files_info)
        
        super(EnhancedUploadDialog, self).__init__(**kwargs)
        
        # Create the content layout
        content = MDCard(
            orientation="vertical",
            padding=dp(20),
            spacing=dp(10),
            size_hint=(1, 1),
            radius=[dp(10)],
            elevation=4,
            md_bg_color=[1, 1, 1, 1],  # White background
        )
        
        # Add title with file count
        title_text = "Uploading" if self.is_single_file else f"Uploading {len(self.files_info)} files"
        title = MDLabel(
            text=title_text,
            font_style="Body",
            role="medium",
            bold=True,
            size_hint_y=None,
            height=dp(30),
            theme_text_color="Primary",
        )
        content.add_widget(title)
        
        # Progress bar
        self.progress_bar = MDLinearProgressIndicator(
            value=0,
            size_hint_x=1,
            height=dp(10),
            indicator_color=[0, 0.5, 1, 1],  # Blue color
        )
        content.add_widget(self.progress_bar)
        
        # Progress percentage
        self.progress_label = MDLabel(
            text="0%",
            font_style="Body",
            halign="right",
            size_hint_y=None,
            height=dp(20),
            theme_text_color="Secondary",
        )
        content.add_widget(self.progress_label)
        
        # File information
        info_box = MDBoxLayout(
            orientation="vertical",
            spacing=dp(5),
            size_hint_y=None,
            height=dp(120),
        )
        
        # Current file being uploaded (only shown for multiple files)
        if not self.is_single_file:
            self.current_file_label = MDLabel(
                text="Preparing...",
                font_style="Body",
                size_hint_y=None,
                height=dp(20),
                theme_text_color="Primary",
            )
            info_box.add_widget(self.current_file_label)
        
        # Total info
        file_text = "file" if self.is_single_file else f"files: {len(self.files_info)} files"
        self.file_info_label = MDLabel(
            text=f"Total remaining: {file_text}: {self._format_size(self.total_size)} (0%)",
            font_style="Body",
            size_hint_y=None,
            height=dp(20),
            theme_text_color="Secondary",
        )
        info_box.add_widget(self.file_info_label)
        
        # Estimated time remaining
        self.time_label = MDLabel(
            text="Estimated time remaining: Calculating...",
            font_style="Body",
            size_hint_y=None,
            height=dp(20),
            theme_text_color="Secondary",
        )
        info_box.add_widget(self.time_label)
        
        # Transfer rate
        self.rate_label = MDLabel(
            text="Transfer rate: 0 MB/s",
            font_style="Body",
            size_hint_y=None,
            height=dp(20),
            theme_text_color="Secondary",
        )
        info_box.add_widget(self.rate_label)
        
        # Files completed (only shown for multiple files)
        if not self.is_single_file:
            self.files_completed_label = MDLabel(
                text=f"Completed: 0/{len(self.files_info)} files",
                font_style="Body",
                size_hint_y=None,
                height=dp(20),
                theme_text_color="Primary",
            )
            info_box.add_widget(self.files_completed_label)
        
        content.add_widget(info_box)
        
        # Add spacer
        content.add_widget(MDBoxLayout(size_hint_y=None, height=dp(10)))
        
        # Cancel button
        button_box = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
        )
        
        # Add spacer to push button to the right
        button_box.add_widget(MDBoxLayout(size_hint_x=1))
        
        cancel_button = MDButton(
            style="elevated",
            size_hint=(None, None),
            size=(dp(100), dp(40)),
            on_release=self._on_cancel_pressed,
        )
        cancel_button.add_widget(MDButtonText(text="Cancel"))
        button_box.add_widget(cancel_button)
        
        content.add_widget(button_box)
        
        self.content = content
        
        # Store last update time for rate calculation
        self._last_update_time = 0
        self._last_bytes = 0
        self.completed_files = 0
        self.transferred = 0
    
    def update_progress(self, file_index, bytes_transferred, file_size):
        """Update the progress for a specific file"""
        try:
            # If this is a new file and we're uploading multiple files, update the current file label
            if not self.is_single_file and file_index != self.current_file_index:
                self.current_file_index = file_index
                current_file = self.files_info[file_index]
                self.current_file_label.text = f"Uploading: {current_file.get('name', 'Unknown')}"
            
            # Calculate file progress
            file_progress = min(100, int((bytes_transferred / file_size) * 100))
            
            # Update progress of total upload
            if self.is_single_file:
                # Simple case - single file
                self.transferred = bytes_transferred
                overall_progress = file_progress
            else:
                # Multiple files - track completed bytes plus current progress
                completed_bytes = sum(file_info.get('size', 0) for file_info in self.files_info[:self.completed_files])
                self.transferred = completed_bytes + bytes_transferred
                
                # Calculate overall progress
                overall_progress = min(100, int((self.transferred / self.total_size) * 100))
            
            # Update progress bar and label
            self.progress = overall_progress / 100.0  # Convert to 0-1 range for progress bar
            self.progress_bar.value = self.progress
            self.progress_label.text = f"{overall_progress}%"
            
            # Update file info
            remaining_bytes = self.total_size - self.transferred
            
            if self.is_single_file:
                self.file_info_label.text = f"Total remaining: {self._format_size(remaining_bytes)} ({overall_progress}%)"
            else:
                self.file_info_label.text = f"Total remaining: {len(self.files_info) - self.completed_files} files: {self._format_size(remaining_bytes)} ({overall_progress}%)"
            
            # Calculate transfer rate
            current_time = Clock.get_time()
            if self._last_update_time > 0:
                time_diff = current_time - self._last_update_time
                if time_diff > 0:
                    bytes_diff = self.transferred - self._last_bytes
                    rate = bytes_diff / time_diff
                    self.transfer_rate = rate
                    
                    # Estimate remaining time
                    if rate > 0:
                        remaining_seconds = remaining_bytes / rate
                        if remaining_seconds < 60:
                            time_str = f"a few seconds" if remaining_seconds < 10 else f"{int(remaining_seconds)} seconds"
                        elif remaining_seconds < 3600:
                            minutes = int(remaining_seconds / 60)
                            time_str = f"{minutes} minute{'s' if minutes > 1 else ''}"
                        else:
                            hours = int(remaining_seconds / 3600)
                            minutes = int((remaining_seconds % 3600) / 60)
                            time_str = f"{hours} hour{'s' if hours > 1 else ''}"
                            if minutes > 0:
                                time_str += f" {minutes} minute{'s' if minutes > 1 else ''}"
                        
                        self.time_label.text = f"Estimated time remaining: {time_str}"
                    
                    # Update transfer rate
                    rate_mb = rate / (1024 * 1024)
                    self.rate_label.text = f"Transfer rate: {rate_mb:.1f} MB/s"
            
            # Store current values for next update
            self._last_update_time = current_time
            self._last_bytes = self.transferred
            
            # Check if current file is complete
            if bytes_transferred >= file_size:
                self.file_completed(file_index)
            
        except Exception as e:
            logger.error(f"Error updating progress: {str(e)}")
    
    def file_completed(self, file_index):
        """Mark a file as completed"""
        self.completed_files = file_index + 1
        
        # If we're uploading multiple files, update the completed files label
        if not self.is_single_file:
            self.files_completed_label.text = f"Completed: {self.completed_files}/{len(self.files_info)} files"
        
        # If all files are completed
        if self.completed_files >= len(self.files_info):
            # Update final progress
            self.progress = 1.0
            self.progress_bar.value = 1.0
            self.progress_label.text = "100%"
            
            if not self.is_single_file:
                self.current_file_label.text = "Upload complete!"
                
            self.file_info_label.text = f"Uploaded: {len(self.files_info)} file{'s' if len(self.files_info) > 1 else ''} ({self._format_size(self.total_size)})"
            self.time_label.text = "Finished"
            
            # Close dialog after a delay
            Clock.schedule_once(lambda dt: self.dismiss(), 1.5)
    
    def _on_cancel_pressed(self, *args):
        """Handle cancel button press"""
        if callable(self.on_cancel):
            self.on_cancel()
        self.dismiss()
    
    def _format_size(self, size_bytes):
        """Format file size with appropriate units"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes/1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes/(1024*1024):.1f} MB"
        else:
            return f"{size_bytes/(1024*1024*1024):.1f} GB"