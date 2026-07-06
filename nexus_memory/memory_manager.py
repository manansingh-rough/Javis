from functools import lru_cache;from nexus_memory.vector_store import get_vector_store;from nexus_memory.session_context import get_session_context
class MemoryManager:
    def __init__(self):self._vs=get_vector_store();self._sc=get_session_context()
    def store_episodic(self,task,outcome,tools,dur,success,sid,comp="simple"):
        d=f"Task:{task}\nOutcome:{outcome}\nTools:{tools}\nDuration:{dur}ms"
        self._vs.add_memory("agent_memory",f"ep_{sid}_{hash(task)}",d,{"task":task,"outcome":outcome,"success":success,"tools":str(tools),"duration_ms":dur,"session_id":sid,"complexity":comp})
    def store_preference(self,fact):self._vs.add_memory("user_preferences",f"pref_{hash(fact)}",f"Fact:{fact}",{"fact":fact})
    def query_memories(self,q,n=5):return self._vs.query("agent_memory",q,n)
    def query_preferences(self,n=3):return self._vs.query("user_preferences","user preferences",n)
    def query_synthesized_tools(self,q,n=3):return self._vs.query("synthesized_tools",q,n)
    def query_all(self,q,n=3):return self._vs.query("agent_memory",q,n)
    def get_context(self):return{"working_memory":self._sc.get("working_memory",[]),"last_task":self._sc.get_last_task_summary(),"task_history_count":len(self._sc.get("task_history",[]))}
@lru_cache(maxsize=1)
def get_memory_manager():return MemoryManager()
