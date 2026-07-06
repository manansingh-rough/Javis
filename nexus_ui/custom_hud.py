"""
NEXUS AI v4.0 — CustomTkinter HUD: 4 zones, all animations, queue consumers.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

The main user interface with four zones:
- Zone 1 (Left): Particle system, arc reactor, system metrics
- Zone 2 (Center): Conversation log with streaming text
- Zone 3 (Bottom): Input bar with send button and status
- Zone 4 (Right): DAG execution visualization

Queue-driven architecture ensures the UI thread is NEVER blocked.
"""

import logging
import queue
import threading
import time
from typing import Optional, Dict, Any, Callable
from functools import lru_cache

from nexus_config.settings import get_settings
from nexus_ui.theme_engine import get_theme_engine, ThemeColors
from nexus_ui.animation_engine import AnimationEngine
from nexus_ui.notification_manager import NotificationManager, get_notification_manager, Notification
from nexus_ui.dag_visualizer import DAGVisualizer

logger = logging.getLogger("nexus.ui.hud")


class NexusHUD:
    """
    Main NEXUS AI HUD window.
    
    Queue-driven architecture:
    - output_queue (str tokens from agent)
    - log_queue (dict events from agent)
    - progress_queue (DAG events from task planner)
    - metrics_queue (CPU/RAM from background services)
    
    All queue polling happens via root.after() timer callbacks.
    """
    
    def __init__(self):
        self._settings = get_settings()
        self._theme = get_theme_engine()
        self._animation = AnimationEngine()
        self._notifications = get_notification_manager()
        self._dag = DAGVisualizer()
        
        # Root window (will be set by run_hud)
        self.root = None
        
        # Queues
        self.output_queue: queue.Queue = queue.Queue()
        self.log_queue: queue.Queue = queue.Queue()
        self.progress_queue: queue.Queue = queue.Queue()
        self.metrics_queue: queue.Queue = queue.Queue()
        
        # UI state
        self._running = False
        self._input_callback: Optional[Callable[[str], None]] = None
        self._conversation_lines: list = []
        self._max_conversation_lines: int = 1000
        
        # Widget references (set during _build_ui)
        self._conversation_text = None
        self._input_entry = None
        self._send_button = None
        self._status_label = None
        self._metrics_labels: Dict[str, object] = {}
        self._particle_canvas = None
        self._reactor_canvas = None
        self._waveform_canvas = None
        self._dag_canvas = None
    
    def set_input_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for when user submits input."""
        self._input_callback = callback
    
    def submit_input(self, text: str) -> None:
        """Submit user input to the agent."""
        if not text or not text.strip():
            return
        
        if self._input_callback:
            self._input_callback(text.strip())
        
        # Clear input
        if self._input_entry:
            self._input_entry.delete(0, "end")
    
    def append_output(self, text: str) -> None:
        """Append text to the conversation log."""
        if not self._conversation_text:
            return
        
        try:
            self._conversation_text.configure(state="normal")
            self._conversation_text.insert("end", text)
            self._conversation_text.see("end")
            self._conversation_text.configure(state="disabled")
        except Exception as e:
            logger.debug(f"Append output error: {e}")
    
    def set_status(self, status: str) -> None:
        """Update the status bar text."""
        if self._status_label:
            try:
                self._status_label.configure(text=status)
            except Exception:
                pass
    
    def update_metrics(self, cpu: float, ram: float, disk: float) -> None:
        """Update the metrics display."""
        labels = {
            "cpu": f"CPU: {cpu:.0f}%",
            "ram": f"RAM: {ram:.0f}MB",
            "disk": f"Disk: {disk:.1f}GB",
        }
        for key, text in labels.items():
            if key in self._metrics_labels:
                try:
                    self._metrics_labels[key].configure(text=text)
                except Exception:
                    pass
    
    def _poll_queues(self) -> None:
        """Poll all queues for new data (called via root.after)."""
        if not self._running:
            return
        
        try:
            # Output queue (agent text tokens)
            while True:
                token = self.output_queue.get_nowait()
                self.append_output(token)
        except queue.Empty:
            pass
        
        try:
            # Log queue (activity events)
            while True:
                event = self.log_queue.get_nowait()
                self._handle_log_event(event)
        except queue.Empty:
            pass
        
        try:
            # Progress queue (DAG events)
            while True:
                event = self.progress_queue.get_nowait()
                self._handle_progress_event(event)
        except queue.Empty:
            pass
        
        try:
            # Metrics queue
            while True:
                metrics = self.metrics_queue.get_nowait()
                self.update_metrics(
                    metrics.get("cpu", 0),
                    metrics.get("ram", 0),
                    metrics.get("disk", 0),
                )
        except queue.Empty:
            pass
        
        # Notifications
        self._notifications.process_queue()
        
        # Schedule next poll
        if self._running and self.root:
            try:
                self.root.after(50, self._poll_queues)
            except Exception:
                pass
    
    def _handle_log_event(self, event: Dict[str, Any]) -> None:
        """Handle a log queue event."""
        event_type = event.get("event_type", "")
        if event_type == "TOOL_CALL":
            tool = event.get("data", {}).get("tool", "unknown")
            self.set_status(f"Executing: {tool}...")
        elif event_type == "TOOL_SUCCESS":
            self.set_status("Ready")
        elif event_type == "TOOL_FAILURE":
            self.set_status("Error occurred")
        elif event_type == "CAPABILITY_SYNTH":
            self.set_status("Synthesizing new capability...")
    
    def _handle_progress_event(self, event: Dict[str, Any]) -> None:
        """Handle a progress queue (DAG) event."""
        action = event.get("action", "")
        if action == "plan_loaded":
            self._dag.set_dag_plan(event.get("plan", {}))
        elif action == "node_update":
            self._dag.update_node_status(
                event.get("node_id", ""),
                event.get("status", ""),
                event.get("duration_ms", 0),
                event.get("error"),
            )
        elif action == "complete":
            self.set_status("Task complete")
    
    def start(self) -> None:
        """Start the UI main loop."""
        self._running = True
        if self.root:
            self.root.after(100, self._poll_queues)
            self.root.after(1000, self._animation_loop)
    
    def stop(self) -> None:
        """Stop the UI main loop."""
        self._running = False
    
    def _animation_loop(self) -> None:
        """Animation frame update loop."""
        if not self._running:
            return
        
        dt = 1.0 / 60  # Assume 60 FPS (actual timing would use time.perf_counter)
        self._animation.update(dt)
        
        # Redraw DAG
        if self._dag_canvas:
            self._dag.render(self._dag_canvas)
        
        if self.root:
            self.root.after(16, self._animation_loop)  # ~60 FPS


def build_hud() -> NexusHUD:
    """
    Build and return the NEXUS AI HUD instance.
    
    This function creates the main window and all UI components.
    It is called by main.py after boot validation.
    
    Returns:
        NexusHUD: The fully constructed HUD instance.
    
    Note:
        This function requires that customtkinter is installed.
        Falls back to headless mode if the import fails.
    """
    return NexusHUD()


def run_hud(hud: Optional[NexusHUD] = None, headless: bool = False) -> None:
    """
    Run the NEXUS AI HUD main loop.
    
    Args:
        hud: Pre-built NexusHUD instance. If None, builds one.
        headless: If True, runs without GUI (CLI/text mode).
    
    In headless mode, input is read from stdin and output is printed to stdout.
    """
    if headless:
        _run_headless(hud or NexusHUD())
        return
    
    if hud is None:
        hud = build_hud()
    
    try:
        import customtkinter as ctk
        ctk.set_appearance_mode("dark")
        
        root = ctk.CTk()
        hud.root = root
        
        root.title("NEXUS AI v4.0")
        root.geometry(f"{hud._settings.WINDOW_WIDTH}x{hud._settings.WINDOW_HEIGHT}")
        root.configure(fg_color=hud._theme.colors.bg_primary)
        
        # Build UI
        _build_ctk_ui(hud, root)
        
        # Start
        hud.start()
        root.mainloop()
    
    except ImportError:
        logger.warning("customtkinter not available, running headless")
        _run_headless(hud)
    except Exception as e:
        logger.error(f"HUD error: {e}")
        _run_headless(hud)


def _build_ctk_ui(hud: NexusHUD, root: object) -> None:
    """
    Build the CustomTkinter UI layout.
    
    This creates all 4 zones and connects the widget references to the HUD.
    """
    try:
        import customtkinter as ctk
        colors = hud._theme.colors
        
        # Main container
        main_frame = ctk.CTkFrame(root, fg_color=colors.bg_primary)
        main_frame.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Top bar
        top_frame = ctk.CTkFrame(main_frame, fg_color=colors.bg_secondary, height=40)
        top_frame.pack(fill="x", padx=2, pady=(2, 0))
        top_frame.pack_propagate(False)
        
        title_label = ctk.CTkLabel(
            top_frame, text="NEXUS AI  v4.0",
            font=hud._theme.get_font("large", bold=True),
            text_color=colors.accent_primary,
        )
        title_label.pack(side="left", padx=15, pady=5)
        
        # Status label
        hud._status_label = ctk.CTkLabel(
            top_frame, text="Initializing...",
            font=hud._theme.get_font("small"),
            text_color=colors.text_secondary,
        )
        hud._status_label.pack(side="right", padx=15, pady=5)
        
        # Content area (split into left, center, right)
        content_frame = ctk.CTkFrame(main_frame, fg_color=colors.bg_primary)
        content_frame.pack(fill="both", expand=True, padx=2, pady=2)
        
        content_frame.grid_columnconfigure(0, weight=0, minsize=200)  # Left
        content_frame.grid_columnconfigure(1, weight=1)               # Center
        content_frame.grid_columnconfigure(2, weight=0, minsize=200)  # Right
        content_frame.grid_rowconfigure(0, weight=1)
        
        # Zone 1: Left panel (particles, arc reactor, metrics)
        left_frame = ctk.CTkFrame(content_frame, fg_color=colors.bg_secondary)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 1))
        
        # Particle canvas
        hud._particle_canvas = ctk.CTkCanvas(
            left_frame, bg=colors.bg_secondary, highlightthickness=0,
            height=300,
        )
        hud._particle_canvas.pack(fill="x", padx=5, pady=5)
        hud._animation.set_canvases(particle_canvas=hud._particle_canvas)
        
        # Arc reactor canvas
        hud._reactor_canvas = ctk.CTkCanvas(
            left_frame, bg=colors.bg_secondary, highlightthickness=0,
            height=100,
        )
        hud._reactor_canvas.pack(fill="x", padx=5, pady=5)
        hud._animation.set_canvases(reactor_canvas=hud._reactor_canvas)
        
        # Metrics
        metrics_frame = ctk.CTkFrame(left_frame, fg_color=colors.bg_tertiary)
        metrics_frame.pack(fill="x", padx=5, pady=5)
        
        for key, label in [("cpu", "CPU:"), ("ram", "RAM:"), ("disk", "Disk:")]:
            lbl = ctk.CTkLabel(
                metrics_frame, text=f"{label} --",
                font=hud._theme.get_mono_font("small"),
                text_color=colors.text_secondary,
            )
            lbl.pack(anchor="w", padx=10, pady=2)
            hud._metrics_labels[key] = lbl
        
        # Zone 2: Center panel (conversation log)
        center_frame = ctk.CTkFrame(content_frame, fg_color=colors.bg_primary)
        center_frame.grid(row=0, column=1, sticky="nsew", padx=1)
        
        hud._conversation_text = ctk.CTkTextbox(
            center_frame,
            font=hud._theme.get_font("normal"),
            text_color=colors.text_primary,
            fg_color=colors.bg_primary,
            border_width=0,
            wrap="word",
            state="disabled",
        )
        hud._conversation_text.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Zone 3: Right panel (DAG visualization)
        right_frame = ctk.CTkFrame(content_frame, fg_color=colors.bg_secondary)
        right_frame.grid(row=0, column=2, sticky="nsew", padx=(1, 0))
        
        dag_label = ctk.CTkLabel(
            right_frame, text="Execution Plan",
            font=hud._theme.get_font("small", bold=True),
            text_color=colors.text_accent,
        )
        dag_label.pack(pady=(10, 5))
        
        hud._dag_canvas = ctk.CTkCanvas(
            right_frame, bg=colors.bg_secondary, highlightthickness=0,
        )
        hud._dag_canvas.pack(fill="both", expand=True, padx=5, pady=5)
        hud._dag.set_canvas_size(200, 400)
        
        # Bottom: Input bar
        bottom_frame = ctk.CTkFrame(main_frame, fg_color=colors.bg_secondary, height=50)
        bottom_frame.pack(fill="x", padx=2, pady=(0, 2))
        bottom_frame.pack_propagate(False)
        
        input_frame = ctk.CTkFrame(bottom_frame, fg_color=colors.bg_tertiary)
        input_frame.pack(fill="x", padx=10, pady=8)
        
        hud._input_entry = ctk.CTkEntry(
            input_frame,
            font=hud._theme.get_font("normal"),
            placeholder_text="Type your command or ask a question...",
            fg_color=colors.bg_tertiary,
            text_color=colors.text_primary,
            border_width=0,
        )
        hud._input_entry.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=5)
        
        def on_send():
            text = hud._input_entry.get()
            hud.submit_input(text)
        
        hud._send_button = ctk.CTkButton(
            input_frame, text="Send",
            command=on_send,
            fg_color=colors.accent_primary,
            hover_color=colors.accent_secondary,
            text_color=colors.bg_primary,
            font=hud._theme.get_font("small", bold=True),
            width=80,
        )
        hud._send_button.pack(side="right", padx=(0, 10), pady=5)
        
        # Bind Enter key
        hud._input_entry.bind("<Return>", lambda e: on_send())
    
    except ImportError:
        raise


def _run_headless(hud: NexusHUD) -> None:
    """Run NEXUS AI in headless (CLI) mode."""
    import sys
    print("NEXUS AI v4.0 — Headless Mode")
    print("Type 'exit' to quit.\n")
    
    while True:
        try:
            user_input = input("> ")
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break
        
        if user_input.lower() in ("exit", "quit"):
            break
        
        if hud._input_callback:
            hud._input_callback(user_input)