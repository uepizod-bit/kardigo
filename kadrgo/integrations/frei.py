from pathlib import Path
import ctypes as C,os
ROOT=Path(__file__).resolve().parents[2]/'assets/frei0r'
class Info(C.Structure):
 _fields_=[('name',C.c_char_p),('author',C.c_char_p),('type',C.c_int),('colour',C.c_int),('abi',C.c_int),('major',C.c_int),('minor',C.c_int),('params',C.c_int),('explanation',C.c_char_p)]
class Param(C.Structure):_fields_=[('name',C.c_char_p),('type',C.c_int),('explanation',C.c_char_p)]
def plugins():return {p.stem:p for p in (ROOT/'filter').glob('*.dll' if os.name=='nt' else '*.so')}
class Filter:
 def __init__(self,path,w,h,values=''):
  self.lib=C.CDLL(str(Path(path).resolve()));l=self.lib;self.instance=None
  l.f0r_init.restype=C.c_int
  if not l.f0r_init():raise ValueError('Plugin init xatosi')
  l.f0r_get_plugin_info.argtypes=[C.POINTER(Info)];self.info=Info();l.f0r_get_plugin_info(C.byref(self.info))
  if self.info.type!=0 or self.info.colour not in (0,1,2):raise ValueError('Faqat FILTER turi qo‘llanadi')
  l.f0r_construct.argtypes=[C.c_uint,C.c_uint];l.f0r_construct.restype=C.c_void_p;self.instance=l.f0r_construct(w,h)
  if not self.instance:raise ValueError('Plugin yaratilmagan')
  l.f0r_update.argtypes=[C.c_void_p,C.c_double,C.c_void_p,C.c_void_p];l.f0r_destruct.argtypes=[C.c_void_p];l.f0r_get_param_info.argtypes=[C.POINTER(Param),C.c_int];l.f0r_set_param_value.argtypes=[C.c_void_p,C.c_void_p,C.c_int]
  if values:
   import math
   for i,text in enumerate(values.split('|')):
    if i>=self.info.params:raise ValueError('Parametrlar soni oshgan')
    vals=[float(x) for x in text.split('/')];pi=Param();l.f0r_get_param_info(C.byref(pi),i);n={0:1,1:1,2:3,3:2}.get(pi.type)
    if n!=len(vals) or not all(math.isfinite(x) and 0<=x<=1 for x in vals):raise ValueError('Parametr turi/qiymati xato')
    v=(C.c_double*n)(*vals);l.f0r_set_param_value(self.instance,C.cast(v,C.c_void_p),i)
 def apply(self,image,t):
  import cv2,numpy as np
  a=cv2.cvtColor(image,cv2.COLOR_BGR2BGRA if self.info.colour==0 else cv2.COLOR_BGR2RGBA);b=np.empty_like(a);self.lib.f0r_update(self.instance,t,a.ctypes.data,b.ctypes.data);return cv2.cvtColor(b,cv2.COLOR_BGRA2BGR if self.info.colour==0 else cv2.COLOR_RGBA2BGR)
 def close(self):
  if self.instance:self.lib.f0r_destruct(self.instance);self.instance=None
  self.lib.f0r_deinit()
def render(r,out):
 import cv2,subprocess
 from fractions import Fraction
 from ..media.probe import FFMPEG,CREATE_NO_WINDOW,probe
 from .worker import ff
 paths=plugins()
 if r['model'] not in paths:raise ValueError('Bu OS uchun plugin yo‘q')
 m=probe(r['source']);cap=cv2.VideoCapture(r['source']);ok,img=cap.read()
 if not ok:raise ValueError('Media o‘qilmadi')
 h,w=img.shape[:2];f=Filter(paths[r['model']],w,h,r.get('parameters',''));enc=None
 try:
  if m.kind=='image':p=out/'frei0r.png';cv2.imwrite(str(p),f.apply(img,0));return {'kind':'media','files':[str(p)]}
  raw=out/'raw.mp4';dest=out/'frei0r.mp4';enc=subprocess.Popen([FFMPEG,'-v','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f'{w}x{h}','-r',m.fps,'-i','pipe:0','-an','-c:v','libx264','-threads','2','-crf','17','-pix_fmt','yuv420p',str(raw)],stdin=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=CREATE_NO_WINDOW);n=0
  while ok:enc.stdin.write(f.apply(img,n/float(Fraction(m.fps))).tobytes());n+=1;ok,img=cap.read()
  enc.stdin.close();err=enc.stderr.read();code=enc.wait()
  if code:raise RuntimeError(err.decode(errors='replace'))
  ff(['-i',str(raw),'-i',r['source'],'-map','0:v','-map','1:a?','-c:v','copy','-c:a','aac','-shortest',str(dest)]);return {'kind':'media','files':[str(dest)]}
 finally:
  cap.release();f.close()
  if enc:
   if enc.poll() is None:enc.kill()
   enc.wait()
   if enc.stderr:enc.stderr.close()
