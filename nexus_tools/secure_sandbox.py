# NEXUS AI v4.0 - 3-Layer Secure Sandbox
import ast,os,sys,subprocess,json,tempfile,threading,time
from pathlib import Path
from nexus_config.settings import get_settings,APP_ROOT

BANNED_IMPORTS=frozenset(["os","sys","subprocess","shutil","ctypes","socket","requests",
    "http","urllib","websocket","telnetlib","ftplib","smtplib","imaplib","poplib",
    "nntplib","asyncore","asynchat","signal","multiprocessing","threading","_thread",
    "importlib","inspect","code","codeop","codecs","compile","builtins","pickle","shelve",
    "marshal","dbm","anydbm","whichdb","dbhash","bsddb","dumbdbm","gdbm","sqlite3",
    "crypt","crypto","Crypto","ssl","hashlib","hmac","secrets","base64","binascii",
])

BANNED_ATTRS=frozenset([".__subclasses__",".__globals__",".__code__",".__closure__",
    ".__dict__",".__builtins__",".__import__",".__reduce__",".__reduce_ex__",
    ".__class__",".__bases__",".__mro__",".__self__",".__func__",
])

BANNED_CALLS=frozenset(["exec","eval","compile","__import__","open","input","breakpoint",
    "vars","globals","locals","dir","getattr","setattr","delattr","hasattr",
])

def ast_validate(code_str,max_nodes=500):
    try:
        tree=ast.parse(code_str)
    except SyntaxError as e:return {"valid":False,"error":f"Syntax: {e}"}
    class SecurityVisitor(ast.NodeVisitor):
        def __init__(self):
            self.node_count=0;self.errors=[]
        def visit(self,node):
            self.node_count+=1
            if self.node_count>max_nodes:self.errors.append("Node count exceeded");return
            if isinstance(node,ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in BANNED_IMPORTS:
                        self.errors.append(f"Banned import: {alias.name}")
            elif isinstance(node,ast.ImportFrom):
                if node.module and node.module.split(".")[0] in BANNED_IMPORTS:
                    self.errors.append(f"Banned import from: {node.module}")
            elif isinstance(node,ast.Attribute):
                attr=f".{node.attr}"
                if attr in BANNED_ATTRS:self.errors.append(f"Banned attribute: {attr}")
            elif isinstance(node,ast.Call):
                if isinstance(node.func,ast.Name) and node.func.id in BANNED_CALLS:
                    self.errors.append(f"Banned call: {node.func.id}")
            elif isinstance(node,ast.Subscript) and isinstance(node.slice,ast.Constant):
                if isinstance(node.slice.value,str):
                    for banned in ["__builtins__","__import__"]:
                        if banned in node.slice.value:self.errors.append(f"Banned string: {node.slice.value}")
            self.generic_visit(node)
    v=SecurityVisitor();v.visit(tree)
    if v.errors:return {"valid":False,"error":"; ".join(v.errors[:5]),"node_count":v.node_count}
    return {"valid":True,"node_count":v.node_count}

def run_in_subprocess(code_str,timeout=30,max_memory_mb=512):
    tmp=tempfile.NamedTemporaryFile(suffix=".py",mode="w",delete=False,dir=APP_ROOT/"temp",encoding="utf-8")
    tmp.write(code_str);tmp.close()
    tmp_path=tmp.name
    try:
        proc=subprocess.run([sys.executable,"-I","-s",tmp_path],capture_output=True,text=True,timeout=timeout)
        return {"success":proc.returncode==0,"stdout":proc.stdout,"stderr":proc.stderr,"returncode":proc.returncode}
    except subprocess.TimeoutExpired:
        return {"success":False,"stdout":"","stderr":"[TIMEOUT]","returncode":-1}
    except Exception as e:
        return {"success":False,"stdout":"","stderr":str(e),"returncode":-2}
    finally:
        try:os.unlink(tmp_path)
        except:pass

def sandbox_execute(code_str,timeout=None,max_memory_mb=None):
    s=get_settings();timeout=timeout or s.SANDBOX_TIMEOUT_SECONDS;max_memory_mb=max_memory_mb or s.SANDBOX_MAX_MEMORY_MB
    validation=ast_validate(code_str)
    if not validation["valid"]:return {"success":False,"result":None,"error":validation["error"],"stage":"ast"}
    sub_result=run_in_subprocess(code_str,timeout,max_memory_mb)
    return {"success":sub_result["success"],"result":sub_result["stdout"],"error":sub_result["stderr"],"stage":"subprocess"}
