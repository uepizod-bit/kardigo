import os,sys,traceback
from pathlib import Path
root=Path(__file__).resolve().parent;sys.path.insert(0,str(root))
from kadrgo.integrations.runtime import configure
configure()
os.environ['PATH']=str(root/'bin')+os.pathsep+os.environ.get('PATH','')
os.environ['KADRGO_FFMPEG']=str(root/'bin/ffmpeg.exe');os.environ['KADRGO_FFPROBE']=str(root/'bin/ffprobe.exe')
os.environ.setdefault('QT_MEDIA_BACKEND','ffmpeg')
data=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'KADRGO Studio 6';data.mkdir(parents=True,exist_ok=True)
os.environ.setdefault('KADRGO_VAULT_DIR',str(data/'Vault'))
try:
 from kadrgo.app import run
 raise SystemExit(run())
except Exception:
 p=data/'startup-error.log';p.write_text(traceback.format_exc(),encoding='utf-8')
 if os.name=='nt':
  import ctypes
  ctypes.windll.user32.MessageBoxW(0,'Ochilmadi. Xato jurnali: '+str(p),'KADRGO Studio',16)
 raise
