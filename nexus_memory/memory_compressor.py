"""
NEXUS AI v4.0 — Memory compression: summarize old episodic memories to prevent ChromaDB bloat.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Periodically compresses old memories by summarizing groups of similar memories
into single consolidated entries. Reduces vector store size while preserving
semantic information.
"""

import logging
import time
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from functools import lru_cache

from nexus_config.settings import get_settings
from nexus_memory.vector_store import get_vector_store

logger = logging.getLogger("nexus.memory.compressor")


COMPRESSION_INTERVAL_HOURS: int = 24
"""How often to run compression (in hours)."""

MAX_MEMORIES_BEFORE_COMPRESSION: int = 500
"""Trigger compression when collection exceeds this many entries."""

MEMORIES_PER_SUMMARY: int = 20
"""Number of old memories to summarize into one entry."""

MAX_SUMMARY_LENGTH_CHARS: int = 500
"""Maximum length of a compressed summary."""


def should_compress(collection: str = "agent_memory") -> bool:
    """
    Check if memory compression should run based on collection size and last run time.
    
    Args:
        collection: ChromaDB collection name to check.
    
    Returns:
        True if compression is needed.
    """
    try:
        store = get_vector_store()
        col = store.get_collection(collection)
        count = col.count()
        
        if count < MAX_MEMORIES_BEFORE_COMPRESSION:
            return False
        
        # Check last compression time from metadata
        last_run = _get_last_compression_time(collection)
        if last_run:
            hours_since = (datetime.now(timezone.utc) - last_run).total_seconds() / 3600
            if hours_since < COMPRESSION_INTERVAL_HOURS:
                return False
        
        return True
    except Exception as e:
        logger.warning(f"Error checking compression need: {e}")
        return False


def _get_last_compression_time(collection: str) -> Optional[datetime]:
    """
    Get the timestamp of the last compression run for a collection.
    
    Args:
        collection: Collection name.
    
    Returns:
        Datetime of last compression, or None if never compressed.
    """
    try:
        store = get_vector_store()
        col = store.get_collection(collection)
        # Check if we have a compression marker
        results = col.get(
            where={"type": "compression_marker"},
            limit=1,
        )
        if results and results.get("metadatas"):
            ts = results["metadatas"][0].get("compressed_at")
            if ts:
                return datetime.fromisoformat(ts)
    except Exception:
        pass
    return None


def compress_collection(collection: str = "agent_memory") -> Dict[str, Any]:
    """
    Compress old memories in a collection by summarizing groups.
    
    Strategy:
    1. Find the oldest MEMORIES_PER_SUMMARY memories
    2. Group them by similarity (same task type, same tools used)
    3. Create a summary entry for each group
    4. Delete the original entries
    5. Store the summary with a reference count
    
    Args:
        collection: ChromaDB collection name to compress.
    
    Returns:
        Dict with compression stats: entries_before, entries_after, groups_created.
    """
    stats = {"entries_before": 0, "entries_after": 0, "groups_created": 0, "errors": []}
    
    try:
        store = get_vector_store()
        col = store.get_collection(collection)
        
        count = col.count()
        stats["entries_before"] = count
        
        if count < MAX_MEMORIES_BEFORE_COMPRESSION:
            stats["entries_after"] = count
            return stats
        
        # Get all entries sorted by timestamp (oldest first)
        all_entries = col.get(limit=count)
        
        if not all_entries or not all_entries.get("metadatas"):
            stats["entries_after"] = count
            return stats
        
        # Group entries by task type
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for i, meta in enumerate(all_entries["metadatas"]):
            task_type = meta.get("complexity", "unknown")
            if task_type not in groups:
                groups[task_type] = []
            
            groups[task_type].append({
                "id": all_entries["ids"][i] if all_entries.get("ids") else f"idx_{i}",
                "metadata": meta,
                "document": all_entries["documents"][i] if all_entries.get("documents") else "",
            })
        
        # Compress each group
        for task_type, entries in groups.items():
            if len(entries) < 5:
                continue  # Skip small groups
            
            # Take oldest entries for compression
            entries_to_compress = entries[:MEMORIES_PER_SUMMARY]
            
            # Create summary
            summary = _create_summary(entries_to_compress, task_type)
            if not summary:
                continue
            
            # Store summary
            store.store_memory(
                text=summary["document"],
                metadata=summary["metadata"],
                collection_name=collection,
            )
            
            # Delete original entries
            ids_to_delete = [e["id"] for e in entries_to_compress if e["id"]]
            if ids_to_delete:
                try:
                    col.delete(ids=ids_to_delete)
                except Exception as e:
                    stats["errors"].append(f"Delete error: {e}")
            
            stats["groups_created"] += 1
        
        # Write compression marker
        try:
            col.add(
                documents=["COMPRESSION_MARKER"],
                metadatas=[{
                    "type": "compression_marker",
                    "compressed_at": datetime.now(timezone.utc).isoformat(),
                    "entries_before": stats["entries_before"],
                }],
                ids=[f"compression_{int(time.time())}"],
            )
        except Exception as e:
            stats["errors"].append(f"Marker error: {e}")
        
        stats["entries_after"] = col.count()
        logger.info(
            f"Compressed {collection}: {stats['entries_before']} → {stats['entries_after']} "
            f"entries ({stats['groups_created']} groups)"
        )
        
    except Exception as e:
        logger.error(f"Compression failed for {collection}: {e}")
        stats["errors"].append(str(e))
    
    return stats


