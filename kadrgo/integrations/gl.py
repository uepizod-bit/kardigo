from pathlib import Path
import os,re,subprocess,math
ROOT=Path(__file__).resolve().parents[2]/'assets/gl-transitions/transitions'
VERT='#version 330\nin vec2 position;out vec2 uv;void main(){uv=(position+1.)*.5;gl_Position=vec4(position,0.,1.);}'
HEAD='#version 330\nuniform sampler2D texFrom;uniform sampler2D texTo;uniform float progress;uniform float ratio;in vec2 uv;out vec4 fragColor;vec4 getFromColor(vec2 p){return texture(texFrom,vec2(p.x,1.-p.y));}vec4 getToColor(vec2 p){return texture(texTo,vec2(p.x,1.-p.y));}\n'
def shaders():return sorted(p.stem for p in ROOT.glob('*.glsl'))
def context():
 import moderngl
 return moderngl.create_standalone_context(require=330,**({} if os.name=='nt' else {'backend':'egl'}))
def program(ctx,name,w,h):
 import numpy as np
 if name not in shaders():raise ValueError('Shader yo‘q')
 s=(ROOT/(name+'.glsl')).read_text();p=ctx.program(vertex_shader=VERT,fragment_shader=HEAD+s+'\nvoid main(){fragColor=transition(uv);}')
 for k,v in [('texFrom',0),('texTo',1),('ratio',w/h)]:
  if k in p:p[k].value=v
 for typ,k,expr in re.findall(r'uniform\s+(float|int|bool|vec[234]|ivec[234])\s+(\w+)\s*;\s*//\s*=\s*([^\n;]+)',s):
  if k not in p:continue
  try:
   if typ=='bool':v=expr.strip()=='true'
   elif typ.startswith(('vec','ivec')):
    vals=[float(x.strip()) for x in expr[expr.index('(')+1:expr.rindex(')')].split(',')];vals=vals*int(typ[-1]) if len(vals)==1 else vals;v=tuple(int(x) if typ.startswith('i') else x for x in vals)
   else:v=int(expr.strip()) if typ=='int' else float(expr.strip())
   p[k].value=v
  except (ValueError,TypeError):pass
 b=ctx.buffer(np.array([-1,-1,1,-1,-1,1,1,1],dtype='f4').tobytes());return p,ctx.simple_vertex_array(p,b,'position'),b

def render(r,out):
 import moderngl
 from ..media.probe import FFMPEG,CREATE_NO_WINDOW,probe
 w,h=int(r.get('width',640)),int(r.get('height',360));duration=float(r.get('duration',1));fps=30
 if not all(128<=v<=4096 and v%2==0 for v in (w,h)) or not math.isfinite(duration) or not .1<=duration<=3:raise ValueError('O‘lcham/vaqt noto‘g‘ri')
 count=max(2,round(duration*fps));ctx=context();p,vao,b=program(ctx,r['model'],w,h);tex=[ctx.texture((w,h),3) for _ in range(2)];fbo=ctx.simple_framebuffer((w,h),components=3);fbo.use();ctx.viewport=(0,0,w,h);children=[];enc=None
 try:
  for i,path in enumerate((r['source'],r['second'])):
   m=probe(path);args=['-loop','1'] if m.kind=='image' else (['-ss',str(max(0,m.duration-duration))] if i==0 else [])
   children.append(subprocess.Popen([FFMPEG,'-v','error','-nostdin','-threads','1',*args,'-i',path,'-t',str(duration),'-an','-vf',f'fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=CREATE_NO_WINDOW));tex[i].use(i);tex[i].filter=(moderngl.LINEAR,moderngl.LINEAR)
  target=out/'transition.mp4';enc=subprocess.Popen([FFMPEG,'-v','error','-nostdin','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{w}x{h}','-r',str(fps),'-i','pipe:0','-an','-vf','vflip','-c:v','libx264','-threads','2','-crf','17','-pix_fmt','yuv420p',str(target)],stdin=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=CREATE_NO_WINDOW)
  last=[None,None]
  for n in range(count):
   for i,reader in enumerate(children):
    data=reader.stdout.read(w*h*3)
    if len(data)==w*h*3:last[i]=data
    if last[i] is None:raise RuntimeError('Manba kadrini o‘qib bo‘lmadi')
    tex[i].write(last[i])
   if 'progress' in p:p['progress'].value=n/(count-1)
   vao.render(moderngl.TRIANGLE_STRIP);enc.stdin.write(fbo.read(components=3,alignment=1))
  enc.stdin.close();err=enc.stderr.read();code=enc.wait()
  if code:raise RuntimeError(err.decode(errors='replace')[-1500:])
 finally:
  for child in children+([enc] if enc else []):
   if child.poll() is None:child.kill()
   child.wait()
   for stream in (child.stdin,child.stdout,child.stderr):
    if stream and not stream.closed:stream.close()
  for obj in (vao,b,p,fbo,*tex):obj.release()
  ctx.release()
 return {'kind':'media','files':[str(target)],'note':'GL o‘tish video asseti, 30fps; audio alohida.'}
