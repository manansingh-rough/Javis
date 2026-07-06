"""
NEXUS AI v4.0 — Particle system, arc reactor, waveform, loading animations.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Provides canvas-based animations optimized for i3 7th Gen:
- Particle system (ambient floating particles)
- Arc reactor (rotating glow ring)
- Waveform (audio-responsive bars)
- Adaptive frame rate to maintain 30-60 FPS on low-power CPU
"""

import logging
import math
import random
import time
from typing import List, Optional, Callable
from dataclasses import dataclass, field

from nexus_config.settings import get_settings
from nexus_ui.theme_engine import get_theme_engine

logger = logging.getLogger("nexus.ui.animation")


# ─── Constants ───────────────────────────────────────────────────────────────

MAX_PARTICLES: int = 80
"""Maximum particles before performance degrades on i3."""

PARTICLE_SPEED: float = 0.3
"""Base particle movement speed in pixels per frame."""

ARC_REACTOR_SEGMENTS: int = 24
"""Number of segments in the arc reactor ring."""

WAVEFORM_BARS: int = 32
"""Number of bars in the waveform display."""

FRAME_BUDGET_MS: float = 16.67
"""Target frame budget for 60 FPS (16.67ms)."""


# ─── Data Classes ───────────────────────────────────────────────────────────

@dataclass
class Particle:
    """A single ambient particle."""
    x: float
    y: float
    vx: float
    vy: float
    size: int
    alpha: float
    color: str
    life: float = 1.0
    max_life: float = 1.0


@dataclass
class ArcReactor:
    """Rotating arc reactor animation state."""
    angle: float = 0.0
    pulse: float = 0.0
    direction: int = 1


@dataclass
class Waveform:
    """Audio waveform animation state."""
    bars: List[float] = field(default_factory=list)
    smoothing: float = 0.3


# ─── Animation Engine ──────────────────────────────────────────────────────

class AnimationEngine:
    """
    Manages canvas-based UI animations.
    
    Design notes for i3 7th Gen:
    - Particle count auto-scales based on measured frame time.
    - All animation state is pre-computed, not rendered per frame.
    - Uses simple physics (no collision detection) to keep math cheap.
    """
    
    def __init__(self):
        self._settings = get_settings()
        self._theme = get_theme_engine()
        
        # Particle system
        self.particles: List[Particle] = []
        self._particle_count: int = min(
            self._settings.UI_PARTICLE_COUNT, MAX_PARTICLES
        )
        
        # Arc reactor
        self.arc_reactor = ArcReactor()
        
        # Waveform
        self.waveform = Waveform()
        self.waveform.bars = [0.0] * WAVEFORM_BARS
        
        # Performance tracking
        self._last_frame_time: float = 0.0
        self._frame_times: List[float] = []
        self._adaptive_count: int = self._particle_count
        
        # Canvas reference (set during HUD init)
        self._particle_canvas: Optional[object] = None
        self._reactor_canvas: Optional[object] = None
        self._waveform_canvas: Optional[object] = None
    
    def set_canvases(
        self,
        particle_canvas: object = None,
        reactor_canvas: object = None,
        waveform_canvas: object = None,
    ) -> None:
        """Set canvas references for rendering."""
        self._particle_canvas = particle_canvas
        self._reactor_canvas = reactor_canvas
        self._waveform_canvas = waveform_canvas
    
    def update(self, dt: float) -> None:
        """
        Update all animation states for the current frame.
        
        Args:
            dt: Delta time in seconds since last frame.
        """
        self._update_particles(dt)
        self._update_arc_reactor(dt)
        self._update_performance(dt)
    
    def reset_particles(self) -> None:
        """Reinitialize the particle system."""
        self.particles.clear()
        for _ in range(self._particle_count):
            self._add_particle()
    
    def set_waveform_levels(self, levels: List[float]) -> None:
        """
        Set waveform bar levels from audio input.
        
        Args:
            levels: List of float values 0.0-1.0 for each bar.
        """
        for i in range(min(len(levels), WAVEFORM_BARS)):
            if i < len(self.waveform.bars):
                # Smooth transition
                target = min(1.0, max(0.0, levels[i]))
                current = self.waveform.bars[i]
                self.waveform.bars[i] = current + (target - current) * self.waveform.smoothing
    
    def _update_particles(self, dt: float) -> None:
        """Update particle positions and lifecycle."""
        speed = PARTICLE_SPEED * dt * 60
        
        for particle in self.particles[:]:
            particle.x += particle.vx * speed
            particle.y += particle.vy * speed
            particle.life -= dt * 0.1
            
            if particle.life <= 0:
                self.particles.remove(particle)
                self._add_particle()
    
    def _add_particle(self) -> None:
        """Add a new particle at a random edge position."""
        if not self._particle_canvas:
            return
        
        try:
            width = int(self._particle_canvas.winfo_width())
            height = int(self._particle_canvas.winfo_height())
        except Exception:
            width, height = 300, 600
        
        edge = random.choice(["left", "right", "top", "bottom"])
        if edge == "left":
            x, y = 0, random.randint(0, height)
            vx = random.uniform(0.2, 0.8)
            vy = random.uniform(-0.3, 0.3)
        elif edge == "right":
            x, y = width, random.randint(0, height)
            vx = random.uniform(-0.8, -0.2)
            vy = random.uniform(-0.3, 0.3)
        elif edge == "top":
            x, y = random.randint(0, width), 0
            vx = random.uniform(-0.3, 0.3)
            vy = random.uniform(0.2, 0.8)
        else:
            x, y = random.randint(0, width), height
            vx = random.uniform(-0.3, 0.3)
            vy = random.uniform(-0.8, -0.2)
        
        particle = Particle(
            x=x,
            y=y,
            vx=vx,
            vy=vy,
            size=random.randint(1, 3),
            alpha=random.uniform(0.2, 0.8),
            color=self._theme.colors.particle_color,
            life=random.uniform(2.0, 6.0),
        )
        self.particles.append(particle)
    
    def _update_arc_reactor(self, dt: float) -> None:
        """Update arc reactor rotation and pulse."""
        self.arc_reactor.angle += dt * 30 * self.arc_reactor.direction
        if self.arc_reactor.angle > 360:
            self.arc_reactor.angle -= 360
        
        self.arc_reactor.pulse += dt * self.arc_reactor.direction
        if self.arc_reactor.pulse > 1.0:
            self.arc_reactor.direction = -1
        elif self.arc_reactor.pulse < 0.3:
            self.arc_reactor.direction = 1
    
    def _update_performance(self, dt: float) -> None:
        """Track frame times and adjust particle count adaptively."""
        now = time.perf_counter()
        if self._last_frame_time > 0:
            frame_ms = (now - self._last_frame_time) * 1000
            self._frame_times.append(frame_ms)
            
            # Keep last 30 frame times
            if len(self._frame_times) > 30:
                self._frame_times.pop(0)
            
            # Check if we need to reduce particles
            if len(self._frame_times) >= 10:
                avg_frame_ms = sum(self._frame_times[-10:]) / 10
                if avg_frame_ms > 33:  # Below 30 FPS
                    self._adaptive_count = max(10, self._adaptive_count - 5)
                    if len(self.particles) > self._adaptive_count:
                        self.particles = self.particles[:self._adaptive_count]
                elif avg_frame_ms < 16:  # Above 60 FPS
                    target = min(self._particle_count, self._adaptive_count + 5)
                    self._adaptive_count = min(target, MAX_PARTICLES)
        
        self._last_frame_time = now
    
    @property
    def current_particle_count(self) -> int:
        """Get current adaptive particle count."""
        return self._adaptive_count