def _create_summary(
    entries: List[Dict[str, Any]], task_type: str
) -> Optional[Dict[str, Any]]:
    """
    Create a summary entry from a group of similar memories.
    
    Args:
        entries: List of memory entries to summarize.
        task_type: The task type for this group.
    
    Returns:
        Dict with 'document' and 'metadata' keys, or None if failed.
    """
    if not entries:
        return None
    
    # Extract common patterns
    tools_used = set()
    successes = 0
    total_duration = 0.0
    task_descriptions = []
    
    for entry in entries:
        meta = entry.get("metadata", {})
        if meta.get("success"):
            successes += 1
        total_duration += meta.get("duration_ms", 0)
        tools = meta.get("tools", [])
        if isinstance(tools, list):
            tools_used.update(tools)
        task_descriptions.append(entry.get("document", "")[:100])
    
    # Build summary document
    summary_doc = (
        f"[Compressed Summary] {len(entries)} {task_type} tasks. "
        f"Success rate: {successes}/{len(entries)}. "
        f"Tools: {', '.join(sorted(tools_used)[:5])}. "
        f"Avg duration: {total_duration/len(entries):.0f}ms."
    )
    
    # Truncate if too long
    if len(summary_doc) > MAX_SUMMARY_LENGTH_CHARS:
        summary_doc = summary_doc[:MAX_SUMMARY_LENGTH_CHARS] + "..."
    
    return {
        "document": summary_doc,
        "metadata": {
            "task": f"compressed_{task_type}",
            "outcome": f"Summary of {len(entries)} {task_type} tasks",
            "success": successes > len(entries) / 2,
            "tools": list(tools_used),
            "duration_ms": total_duration / len(entries),
            "synthesis_triggered": False,
            "session_id": "compressed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "complexity": task_type,
            "compressed": True,
            "original_count": len(entries),
        },
    }


def run_scheduled_compression() -> Dict[str, Any]:
    """
    Run compression on all collections that need it.
    
    Called periodically by the background services thread.
    
    Returns:
        Dict mapping collection names to their compression stats.
    """
    results = {}
    collections = ["agent_memory", "user_preferences"]
    
    for collection in collections:
        if should_compress(collection):
            try:
                results[collection] = compress_collection(collection)
            except Exception as e:
                logger.error(f"Failed to compress {collection}: {e}")
                results[collection] = {"error": str(e)}
    
    return results