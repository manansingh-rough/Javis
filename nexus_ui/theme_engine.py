"""
NEXUS AI v4.0 — Color palette, font loading, DPI scaling, theme switching.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Provides theme management for the CustomTkinter HUD with three dark themes:
- dark_platinum (default): Dark gray with cyan accents
- midnight_blue: Deep blue with gold accents
- void_black: True black with purple accents

All themes are OLED-friendly with true black backgrounds.
"""

import logging
import platform
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
from functools import lru_cache
from pathlib import Path

from nexus_config.settings import get_settings, APP_ROOT

logger = logging.getLogger("nexus.ui.theme")


@dataclass(frozen=True)
class ThemeColors:
    """
    Immutable color palette for a NEXUS AI theme.
    
    All colors are hex strings (e.g., "#1a1a2e").
    """
    # Background colors
    bg_primary: str = "#0d0d0d"        # Main background
    bg_secondary: str = "#1a1a1a"      # Panel background
    bg_tertiary: str = "#2a2a2a"       # Input/button background
    bg_hover: str = "#3a3a3a"          # Hover state
    
    # Text colors
    text_primary: str = "#ffffff"       # Primary text
    text_secondary: str = "#a0a0a0"    # Secondary/muted text
    text_accent: str = "#00d4ff"       # Accent text
    
    # Accent colors
    accent_primary: str = "#00d4ff"    # Primary accent (cyan)
    accent_secondary: str = "#0088cc"  # Secondary accent
    accent_success: str = "#00ff88"    # Success (green)
    accent_warning: str = "#ffaa00"    # Warning (amber)
    accent_error: str = "#ff4444"      # Error (red)
    accent_info: str = "#4488ff"       # Info (blue)
    
    # Border colors
    border_primary: str = "#333333"    # Default border
    border_focus: str = "#00d4ff"     # Focus border
    border_error: str = "#ff4444"     # Error border
    
    # Animation colors
    particle_color: str = "#00d4ff"    # Particle system color
    arc_reactor_color: str = "#00d4ff" # Arc reactor glow
    waveform_color: str = "#00d4ff"    # Waveform bars
    
    # DAG visualization colors
    dag_pending: str = "#555555"       # Pending node
    dag_running: str = "#00d4ff"       # Running node
    dag_success: str = "#00ff88"       # Completed node
    dag_failed: str = "#ff4444"        # Failed node
    
    # Font configuration
    font_family: str = "Segoe UI"      # Primary font
    font_mono: str = "Consolas"        # Monospace font
    font_size_small: int = 11
    font_size_normal: int = 13
    font_size_large: int = 16
    font_size_xl: int = 20
    font_size_title: int = 28


# ─── Theme Definitions ──────────────────────────────────────────────────────

DARK_PLATINUM = ThemeColors(
    bg_primary="#0d0d0d",
    bg_secondary="#1a1a1a",
    bg_tertiary="#2a2a2a",
    bg_hover="#3a3a3a",
    text_primary="#ffffff",
    text_secondary="#a0a0a0",
    text_accent="#00d4ff",
    accent_primary="#00d4ff",
    accent_secondary="#0088cc",
    accent_success="#00ff88",
    accent_warning="#ffaa00",
    accent_error="#ff4444",
    accent_info="#4488ff",
    border_primary="#333333",
    border_focus="#00d4ff",
    border_error="#ff4444",
    particle_color="#00d4ff",
    arc_reactor_color="#00d4ff",
    waveform_color="#00d4ff",
    dag_pending="#555555",
    dag_running="#00d4ff",
    dag_success="#00ff88",
    dag_failed="#ff4444",
)

MIDNIGHT_BLUE = ThemeColors(
    bg_primary="#0a0a1a",
    bg_secondary="#12122a",
    bg_tertiary="#1a1a3a",
    bg_hover="#2a2a4a",
    text_primary="#e0e0ff",
    text_secondary="#8888aa",
    text_accent="#ffd700",
    accent_primary="#ffd700",
    accent_secondary="#ccaa00",
    accent_success="#00ff88",
    accent_warning="#ff8800",
    accent_error="#ff4444",
    accent_info="#4488ff",
    border_primary="#2a2a4a",
    border_focus="#ffd700",
    border_error="#ff4444",
    particle_color="#ffd700",
    arc_reactor_color="#ffd700",
    waveform_color="#ffd700",
    dag_pending="#444466",
    dag_running="#ffd700",
    dag_success="#00ff88",
    dag_failed="#ff4444",
)

