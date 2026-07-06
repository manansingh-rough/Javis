"""
NEXUS AI v4.0 — Tool 18: Data analysis with Pandas.
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Loads, analyzes, transforms, and exports data from CSV, Excel, JSON, and
other formats. Provides statistical summaries, filtering, and plotting.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, Union

logger = logging.getLogger("nexus.tool.data_analyzer")


def data_analyzer(
    action: str,
    path: Optional[str] = None,
    data: Optional[Union[List[Dict], str]] = None,
    query: Optional[str] = None,
    output_path: Optional[str] = None,
    output_format: str = "csv",
    columns: Optional[List[str]] = None,
    group_by: Optional[str] = None,
    agg_function: str = "mean",
) -> str:
    """
    Analyze data using Pandas: load, summarize, filter, transform, and export.
    
    Use this tool when: The user asks to analyze a CSV or Excel file, get
    statistics about data, filter/transform data, or convert between formats.
    
    Args:
        action: One of: "load", "summary", "filter", "groupby", "sort",
                "head", "describe", "convert", "plot", "query"
        path: Path to data file (CSV, Excel, JSON, Parquet).
        data: Inline data as list of dicts or JSON string.
        query: Filter query or pandas query expression.
        output_path: Path to save output file.
        output_format: Output format for "convert": "csv", "json", "excel", "parquet".
        columns: Specific columns to include.
        group_by: Column name to group by (for "groupby" action).
        agg_function: Aggregation function: "mean", "sum", "count", "min", "max", "median".
    
    Returns:
        JSON string with keys:
          - success (bool): Whether the operation succeeded.
          - result (any): Analysis results.
          - error (str or null): Error message if failed.
    """
    start = time.perf_counter()
    
    try:
        import pandas as pd
        
        df = None
        
        # Load data from path or inline
        if path:
            p = Path(path)
            if not p.exists():
                return json.dumps({"success": False, "result": None, "error": f"File not found: {path}"})
            
            ext = p.suffix.lower()
            try:
                if ext == ".csv":
                    df = pd.read_csv(p)
                elif ext in (".xls", ".xlsx"):
                    df = pd.read_excel(p)
                elif ext == ".json":
                    df = pd.read_json(p)
                elif ext == ".parquet":
                    df = pd.read_parquet(p)
                elif ext == ".feather":
                    df = pd.read_feather(p)
                else:
                    return json.dumps({"success": False, "result": None, "error": f"Unsupported format: {ext}. Supported: .csv, .xlsx, .json, .parquet, .feather"})
            except Exception as e:
                return json.dumps({"success": False, "result": None, "error": f"Failed to load {path}: {e}"})
        
        elif data:
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError:
                    return json.dumps({"success": False, "result": None, "error": "Invalid JSON data string"})
            df = pd.DataFrame(data)
        
        else:
            return json.dumps({"success": False, "result": None, "error": "Either path or data parameter required"})
        
        if df is None or df.empty:
            return json.dumps({"success": False, "result": None, "error": "No data loaded"})
        
        # Limit columns if specified
        if columns:
            available = [c for c in columns if c in df.columns]
            if available:
                df = df[available]
        
        # Execute the requested action
        if action == "load":
            info = {
                "rows": len(df),
                "columns": len(df.columns),
                "column_names": list(df.columns),
                "dtypes": {str(k): str(v) for k, v in df.dtypes.items()},
                "memory_usage_kb": round(df.memory_usage(deep=True).sum() / 1024, 1),
                "has_null": bool(df.isnull().any().any()),
            }
            return json.dumps({"success": True, "result": info, "error": None})
        
        elif action == "summary":
            summary = {
                "rows": len(df),
                "columns": len(df.columns),
                "column_info": {},
            }
            for col in df.columns:
                col_data = {
                    "dtype": str(df[col].dtype),
                    "null_count": int(df[col].isnull().sum()),
                    "null_percent": round(float(df[col].isnull().mean() * 100), 1),
                    "unique_values": int(df[col].nunique()),
                }
                if pd.api.types.is_numeric_dtype(df[col]):
                    col_data.update({
                        "min": float(df[col].min()) if not df[col].isnull().all() else None,
                        "max": float(df[col].max()) if not df[col].isnull().all() else None,
                        "mean": float(df[col].mean()) if not df[col].isnull().all() else None,
                        "median": float(df[col].median()) if not df[col].isnull().all() else None,
                        "std": float(df[col].std()) if not df[col].isnull().all() else None,
                    })
                elif pd.api.types.is_datetime64_any_dtype(df[col]):
                    col_data.update({
                        "min": str(df[col].min()) if not df[col].isnull().all() else None,
                        "max": str(df[col].max()) if not df[col].isnull().all() else None,
                    })
                summary["column_info"][col] = col_data
            
            return json.dumps({"success": True, "result": summary, "error": None})
        
        elif action == "describe":
            desc = df.describe(include="all").to_dict()
            # Convert numpy types to Python types
            clean_desc = {}
            for col, stats in desc.items():
                clean_desc[str(col)] = {str(k): v if not pd.isna(v) else None for k, v in stats.items()}
            return json.dumps({"success": True, "result": clean_desc, "error": None})
        
        elif action == "head":
            n = int(query or 5)
            head_df = df.head(min(n, 100))
            return json.dumps({"success": True, "result": head_df.to_dict(orient="records"), "error": None, "metadata": {"rows": len(head_df)}})
        
        elif action == "filter":
            if not query:
                return json.dumps({"success": False, "result": None, "error": "Filter query required"})
            try:
                filtered = df.query(query)
                return json.dumps({
                    "success": True,
                    "result": filtered.to_dict(orient="records"),
                    "error": None,
                    "metadata": {"original_rows": len(df), "filtered_rows": len(filtered)}
                })
            except Exception as e:
                return json.dumps({"success": False, "result": None, "error": f"Filter error: {e}"})
        
        elif action == "sort":
            if not query:
                return json.dumps({"success": False, "result": None, "error": "Column name required for sort"})
            ascending = True
            if query.startswith("-"):
                ascending = False
                query = query[1:]
            if query not in df.columns:
                return json.dumps({"success": False, "result": None, "error": f"Column '{query}' not found"})
            sorted_df = df.sort_values(by=query, ascending=ascending)
            return json.dumps({
                "success": True,
                "result": sorted_df.to_dict(orient="records"),
                "error": None,
                "metadata": {"sort_by": query, "ascending": ascending}
            })
        
        elif action == "groupby":
            if not group_by:
                return json.dumps({"success": False, "result": None, "error": "group_by column required"})
            if group_by not in df.columns:
                return json.dumps({"success": False, "result": None, "error": f"Column '{group_by}' not found"})
            
            agg_map = {
                "mean": "mean", "sum": "sum", "count": "count",
                "min": "min", "max": "max", "median": "median",
            }
            agg = agg_map.get(agg_function, "mean")
            
            numeric_cols = df.select_dtypes(include="number").columns.tolist()
            grouped = df.groupby(group_by)[numeric_cols].agg(agg).reset_index()
            
            return json.dumps({
                "success": True,
                "result": grouped.to_dict(orient="records"),
                "error": None,
                "metadata": {"group_by": group_by, "agg_function": agg, "groups": grouped.shape[0]}
            })
        
        elif action == "convert":
            if not output_path:
                return json.dumps({"success": False, "result": None, "error": "output_path required"})
            
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            
            fmt = output_format.lower()
            try:
                if fmt == "csv":
                    df.to_csv(out, index=False)
                elif fmt == "json":
                    df.to_json(out, orient="records", indent=2)
                elif fmt == "excel":
                    df.to_excel(out, index=False)
                elif fmt == "parquet":
                    df.to_parquet(out, index=False)
                else:
                    return json.dumps({"success": False, "result": None, "error": f"Unsupported format: {fmt}"})
                
                return json.dumps({"success": True, "result": f"Exported {len(df)} rows to {output_path}", "error": None})
            except Exception as e:
                return json.dumps({"success": False, "result": None, "error": f"Export failed: {e}"})
        
        elif action == "query":
            if not query:
                return json.dumps({"success": False, "result": None, "error": "Query required"})
            try:
                result = df.query(query)
                return json.dumps({
                    "success": True,
                    "result": result.to_dict(orient="records"),
                    "error": None,
                    "metadata": {"rows": len(result), "query": query}
                })
            except Exception as e:
                return json.dumps({"success": False, "result": None, "error": f"Query error: {e}"})
        
        else:
            return json.dumps({
                "success": False, "result": None,
                "error": f"Unknown action: '{action}'. Valid: load, summary, describe, head, filter, sort, groupby, convert, query"
            })
    
    except ImportError:
        return json.dumps({
            "success": False, "result": None,
            "error": "Pandas not installed. Install with: pip install pandas openpyxl"
        })
    except Exception as e:
        logger.error(f"data_analyzer error: {e}", exc_info=True)
        return json.dumps({
            "success": False, "result": None,
            "error": f"{type(e).__name__}: {e}"
        })