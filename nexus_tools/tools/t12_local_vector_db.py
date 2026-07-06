"""
NEXUS AI v4.0 — Tool 12: Agent-facing ChromaDB memory interface.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Provides agent-friendly access to ChromaDB vector memory: store memories,
search semantically, and manage memory collections.
"""

import json
import logging
import time
from typing import Optional, List, Dict, Any

logger = logging.getLogger("nexus.tool.local_vector_db")


def local_vector_db(
    action: str,
    collection: str = "agent_memory",
    text: Optional[str] = None,
    query: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    n_results: int = 5,
    document_id: Optional[str] = None,
) -> str:
    """
    Store and retrieve information from the agent's vector memory.
    
    Use this tool when: The user asks to remember something for later, search
    past conversations, or store information for future reference.
    
    Args:
        action: One of: "store", "search", "delete", "list_collections", "count"
        collection: ChromaDB collection name. Default: "agent_memory".
                   Other collections: "user_preferences", "synthesized_tools"
        text: Text content to store (for "store" action).
        query: Search query (for "search" action).
        metadata: Dict of metadata to store alongside the text.
        n_results: Number of search results to return (1-20).
        document_id: ID of document to delete (for "delete" action).
    
    Returns:
        JSON string with keys:
          - success (bool): Whether the operation succeeded.
          - result (any): Search results or confirmation message.
          - error (str or null): Error message if failed.
    
    Examples:
        >>> local_vector_db("store", text="Python 3.12 features: ...", metadata={"topic": "python"})
        >>> local_vector_db("search", query="Python features", n_results=3)
        >>> local_vector_db("list_collections")
    """
    start = time.perf_counter()
    n_results = min(max(n_results, 1), 20)
    
    try:
        from nexus_memory.vector_store import get_vector_store
        store = get_vector_store()
        
        if action == "store":
            if not text:
                return json.dumps({"success": False, "result": None, "error": "Text required for store action"})
            
            store.store_memory(
                collection=collection,
                text=text,
                metadata=metadata or {},
            )
            return json.dumps({
                "success": True,
                "result": f"Stored in collection '{collection}'",
                "error": None,
                "metadata": {"text_length": len(text), "collection": collection}
            })
        
        elif action == "search":
            if not query:
                return json.dumps({"success": False, "result": None, "error": "Query required for search action"})
            
            results = store.search_memory(
                collection=collection,
                query=query,
                n_results=n_results,
            )
            
            return json.dumps({
                "success": True,
                "result": results,
                "error": None,
                "metadata": {"count": len(results), "collection": collection}
            })
        
        elif action == "delete":
            if not document_id:
                return json.dumps({"success": False, "result": None, "error": "document_id required for delete action"})
            
            store.delete_memory(
                collection=collection,
                document_id=document_id,
            )
            return json.dumps({
                "success": True,
                "result": f"Deleted document {document_id} from '{collection}'",
                "error": None
            })
        
        elif action == "list_collections":
            collections = store.list_collections()
            return json.dumps({
                "success": True,
                "result": collections,
                "error": None,
                "metadata": {"count": len(collections)}
            })
        
        elif action == "count":
            count = store.count(collection)
            return json.dumps({
                "success": True,
                "result": count,
                "error": None,
                "metadata": {"collection": collection}
            })
        
        else:
            return json.dumps({
                "success": False, "result": None,
                "error": f"Unknown action: '{action}'. Valid: store, search, delete, list_collections, count"
            })
    
    except ImportError:
        return json.dumps({
            "success": False, "result": None,
            "error": "ChromaDB not installed. Install with: pip install chromadb"
        })
    except Exception as e:
        logger.error(f"local_vector_db error: {e}", exc_info=True)
        return json.dumps({
            "success": False, "result": None,
            "error": f"{type(e).__name__}: {e}"
        })