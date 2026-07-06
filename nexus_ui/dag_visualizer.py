"""
NEXUS AI v4.0 — Real-time DAG execution visualization in right panel.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Displays a directed acyclic graph (DAG) of task execution nodes with
real-time status updates (pending/running/success/failed).
Optimized for canvas-based rendering with minimal CPU overhead.
"""

import logging
import math
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from nexus_ui.theme_engine import get_theme_engine

logger = logging.getLogger("nexus.ui.dag")


class NodeStatus(Enum):
    """Status of a DAG execution node."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class DAGNode:
    """A single node in the task execution DAG."""
    id: str
    label: str
    status: NodeStatus = NodeStatus.PENDING
    depends_on: List[str] = field(default_factory=list)
    duration_ms: float = 0.0
    error: Optional[str] = None
    x: float = 0.0
    y: float = 0.0
    width: float = 140.0
    height: float = 40.0


class DAGVisualizer:
    """
    Real-time DAG execution visualization.
    
    Manages node positions, status colors, and connection lines
    for rendering on a tkinter Canvas.
    """
    
    def __init__(self):
        self._theme = get_theme_engine()
        self.nodes: Dict[str, DAGNode] = {}
        self._node_positions: Dict[str, Tuple[float, float]] = {}
        self._canvas_width: int = 400
        self._canvas_height: int = 600
        self._node_spacing_x: float = 160.0
        self._node_spacing_y: float = 70.0
        self._padding: float = 20.0
    
    def set_canvas_size(self, width: int, height: int) -> None:
        """Set the canvas dimensions for layout calculation."""
        self._canvas_width = width
        self._canvas_height = height
    
    def set_dag_plan(self, plan: Dict[str, Any]) -> None:
        """
        Load a DAG plan from the task planner.
        
        Args:
            plan: Dict with 'steps' list containing step definitions
                  with 'id', 'label', and 'depends_on' fields.
        """
        self.nodes.clear()
        
        steps = plan.get("steps", [])
        if not steps:
            return
        
        # Create nodes
        for step in steps:
            node_id = step.get("id", f"step_{len(self.nodes)}")
            self.nodes[node_id] = DAGNode(
                id=node_id,
                label=step.get("label", node_id),
                depends_on=step.get("depends_on", []),
            )
        
        # Calculate layout
        self._calculate_layout()
    
    def update_node_status(
        self,
        node_id: str,
        status: NodeStatus,
        duration_ms: float = 0.0,
        error: Optional[str] = None,
    ) -> None:
        """
        Update the status of a DAG node.
        
        Args:
            node_id: ID of the node to update.
            status: New status.
            duration_ms: Execution duration in milliseconds.
            error: Error message if failed.
        """
        if node_id in self.nodes:
            node = self.nodes[node_id]
            node.status = status
            node.duration_ms = duration_ms
            node.error = error
    
    def get_node_color(self, status: NodeStatus) -> str:
        """Get the color for a node based on its status."""
        colors = {
            NodeStatus.PENDING: self._theme.colors.dag_pending,
            NodeStatus.RUNNING: self._theme.colors.dag_running,
            NodeStatus.SUCCESS: self._theme.colors.dag_success,
            NodeStatus.FAILED: self._theme.colors.dag_failed,
            NodeStatus.SKIPPED: self._theme.colors.dag_pending,
        }
        return colors.get(status, self._theme.colors.dag_pending)
    
    def render(self, canvas: object) -> None:
        """
        Render the DAG on a tkinter Canvas.
        
        Args:
            canvas: tkinter Canvas widget to draw on.
        """
        try:
            canvas.delete("dag_all")
            
            # Draw connection lines first (behind nodes)
            for node_id, node in self.nodes.items():
                for dep_id in node.depends_on:
                    if dep_id in self.nodes:
                        dep_node = self.nodes[dep_id]
                        self._draw_connection(canvas, dep_node, node)
            
            # Draw nodes
            for node_id, node in self.nodes.items():
                self._draw_node(canvas, node)
        
        except Exception as e:
            logger.debug(f"DAG render error: {e}")
    
    def _draw_node(self, canvas: object, node: DAGNode) -> None:
        """Draw a single DAG node on the canvas."""
        x, y = node.x, node.y
        w, h = node.width, node.height
        color = self.get_node_color(node.status)
        
        # Node background
        canvas.create_rectangle(
            x, y, x + w, y + h,
            fill=self._theme.colors.bg_tertiary,
            outline=color,
            width=2,
            tags="dag_all",
        )
        
        # Status indicator dot
        dot_x = x + 10
        dot_y = y + h / 2
        canvas.create_oval(
            dot_x - 4, dot_y - 4, dot_x + 4, dot_y + 4,
            fill=color,
            outline="",
            tags="dag_all",
        )
        
        # Label text
        label_x = x + 20
        label_y = y + h / 2
        canvas.create_text(
            label_x, label_y,
            text=node.label[:20],
            fill=self._theme.colors.text_primary,
            anchor="w",
            font=self._theme.get_mono_font("small"),
            tags="dag_all",
        )
        
        # Duration text
        if node.duration_ms > 0:
            dur_x = x + w - 5
            dur_text = f"{node.duration_ms:.0f}ms"
            canvas.create_text(
                dur_x, y + h + 10,
                text=dur_text,
                fill=self._theme.colors.text_secondary,
                anchor="e",
                font=self._theme.get_mono_font("small"),
                tags="dag_all",
            )
    
    def _draw_connection(self, canvas: object, from_node: DAGNode, to_node: DAGNode) -> None:
        """Draw a connection arrow between two nodes."""
        x1 = from_node.x + from_node.width
        y1 = from_node.y + from_node.height / 2
        x2 = to_node.x
        y2 = to_node.y + to_node.height / 2
        
        color = self._theme.colors.border_primary
        
        # Line
        canvas.create_line(
            x1, y1, x2, y2,
            fill=color,
            width=1,
            tags="dag_all",
        )
        
        # Arrow head
        arrow_size = 6
        angle = math.atan2(y2 - y1, x2 - x1)
        ax1 = x2 - arrow_size * math.cos(angle - 0.5)
        ay1 = y2 - arrow_size * math.sin(angle - 0.5)
        ax2 = x2 - arrow_size * math.cos(angle + 0.5)
        ay2 = y2 - arrow_size * math.sin(angle + 0.5)
        
        canvas.create_polygon(
            x2, y2, ax1, ay1, ax2, ay2,
            fill=color,
            outline="",
            tags="dag_all",
        )
    
    def _calculate_layout(self) -> None:
        """Calculate node positions using a simple layered layout."""
        if not self.nodes:
            return
        
        # Find root nodes (no dependencies)
        root_ids = [
            nid for nid, node in self.nodes.items()
            if not node.depends_on
        ]
        
        # Simple BFS layering
        layers: List[List[str]] = []
        visited: set = set()
        current_layer = root_ids
        
        while current_layer:
            layers.append(current_layer)
            visited.update(current_layer)
            
            next_layer = []
            for nid in current_layer:
                node = self.nodes[nid]
                # Find nodes that depend on this one
                for other_id, other_node in self.nodes.items():
                    if other_id not in visited and nid in other_node.depends_on:
                        if other_id not in next_layer:
                            next_layer.append(other_id)
            
            # Also add any unvisited nodes that have all deps satisfied
            for nid, node in self.nodes.items():
                if nid not in visited and nid not in next_layer:
                    if all(dep in visited for dep in node.depends_on):
                        next_layer.append(nid)
            
            current_layer = next_layer
        
        # Position nodes by layer
        start_y = self._padding
        for layer in layers:
            count = len(layer)
            total_width = count * self._node_spacing_x
            start_x = (self._canvas_width - total_width) / 2
            
            for i, nid in enumerate(layer):
                if nid in self.nodes:
                    self.nodes[nid].x = start_x + i * self._node_spacing_x
                    self.nodes[nid].y = start_y
            
            start_y += self._node_spacing_y