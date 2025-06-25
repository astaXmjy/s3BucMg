# styles.py
from enum import Enum

class AppTheme:
    # Primary Colors
    PRIMARY = "#2196F3"  # Blue
    PRIMARY_LIGHT = "#64B5F6"
    PRIMARY_DARK = "#1976D2"
    
    # Accent Colors
    ACCENT = "#FFC107"  # Amber
    ACCENT_LIGHT = "#FFD54F"
    ACCENT_DARK = "#FFA000"
    
    # Background Colors
    BG_LIGHT = "#FAFAFA"
    BG_DARK = "#303030"
    
    # Text Colors
    TEXT_PRIMARY = "#212121"
    TEXT_SECONDARY = "#757575"
    TEXT_HINT = "#9E9E9E"
    
    # Card Colors
    CARD_BG_LIGHT = "#FFFFFF"
    CARD_BG_DARK = "#424242"
    
    # Status Colors
    SUCCESS = "#4CAF50"
    WARNING = "#FF9800"
    ERROR = "#F44336"
    INFO = "#2196F3"
    
    # Gradients
    GRADIENT_PRIMARY = ["#1976D2", "#64B5F6"]
    GRADIENT_ACCENT = ["#FFA000", "#FFD54F"]
    
    # Elevation and Shadows
    ELEVATION_LEVELS = {
        "low": "2dp",
        "medium": "4dp",
        "high": "8dp"
    }
    
    # Typography
    FONT_SIZES = {
        "h1": "96sp",
        "h2": "60sp",
        "h3": "48sp",
        "h4": "34sp",
        "h5": "24sp",
        "h6": "20sp",
        "subtitle1": "16sp",
        "subtitle2": "14sp",
        "body1": "16sp",
        "body2": "14sp",
        "button": "14sp",
        "caption": "12sp",
        "overline": "10sp"
    }
    
    # Spacing
    SPACING = {
        "xs": "4dp",
        "sm": "8dp",
        "md": "16dp",
        "lg": "24dp",
        "xl": "32dp",
        "xxl": "48dp"
    }

    # Border Radius
    BORDER_RADIUS = {
        "none": "0dp",
        "sm": "4dp",
        "md": "8dp",
        "lg": "16dp",
        "xl": "24dp",
        "circle": "50%"
    }