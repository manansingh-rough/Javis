"""
NEXUS AI v4.0 — Reference Plugin: iCal + Google Calendar operations.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Extends NEXUS AI with calendar event management using the calendar_manager tool.
"""

import json
from nexus_plugins.plugin_base import register_plugin
from nexus_tools.tools.t21_calendar_manager import calendar_manager as _calendar_manager


def calendar_list_events(ical_path: str, days_ahead: int = 7, max_events: int = 20) -> str:
    """
    List upcoming calendar events from an iCal file.
    
    Use when: The user wants to check their schedule or upcoming events.
    """
    return _calendar_manager("list_upcoming", ical_path=ical_path,
                             days_ahead=days_ahead, max_events=max_events)


def calendar_create_event(ical_path: str, summary: str, description: str = "",
                          start_time: str = "", end_time: str = "",
                          location: str = "") -> str:
    """
    Create a new calendar event in an iCal file.
    
    Use when: The user wants to add an event to their calendar.
    """
    return _calendar_manager("create_ical", ical_path=ical_path, summary=summary,
                             description=description, start_time=start_time,
                             end_time=end_time, location=location)


def register():
    """Register this plugin with NEXUS AI."""
    return register_plugin(
        name="calendar-plugin",
        tool_func=calendar_list_events,
        version="1.0.0",
        author="NEXUS AI Team",
        description="Manage calendar events via iCal files",
        tags=["calendar", "schedule", "productivity"],
        needs_network=False,
        needs_filesystem=True,
    )