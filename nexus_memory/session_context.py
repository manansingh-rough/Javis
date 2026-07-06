import json,time,threading;from functools import lru_cache
from nexus_config.settings import get_settings,APP_ROOT
class SessionContext:
    def __init__(self):
        self._s=get_settings();self._f=APP_ROOT/"session_context.json";self._lock=threading.Lock()
        self._d=self._load();self._dirty=False;threading.Thread(target=self._save_loop,daemon=True).start()
    def _load(self):
        if self._f.exists():
            try:return json.loads(self._f.read_text(encoding="utf-8"))
            except:pass
        return{"preferences":{},"task_history":[],"last_session":None,"workflow_count":0,"synthesized_tools":[]}
    def save(self):
        with self._lock:self._f.write_text(json.dumps(self._d,indent=2,default=str),encoding="utf-8");self._dirty=False
    def _save_loop(self):
        while True:time.sleep(60);self._dirty and self.save()
    def get(self,k,d=None):
        with self._lock:return self._d.get(k,d)
    def set(self,k,v):
        with self._lock:self._d[k]=v;self._dirty=True
    def add_task(self,td):
        with self._lock:
            self._d.setdefault("task_history",[]).append(td);h=self._s.WORKFLOW_HISTORY_LENGTH
            if len(self._d["task_history"])>h:self._d["task_history"]=self._d["task_history"][-h:];self._dirty=True
    def get_last_task_summary(self):
        h=self.get("task_history",[])
        if not h:return None
        l=h[-1];return f"'{l.get('task','')}' - {'success' if l.get('success') else 'failed'}"
@lru_cache(maxsize=1)
def get_session_context():return SessionContext()
