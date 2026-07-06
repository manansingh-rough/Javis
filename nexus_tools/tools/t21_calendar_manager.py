"""
NEXUS AI v4.0 — Tool 21: Calendar management (iCal + Google Calendar).
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Reads and writes calendar events via iCal files and Google Calendar API.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger("nexus.tool.calendar_manager")


def calendar_manager(
    action: str,
    ical_path: Optional[str] = None,
    summary: str = "",
    description: str = "",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    location: str = "",
    days_ahead: int = 7,
    max_events: int = 20,
) -> str:
    """
    Manage calendar events: read, create, and list events.
    
    Use this tool when: The user asks about their schedule, wants to create
    a calendar event, or check upcoming appointments.
    
    Args:
        action: One of: "read_ical", "create_ical", "list_upcoming"
        ical_path: Path to .ics file (for "read_ical", "create_ical").
        summary: Event title/summary (for "create_ical").
        description: Event description (for "create_ical").
        start_time: Start time in ISO format (for "create_ical").
        end_time: End time in ISO format (for "create_ical").
        location: Event location (for "create_ical").
        days_ahead: Days to look ahead for "list_upcoming".
        max_events: Maximum events to return.
    
    Returns:
        JSON string with keys:
          - success (bool): Whether the operation succeeded.
          - result (any): Event list or confirmation.
          - error (str or null): Error message if failed.
    """
    start = time.perf_counter()
    max_events = min(max(max_events, 1), 100)
    
    try:
        if action == "read_ical":
            if not ical_path:
                return json.dumps({"success": False, "result": None, "error": "ical_path required"})
            
            p = Path(ical_path)
            if not p.exists():
                return json.dumps({"success": False, "result": None, "error": f"File not found: {ical_path}"})
            
            return _read_ical(p, max_events)
        
        elif action == "create_ical":
            if not ical_path:
                return json.dumps({"success": False, "result": None, "error": "ical_path required"})
            if not summary:
                return json.dumps({"success": False, "result": None, "error": "summary required"})
            
            return _create_ical(ical_path, summary, description, start_time, end_time, location)
        
        elif action == "list_upcoming":
            if ical_path:
                p = Path(ical_path)
                if p.exists():
                    return _read_ical(p, max_events, upcoming_only=True, days_ahead=days_ahead)
            return json.dumps({
                "success": True, "result": [],
                "error": None,
                "metadata": {"note": "No calendar file specified. Use ical_path to point to an .ics file."}
            })
        
        else:
            return json.dumps({
                "success": False, "result": None,
                "error": f"Unknown action: '{action}'. Valid: read_ical, create_ical, list_upcoming"
            })
    
    except Exception as e:
        logger.error(f"calendar_manager error: {e}", exc_info=True)
        return json.dumps({
            "success": False, "result": None,
            "error": f"{type(e).__name__}: {e}"
        })


def _read_ical(path: Path, max_events: int, upcoming_only: bool = False, days_ahead: int = 7) -> str:
    """Read events from an iCal (.ics) file."""
    try:
        from icalendar import Calendar
    except ImportError:
        return json.dumps({
            "success": False, "result": None,
            "error": "icalendar not installed. Install with: pip install icalendar"
        })
    
    try:
        with open(path, "rb") as f:
            cal = Calendar.from_ical(f.read())
        
        events = []
        now = datetime.now()
        cutoff = now + timedelta(days=days_ahead) if upcoming_only else None
        
        for component in cal.walk():
            if component.name == "VEVENT":
                event_start = component.get("dtstart")
                if event_start:
                    if hasattr(event_start, "dt"):
                        event_start = event_start.dt
                
                event_end = component.get("dtend")
                if event_end:
                    if hasattr(event_end, "dt"):
                        event_end = event_end.dt
                
                # Filter for upcoming events
                if upcoming_only and event_start:
                    if isinstance(event_start, datetime):
                        if event_start < now or (cutoff and event_start > cutoff):
                            continue
                    elif isinstance(event_start, date):
                        event_dt = datetime.combine(event_start, datetime.min.time())
                        if event_dt < now or (cutoff and event_dt > cutoff):
                            continue
                
                event = {
                    "summary": str(component.get("summary", "")),
                    "description": str(component.get("description", "")),
                    "location": str(component.get("location", "")),
                    "start": str(event_start) if event_start else "",
                    "end": str(event_end) if event_end else "",
                    "uid": str(component.get("uid", "")),
                    "status": str(component.get("status", "")),
                }
                events.append(event)
                
                if len(events) >= max_events:
                    break
        
        # Sort by start time
        events.sort(key=lambda e: e.get("start", ""))
        
        return json.dumps({
            "success": True,
            "result": events,
            "error": None,
            "metadata": {"count": len(events), "file": str(path)}
        })
    
    except Exception as e:
        return json.dumps({
            "success": False, "result": None,
            "error": f"Failed to read iCal file: {e}"
        })


def _create_ical(ical_path: str, summary: str, description: str, start_time: Optional[str], end_time: Optional[str], location: str) -> str:
    """Create a new iCal (.ics) file with an event."""
    try:
        from icalendar import Calendar, Event, vCalAddress, vText
        from dateutil import parser as dateparser
    except ImportError:
        return json.dumps({
            "success": False, "result": None,
            "error": "icalendar not installed. Install with: pip install icalendar python-dateutil"
        })
    
    try:
        cal = Calendar()
        cal.add("prodid", "-//NEXUS AI//Calendar//EN")
        cal.add("version", "2.0")
        
        event = Event()
        event.add("summary", summary)
        event.add("description", description)
        event.add("location", location)
        event.add("uid", f"nexus-{int(time.time())}@nexus-ai")
        
        # Parse times
        if start_time:
            try:
                event.add("dtstart", dateparser.parse(start_time))
            except Exception:
                event.add("dtstart", datetime.now())
        else:
            event.add("dtstart", datetime.now())
        
        if end_time:
            try:
                event.add("dtend", dateparser.parse(end_time))
            except Exception:
                event.add("dtend", datetime.now() + timedelta(hours=1))
        else:
            event.add("dtend", datetime.now() + timedelta(hours=1))
        
        event.add("dtstamp", datetime.now())
        
        cal.add_component(event)
        
        out = Path(ical_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "wb") as f:
            f.write(cal.to_ical())
        
        return json.dumps({
            "success": True,
            "result": f"Created calendar event: {summary}",
            "error": None,
            "metadata": {"path": ical_path, "summary": summary}
        })
    
    except Exception as e:
        return json.dumps({
            "success": False, "result": None,
            "error": f"Failed to create iCal file: {e}"
        })