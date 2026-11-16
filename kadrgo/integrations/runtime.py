import os,sys
from pathlib import Path
handles=[]
def configure():
 if os.name=='nt':
  for site in (Path(sys.executable).parent/'Lib/site-packages',Path(__file__).resolve().parents[2]/'runtime/Lib/site-packages'):
   for n in ('PySide6','shiboken6','ctranslate2','PyOpenColorIO/bin','onnxruntime/capi'):
    if (site/n).is_dir():handles.append(os.add_dll_directory(str(site/n)))
