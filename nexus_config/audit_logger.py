# NEXUS AI v4.0 - Enterprise Audit Logger
# JSON-lines rotating audit log with @audited decorator

import json, logging, os, threading, time, asyncio, uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Dict, Any, Callable, List, TypeVar
from functools import lru_cache, wraps
from nexus_config.settings import get_settings, APP_ROOT

SENSITIVE_PATTERNS = frozenset(["api_key","apikey","password","passwd","token","secret","auth",
    "authorization","credential","private_key","access_key","bearer","oauth","jwt","cookie",
    "session_id","code","content","body","payload","key","email","phone","credit","pin",])
MAX_LOG_STR = 200

@dataclass
class AuditEntry:
    timestamp: str; session_id: str; module: str; function_name: str
    event_type: str; data: Dict[str, Any]; duration_ms: float; success: bool
    error: Optional[str]; thread_id: int; process_id: int

def auto_redact(data, depth=0):
    if depth>10: return "[DEPTH_EXCEEDED]"
    if isinstance(data,dict):
        return {k:f"[REDACTED:{len(str(v))}]" if any(p in str(k).lower() for p in SENSITIVE_PATTERNS) else auto_redact(v,depth+1) for k,v in data.items()}
    if isinstance(data,(list,tuple)): return [auto_redact(i,depth+1) for i in data]
    if isinstance(data,str): return f"[CONTENT:{len(data)}]" if depth>0 and len(data)>MAX_LOG_STR else data
    if isinstance(data,(int,float,bool)) or data is None: return data
    s=str(data); return f"[OBJ:{type(data).__name__}:{len(s)}]" if len(s)>MAX_LOG_STR else s

class NexusAuditLogger:
    def __init__(self):
        self._s=get_settings();self._sid=str(uuid.uuid4());self._lock=threading.Lock()
        self._log=logging.getLogger("nexus.audit");self._log.setLevel(logging.DEBUG);self._log.propagate=False
        lp=APP_ROOT/"logs"/"nexus_audit.jsonl"
        fh=RotatingFileHandler(str(lp),maxBytes=self._s.AUDIT_LOG_MAX_BYTES,backupCount=self._s.AUDIT_LOG_BACKUP_COUNT,encoding="utf-8",delay=True)
        fh.setLevel(logging.DEBUG);fh.setFormatter(logging.Formatter("%(message)s"));self._log.addHandler(fh)
        ch=logging.StreamHandler();ch.setLevel(logging.WARNING);ch.setFormatter(logging.Formatter("[AUDIT] %(message)s"));self._log.addHandler(ch)
        threading.Thread(target=self._flush_loop,daemon=True).start()
    @property
    def session_id(self): return self._sid
    def log(self,event_type,data,module="nexus",function_name="unknown",duration_ms=0.0,success=True,error=None):
        try:
            e=AuditEntry(timestamp=datetime.now(timezone.utc).astimezone().isoformat(),session_id=self._sid,
                module=module,function_name=function_name,event_type=event_type,data=auto_redact(data),
                duration_ms=round(duration_ms,3),success=success,error=error,
                thread_id=threading.current_thread().ident or 0,process_id=os.getpid())
            with self._lock:
                m=json.dumps(asdict(e),ensure_ascii=False,default=str);self._log.debug(m)
                if not success or event_type=="SECURITY_REJECT":self._log.warning(m)
        except:pass
    def _flush_loop(self):
        while True:
            time.sleep(30)
            try:
                for h in self._log.handlers:
                    if hasattr(h,"flush"):h.flush()
            except:pass
    def get_recent_entries(self,n=10):
        try:
            lp=APP_ROOT/"logs"/"nexus_audit.jsonl"
            if not lp.exists():return[]
            with open(lp,"r",encoding="utf-8",errors="replace") as f:lines=f.readlines()
            es=[]
            for line in reversed(lines):
                line=line.strip()
                if not line:continue
                try:es.append(json.loads(line))
                except:continue
                if len(es)>=n:break
            return list(reversed(es))
        except:return[]

F=TypeVar("F",bound=Callable[...,Any])
def audited(event_type,module=""):
    def deco(func):
        fm=module or getattr(func,"__module__","unknown");fn=func.__name__
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def w(*a,**kw):
                l=get_audit_logger();s=time.perf_counter();e=None
                try:return await func(*a,**kw)
                except Exception as ex:e=f"{type(ex).__name__}:{ex}";raise
                finally:l.log(event_type,{"a":len(a),"k":list(kw.keys())},fm,fn,(time.perf_counter()-s)*1000,e is None,e)
            return w
        else:
            @wraps(func)
            def w(*a,**kw):
                l=get_audit_logger();s=time.perf_counter();e=None
                try:return func(*a,**kw)
                except Exception as ex:e=f"{type(ex).__name__}:{ex}";raise
                finally:l.log(event_type,{"a":len(a),"k":list(kw.keys())},fm,fn,(time.perf_counter()-s)*1000,e is None,e)
            return w
    return deco

@lru_cache(maxsize=1)
def get_audit_logger():return NexusAuditLogger()