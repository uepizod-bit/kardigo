import sys,os,json,traceback
from pathlib import Path
root=Path(__file__).resolve().parent;sys.path.insert(0,str(root))
from kadrgo.integrations.runtime import configure
configure()
if os.name!='nt':
 try:os.setsid()
 except OSError:pass
r=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'));extra=Path(r['vault'])/'Engines'/r['engine']
if extra.exists():sys.path.insert(0,str(extra))
os.environ['PATH']=str(root/'bin')+os.pathsep+os.environ.get('PATH','')
try:
 from kadrgo.integrations.worker import execute
 execute(sys.argv[1])
except Exception:traceback.print_exc();raise SystemExit(1)
