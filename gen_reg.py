#!/usr/bin/env python3
import os
R = "e:\\Jarvis 2.0\\venv"
def w(p, c):
    f = os.path.join(R, p); os.makedirs(os.path.dirname(f), exist_ok=True)
    with open(f, "w", encoding="utf-8") as fh: fh.write(c); print(f"[OK] {p}")

w("nexus_tools/registry.py", '''# NEXUS AI v4.0 - Tool Registry
import inspect,json,logging,threading,os,sys
from pathlib import Path
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional
from nexus_config.settings import get_settings,APP_ROOT
from nexus_tools.secure_sandbox import sandbox_execute
from nexus_tools.rate_limiter import RateLimiter

class ToolRegistry:
    def __init__(self):
        self._s=get_settings();self._lock=threading.Lock()
        self._tools:Dict[str,Callable]={};self._tool_info:Dict[str,dict]={}
        self._plugin_tools:Dict[str,str]={};self._hot_reload=False
        self._limiter=RateLimiter(rate=self._s.GROQ_REQUESTS_PER_MINUTE)

    def register(self,func,source="core",name=None,description=None):
        n=name or func.__name__;d=description or (func.__doc__ or "").strip()
        with self._lock:
            self._tools[n]=func
            self._tool_info[n]={"name":n,"description":d,"source":source,"module":func.__module__}
            if source=="plugin":self._plugin_tools[n]=func.__module__
        logging.getLogger("nexus.registry").info(f"Registered tool: {n} ({source})")
        return n

    def unregister(self,name):
        with self._lock:
            self._tools.pop(name,None);self._tool_info.pop(name,None);self._plugin_tools.pop(name,None)

    def get_tool(self,name):
        with self._lock:return self._tools.get(name)

    def get_tool_info(self,name):
        with self._lock:return self._tool_info.get(name)

    def list_tools(self,source=None):
        with self._lock:
            if source:return {n:i for n,i in self._tool_info.items() if i["source"]==source}
            return dict(self._tool_info)

    def call_tool(self,name,**kwargs):
        func=self.get_tool(name)
        if not func:return {"success":False,"result":None,"error":f"Tool not found: {name}"}
        try:
            result=func(**kwargs)
            if isinstance(result,str):
                try:return json.loads(result)
                except:return{"success":True,"result":result}
            return result
        except Exception as e:return{"success":False,"result":None,"error":str(e)}

    def load_plugins(self):
        plugin_dir=APP_ROOT/"plugins"
        if not plugin_dir.exists():return 0
        count=0
        for f in sorted(plugin_dir.glob("*.py")):
            try:
                import importlib.util
                spec=importlib.util.spec_from_file_location(f.stem,str(f))
                if spec and spec.loader:
                    mod=importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    if hasattr(mod,"register"):
                        metas=mod.register(self)
                        count+=1
                        logging.getLogger("nexus.registry").info(f"Loaded plugin: {f.name}")
            except Exception as e:logging.getLogger("nexus.registry").error(f"Failed to load {f.name}: {e}")
        return count

    def load_synthesized_tools(self):
        syn_dir=APP_ROOT/"synthesized_tools"
        if not syn_dir.exists():return 0
        count=0
        for f in sorted(syn_dir.glob("*.py")):
            try:
                import importlib.util
                spec=importlib.util.spec_from_file_location(f"syn_{f.stem}",str(f))
                if spec and spec.loader:
                    mod=importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    for name,obj in inspect.getmembers(mod,inspect.isfunction):
                        if hasattr(obj,"__tool__") or getattr(obj,"_is_tool",False) or name.startswith("tool_"):
                            self.register(obj,source="synthesized",name=f.stem)
                            count+=1
            except:pass
        return count

    def refresh(self):
        self.load_synthesized_tools()
        self.load_plugins()

@lru_cache(maxsize=1)
def get_registry():return ToolRegistry()
''')
print("Registry done")