VOID_BLACK = ThemeColors(
    bg_primary="#000000",
    bg_secondary="#0a0a0a",
    bg_tertiary="#1a1a1a",
    bg_hover="#2a2a2a",
    text_primary="#e0e0ff",
    text_secondary="#8888aa",
    text_accent="#bb88ff",
    accent_primary="#bb88ff",
    accent_secondary="#8844cc",
    accent_success="#00ff88",
    accent_warning="#ffaa00",
    accent_error="#ff4444",
    accent_info="#4488ff",
    border_primary="#1a1a1a",
    border_focus="#bb88ff",
    border_error="#ff4444",
    particle_color="#bb88ff",
    arc_reactor_color="#bb88ff",
    waveform_color="#bb88ff",
    dag_pending="#333333",
    dag_running="#bb88ff",
    dag_success="#00ff88",
    dag_failed="#ff4444",
)

THEMES: Dict[str, ThemeColors] = {
    "dark_platinum": DARK_PLATINUM,
    "midnight_blue": MIDNIGHT_BLUE,
    "void_black": VOID_BLACK,
}


class ThemeEngine:
    """
    Manages theme selection, font loading, and DPI scaling.
    
    Provides:
    - Theme switching at runtime
    - Font family resolution per platform
    - DPI-aware scaling
    - Color palette access
    """
    
    def __init__(self):
        self._settings = get_settings()
        self._current_theme_name: str = self._settings.UI_THEME
        self._current_colors: ThemeColors = THEMES.get(
            self._current_theme_name, DARK_PLATINUM
        )
        self._dpi_scale: float = self._detect_dpi_scale()
        self._font_family: str = self._resolve_font_family()
        self._font_mono: str = self._resolve_mono_font()
    
    @property
    def colors(self) -> ThemeColors:
        """Get current theme colors."""
        return self._current_colors
    
    @property
    def theme_name(self) -> str:
        """Get current theme name."""
        return self._current_theme_name
    
    @property
    def dpi_scale(self) -> float:
        """Get DPI scaling factor."""
        return self._dpi_scale * self._settings.UI_FONT_SCALE
    
    def set_theme(self, theme_name: str) -> None:
        """
        Switch to a different theme at runtime.
        
        Args:
            theme_name: One of "dark_platinum", "midnight_blue", "void_black".
        
        Raises:
            ValueError: If theme_name is not recognized.
        """
        if theme_name not in THEMES:
            raise ValueError(f"Unknown theme: {theme_name}. Options: {list(THEMES.keys())}")
        self._current_theme_name = theme_name
        self._current_colors = THEMES[theme_name]
        logger.info(f"Theme switched to: {theme_name}")
    
    def get_font(self, size: str = "normal", bold: bool = False) -> Tuple[str, int, str]:
        """
        Get a font tuple for CustomTkinter.
        
        Args:
            size: One of "small", "normal", "large", "xl", "title".
            bold: Whether to use bold weight.
        
        Returns:
            Tuple of (font_family, font_size, weight).
        """
        sizes = {
            "small": self._current_colors.font_size_small,
            "normal": self._current_colors.font_size_normal,
            "large": self._current_colors.font_size_large,
            "xl": self._current_colors.font_size_xl,
            "title": self._current_colors.font_size_title,
        }
        font_size = int(sizes.get(size, self._current_colors.font_size_normal) * self.dpi_scale)
        weight = "bold" if bold else "normal"
        return (self._font_family, font_size, weight)
    
    def get_mono_font(self, size: str = "normal") -> Tuple[str, int]:
        """
        Get a monospace font tuple.
        
        Args:
            size: One of "small", "normal", "large".
        
        Returns:
            Tuple of (font_family, font_size).
        """
        sizes = {
            "small": self._current_colors.font_size_small,
            "normal": self._current_colors.font_size_normal,
            "large": self._current_colors.font_size_large,
        }
        font_size = int(sizes.get(size, self._current_colors.font_size_normal) * self.dpi_scale)
        return (self._font_mono, font_size)
    
    def _detect_dpi_scale(self) -> float:
        """Detect system DPI scaling factor."""
        try:
            import tkinter as tk
            root = tk.Tk()
            dpi = root.winfo_fpixels("1i")
            root.destroy()
            return dpi / 96.0  # 96 DPI is standard
        except Exception:
            return 1.0
    
    def _resolve_font_family(self) -> str:
        """Resolve the best available font family for the platform."""
        system = platform.system()
        if system == "Windows":
            return "Segoe UI"
        elif system == "Darwin":
            return "SF Pro Display"
        else:
            return "Ubuntu"
    
    def _resolve_mono_font(self) -> str:
        """Resolve the best available monospace font for the platform."""
        system = platform.system()
        if system == "Windows":
            return "Consolas"
        elif system == "Darwin":
            return "SF Mono"
        else:
            return "Ubuntu Mono"


@lru_cache(maxsize=1)
def get_theme_engine() -> ThemeEngine:
    """
    Return the singleton ThemeEngine instance.
    
    Returns:
        ThemeEngine: The singleton theme engine.
    """
    return ThemeEngine()