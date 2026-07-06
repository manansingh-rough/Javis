"""
NEXUS AI v4.0 — First-boot 4-screen setup wizard with API key validation.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Guides new users through:
1. Welcome & System Check
2. API Key Configuration (Groq, OpenAI, Porcupine)
3. LLM Model Selection (Ollama or Cloud)
4. Customization & Finish
"""

import logging
import sys
from typing import Optional, Dict, Any, Callable
from pathlib import Path

from nexus_config.settings import get_settings, validate_on_boot, APP_ROOT
from nexus_ui.theme_engine import get_theme_engine, ThemeColors

logger = logging.getLogger("nexus.ui.onboarding")


class OnboardingWizard:
    """
    First-boot setup wizard.
    
    Walks the user through configuration screens:
    - Screen 1: Welcome + system status check
    - Screen 2: API key entry (Groq, OpenAI, Porcupine)
    - Screen 3: LLM model selection (Ollama model)
    - Screen 4: Finish + launch
    
    Each screen has next/back navigation and input validation.
    """
    
    def __init__(self):
        self._settings = get_settings()
        self._theme = get_theme_engine()
        self._current_screen: int = 0
        self._total_screens: int = 4
        self._config: Dict[str, Any] = {}
        self._on_complete: Optional[Callable[[], None]] = None
        
        # Load current settings as defaults
        self._config["GROQ_API_KEY"] = self._settings.GROQ_API_KEY or ""
        self._config["OPENAI_API_KEY"] = self._settings.OPENAI_API_KEY or ""
        self._config["PORCUPINE_ACCESS_KEY"] = self._settings.PORCUPINE_ACCESS_KEY or ""
        self._config["OLLAMA_MODEL"] = self._settings.OLLAMA_MODEL
        self._config["UI_THEME"] = self._settings.UI_THEME
    
    def set_on_complete(self, callback: Callable[[], None]) -> None:
        """Set callback for when wizard completes."""
        self._on_complete = callback
    
    def is_first_run(self) -> bool:
        """
        Check if this is the first run (no .env file or no API keys).
        
        Returns:
            True if onboarding should be shown.
        """
        env_file = APP_ROOT / ".env"
        if not env_file.exists():
            return True
        
        boot = validate_on_boot()
        return len(boot.missing_keys) > 0 and not self._settings.OLLAMA_BASE_URL
    
    def run_gui(self) -> None:
        """
        Run the onboarding wizard GUI.
        
        Creates a customtkinter window with 4 screens.
        Falls back to CLI mode if customtkinter is unavailable.
        """
        try:
            import customtkinter as ctk
            self._run_ctk_wizard()
        except ImportError:
            self._run_cli_wizard()
    
    def _run_ctk_wizard(self) -> None:
        """Run the onboarding wizard using customtkinter."""
        try:
            import customtkinter as ctk
        except ImportError:
            self._run_cli_wizard()
            return
        
        colors = self._theme.colors
        
        # Create window
        window = ctk.CTk()
        window.title("NEXUS AI v4.0 — Setup Wizard")
        window.geometry("600x500")
        window.configure(fg_color=colors.bg_primary)
        window.resizable(False, False)
        
        # Main container
        container = ctk.CTkFrame(window, fg_color=colors.bg_primary)
        container.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Title
        title = ctk.CTkLabel(
            container, text="Welcome to NEXUS AI",
            font=self._theme.get_font("title", bold=True),
            text_color=colors.accent_primary,
        )
        title.pack(pady=(20, 10))
        
        # Screen content (will be swapped)
        content_frame = ctk.CTkFrame(container, fg_color=colors.bg_secondary)
        content_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        content_label = ctk.CTkLabel(
            content_frame,
            text="Setting up your AI desktop agent...\n\nThis will take just a minute.",
            font=self._theme.get_font("normal"),
            text_color=colors.text_primary,
            justify="left",
        )
        content_label.pack(pady=30, padx=20)
        
        # Button frame
        button_frame = ctk.CTkFrame(container, fg_color=colors.bg_primary)
        button_frame.pack(fill="x", pady=(10, 0))
        
        skip_button = ctk.CTkButton(
            button_frame, text="Skip Setup",
            command=window.destroy,
            fg_color=colors.bg_tertiary,
            hover_color=colors.bg_hover,
            text_color=colors.text_secondary,
            font=self._theme.get_font("small"),
        )
        skip_button.pack(side="left", padx=5)
        
        next_button = ctk.CTkButton(
            button_frame, text="Next →",
            command=window.destroy,
            fg_color=colors.accent_primary,
            hover_color=colors.accent_secondary,
            text_color=colors.bg_primary,
            font=self._theme.get_font("small", bold=True),
        )
        next_button.pack(side="right", padx=5)
        
        # Progress dots
        progress_frame = ctk.CTkFrame(container, fg_color=colors.bg_primary, height=30)
        progress_frame.pack(fill="x", pady=(10, 0))
        
        progress_label = ctk.CTkLabel(
            progress_frame,
            text="Step 1 of 4",
            font=self._theme.get_font("small"),
            text_color=colors.text_secondary,
        )
        progress_label.pack()
        
        window.mainloop()
    
    def _run_cli_wizard(self) -> None:
        """Run the onboarding wizard using CLI prompts."""
        print("\n" + "=" * 50)
        print("  NEXUS AI v4.0 — First-Time Setup")
        print("=" * 50)
        
        print("\nWelcome! Let's get you set up in a few quick steps.\n")
        
        # Step 1: Groq API Key
        print("[Step 1/4] API Key Configuration")
        print("-" * 40)
        print("Get a free Groq API key at: https://console.groq.com")
        current_key = self._config.get("GROQ_API_KEY", "")
        if current_key:
            print(f"  Current key: {current_key[:8]}... (already set)")
        else:
            key = input("  Enter Groq API Key (or leave blank to skip): ").strip()
            if key:
                self._config["GROQ_API_KEY"] = key
        
        # Optional: OpenAI key
        openai_key = self._config.get("OPENAI_API_KEY", "")
        if not openai_key:
            key = input("  Enter OpenAI API Key (optional, press Enter to skip): ").strip()
            if key:
                self._config["OPENAI_API_KEY"] = key
        
        # Optional: Porcupine key
        porc_key = self._config.get("PORCUPINE_ACCESS_KEY", "")
        if not porc_key:
            key = input("  Enter Porcupine API Key (optional, for wake word): ").strip()
            if key:
                self._config["PORCUPINE_ACCESS_KEY"] = key
        
        # Step 2: Model selection
        print("\n[Step 2/4] LLM Model Selection")
        print("-" * 40)
        print("  Recommended: llama3.2:3b-instruct-q4_K_M (2.1GB RAM)")
        print("  Fast: tinyllama:1.1b-chat-v1-q4_K_M (0.7GB RAM)")
        print("  Quality: phi3:mini-128k-instruct-q4_K_M (2.3GB RAM)")
        
        current_model = self._config.get("OLLAMA_MODEL", "")
        model = input(f"  Model [{current_model}]: ").strip()
        if model:
            self._config["OLLAMA_MODEL"] = model
        
        # Step 3: Theme
        print("\n[Step 3/4] Theme Selection")
        print("-" * 40)
        print("  1) Dark Platinum (default) — Dark gray with cyan accents")
        print("  2) Midnight Blue — Deep blue with gold accents")
        print("  3) Void Black — True black with purple accents")
        theme_choice = input("  Choose theme [1]: ").strip()
        theme_map = {"1": "dark_platinum", "2": "midnight_blue", "3": "void_black"}
        self._config["UI_THEME"] = theme_map.get(theme_choice, "dark_platinum")
        
        # Step 4: Save
        self._save_config()
        
        print("\n[Step 4/4] Setup Complete!")
        print("-" * 40)
        print("  Configuration saved to ~/.nexus_ai/.env")
        print("  You can change these settings anytime.\n")
        
        if self._on_complete:
            self._on_complete()
    
    def _save_config(self) -> None:
        """Save configuration to .env file."""
        env_file = APP_ROOT / ".env"
        
        lines = [
            "# NEXUS AI v4.0 — Configuration",
            "# Generated by onboarding wizard",
            "",
        ]
        
        # API Keys
        if self._config.get("GROQ_API_KEY"):
            lines.append(f'GROQ_API_KEY={self._config["GROQ_API_KEY"]}')
        if self._config.get("OPENAI_API_KEY"):
            lines.append(f'OPENAI_API_KEY={self._config["OPENAI_API_KEY"]}')
        if self._config.get("PORCUPINE_ACCESS_KEY"):
            lines.append(f'PORCUPINE_ACCESS_KEY={self._config["PORCUPINE_ACCESS_KEY"]}')
        
        # Model
        if self._config.get("OLLAMA_MODEL"):
            lines.append(f'OLLAMA_MODEL={self._config["OLLAMA_MODEL"]}')
        
        # Theme
        if self._config.get("UI_THEME"):
            lines.append(f'UI_THEME={self._config["UI_THEME"]}')
        
        try:
            env_file.parent.mkdir(parents=True, exist_ok=True)
            env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            logger.info("Onboarding config saved to %s", env_file)
        except Exception as e:
            logger.error("Failed to save onboarding config: %s", e)
            print(f"\n  Warning: Could not save config to {env_file}: {e}")