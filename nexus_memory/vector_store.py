from functools import lru_cache; from nexus_config.settings import get_settings,APP_ROOT
class VectorStore:
    def __init__(self):
        self._s=get_settings();self._client=None;self._collections={};self._embedder=None
    def _gc(self):
        if self._client is None:
            import chromadb
            try:self._client=chromadb.PersistentClient(path=str(APP_ROOT/"db"))
            except:self._client=chromadb.EphemeralClient()
        return self._client
    def _ge(self):
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer
                cache=APP_ROOT/"db"/"model_cache";cache.mkdir(parents=True,exist_ok=True)
                self._embedder=SentenceTransformer("all-MiniLM-L6-v2",cache_folder=str(cache))
            except:self._embedder=None
        return self._embedder
    def get_collection(self,name):
        if name not in self._collections:
            c=self._gc()
            try:self._collections[name]=c.get_collection(name)
            except:self._collections[name]=c.create_collection(name)
        return self._collections[name]
    def add_memory(self,col,doc_id,document,metadata=None):
        c=self.get_collection(col);e=self._ge()
        if e:c.add(ids=[doc_id],embeddings=[e.encode(document).tolist()],documents=[document],metadatas=[metadata or {}])
        else:c.add(ids=[doc_id],documents=[document],metadatas=[metadata or {}])
    def query(self,col,qt,n=5):
        c=self.get_collection(col);e=self._ge()
        if e:return c.query(query_embeddings=[e.encode(qt).tolist()],n_results=n)
        return c.query(query_texts=[qt],n_results=n)
@lru_cache(maxsize=1)
def get_vector_store():return VectorStore()
