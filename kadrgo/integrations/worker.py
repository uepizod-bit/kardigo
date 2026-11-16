from pathlib import Path
import json,os,subprocess,urllib.request,urllib.parse,base64,uuid,time,math

def local(url):
 p=urllib.parse.urlsplit(url)
 if p.scheme!='http' or p.hostname not in ('localhost','127.0.0.1','::1') or p.username or p.password or p.query or p.fragment:raise ValueError('Faqat mahalliy HTTP API manzili ruxsat etiladi')
 return url.rstrip('/')
def api(url,path,data=None,timeout=120):
 req=urllib.request.Request(local(url)+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=timeout) as r:return json.load(r)
def ff(args,capture=False):
 from ..media.probe import FFMPEG,CREATE_NO_WINDOW
 return subprocess.run([FFMPEG,'-v','error','-nostdin','-y','-threads','2',*args],check=True,capture_output=capture,creationflags=CREATE_NO_WINDOW)
def frame(src,t,path):
 ff(['-ss',str(t),'-i',src,'-frames:v','1','-vf','scale=480:-2',str(path)]);return str(path)
def scenes(r,out):
 from scenedetect import detect,AdaptiveDetector
 from ..media.probe import probe
 rows=[{'start':a.get_seconds(),'end':b.get_seconds()} for a,b in detect(r['source'],AdaptiveDetector())]
 return {'kind':'scenes','scenes':rows or [{'start':0,'end':probe(r['source']).duration}]}
def whisper(r,out):
 import numpy as np
 from faster_whisper import WhisperModel
 model=WhisperModel(r['model'],device='cpu',compute_type='int8',download_root=str(Path(r['vault'])/'Models/Whisper'))
 audio=ff(['-i',r['source'],'-vn','-ar','16000','-ac','1','-f','f32le','pipe:1'],True).stdout
 segments,_=model.transcribe(np.frombuffer(audio,dtype=np.float32).copy(),language=r.get('language','uz') or None,vad_filter=True)
 return {'kind':'captions','segments':[{'start':float(s.start),'end':float(s.end),'text':s.text.strip()} for s in segments if s.text.strip()]}
def qwen(r,out):
 imgs=[];assets=r.get('assets',[])[:8]
 for i,a in enumerate(assets):
  for j,t in enumerate([a['duration']*.2,a['duration']*.7]):
   p=out/f'{i}-{j}.jpg';frame(a['path'],t,p);imgs.append(base64.b64encode(p.read_bytes()).decode())
 if not imgs:raise ValueError('Avval video import qiling')
 brief='Return ONLY JSON. Schema: {"track":"V1","items":[{"asset":"id","src_in":0.0,"src_out":1.0,"reason":"Uzbek reason"}]}. Only listed existing assets, valid source times. Frames are two per asset in listed order. Do not invent dialogue. Assets:'+json.dumps([{k:a[k] for k in ('id','duration')} for a in assets])+'. Task:'+r.get('brief','30 soniyali treyler')
 data=api(r['endpoint'],'/api/chat',{'model':r['model'],'messages':[{'role':'user','content':brief,'images':imgs}],'format':'json','stream':False},1200)
 plan=json.loads(data['message']['content'])
 from ..ai.plan import validate_plan
 from ..core.model import Project
 errors=validate_plan(Project.from_dict(r['project']),plan)
 if errors:raise ValueError('; '.join(errors))
 return {'kind':'plan','plan':plan}
def comfy(r,out):
 graph=json.loads(Path(r['workflow']).read_text(encoding='utf-8'))
 if not isinstance(graph,dict) or not graph or not all(isinstance(v,dict) and 'class_type' in v for v in graph.values()):raise ValueError('ComfyUI API-format workflow JSON kerak')
 response=api(r['endpoint'],'/prompt',{'prompt':graph,'client_id':'kadrgo-'+uuid.uuid4().hex})
 if response.get('node_errors'):raise ValueError(str(response['node_errors'])[:1500])
 pid=response['prompt_id'];result=None
 for _ in range(3600):
  result=api(r['endpoint'],'/history/'+urllib.parse.quote(pid)).get(pid)
  if result:break
  time.sleep(1)
 if not result:raise TimeoutError('ComfyUI 60 daqiqa ichida tugamadi')
 if result.get('status',{}).get('status_str')=='error':raise RuntimeError(str(result['status']))
 files=[]
 for node in result.get('outputs',{}).values():
  for kind in ('images','videos','gifs','audio'):
   for e in node.get(kind,[]):
    if not isinstance(e,dict) or 'filename' not in e:continue
    target=out/(uuid.uuid4().hex[:6]+'_'+Path(e['filename']).name)
    args=urllib.parse.urlencode({k:e[k] for k in ('filename','subfolder','type') if k in e})
    with urllib.request.urlopen(local(r['endpoint'])+'/view?'+args,timeout=120) as response,target.open('wb') as f:
     import shutil;shutil.copyfileobj(response,f)
    files.append(str(target))
 return {'kind':'media','files':files,'prompt_id':pid}
def deepfilter(r,out):
 from df.enhance import init_df,load_audio,enhance,save_audio
 source=out/'input.wav';ff(['-i',r['source'],'-vn','-ar','48000',str(source)])
 model,state,*_=init_df(log_file=None);audio,_=load_audio(str(source),sr=state.sr());result=enhance(model,state,audio);target=out/'dialog-clean.wav';save_audio(str(target),result,state.sr())
 return {'kind':'media','files':[str(target)]}
def upscale(r,out):
 from ..media.probe import probe,CREATE_NO_WINDOW
 exe=Path(r['executable']);models=Path(r['models']);name=r['model']
 if not exe.is_file() or not (models/(name+'.param')).is_file() or not (models/(name+'.bin')).is_file():raise ValueError('NCNN executable va mos model fayllari kerak')
 src=out/'frames';dst=out/'upscaled';src.mkdir();dst.mkdir();meta=probe(r['source'])
 ff(['-i',r['source'],'-an',*(['-frames:v','1'] if meta.kind=='image' else ['-fps_mode','passthrough']),str(src/'%08d.png')])
 subprocess.run([str(exe),'-i',str(src),'-o',str(dst),'-m',str(models),'-n',name,'-s','4','-t','128','-f','png'],check=True,creationflags=CREATE_NO_WINDOW)
 if meta.kind=='image':return {'kind':'media','files':[str(p) for p in dst.glob('*.png')]}
 target=out/'upscaled.mp4';ff(['-framerate',meta.fps,'-i',str(dst/'%08d.png'),'-i',r['source'],'-map','0:v','-map','1:a?','-c:v','libx264','-crf','17','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(target)])
 return {'kind':'media','files':[str(target)]}
def sam(r,out):
 import torch,numpy as np,cv2
 from sam2.build_sam import build_sam2_video_predictor
 checkpoint=Path(r['checkpoint'])
 if not checkpoint.is_file():raise ValueError('SAM checkpoint kerak')
 allowed=['configs/sam2.1/sam2.1_hiera_'+n+'.yaml' for n in ('t','s','b+','l')]
 if r['model'] not in allowed:raise ValueError('SAM config mos emas')
 frames=out/'frames';masks=out/'masks';frames.mkdir();masks.mkdir();ff(['-i',r['source'],'-an','-start_number','0',str(frames/'%05d.jpg')]);image=cv2.imread(str(frames/'00000.jpg'));h,w=image.shape[:2]
 x,y=float(r.get('x',.5)),float(r.get('y',.5))
 if not all(math.isfinite(v) and 0<=v<=1 for v in (x,y)):raise ValueError('X/Y 0–1 bo‘lsin')
 predictor=build_sam2_video_predictor(r['model'],str(checkpoint),device='cuda' if torch.cuda.is_available() else 'cpu')
 with torch.inference_mode():
  state=predictor.init_state(video_path=str(frames),offload_video_to_cpu=True)
  predictor.add_new_points_or_box(inference_state=state,frame_idx=0,obj_id=1,points=np.array([[x*w,y*h]],dtype=np.float32),labels=np.array([1],dtype=np.int32))
  for index,ids,logits in predictor.propagate_in_video(state):cv2.imwrite(str(masks/f'{index:05d}.png'),(logits[0,0]>0).cpu().numpy().astype(np.uint8)*255)
 return {'kind':'masks','directory':str(masks),'note':'PNG maskalar; taymlaynga kompoziting avtomatik ulanmagan.'}
def ocio(r,out):
 from .color import bake
 return {'kind':'lut','file':str(bake(r,out/'ocio.cube'))}
def execute(path):
 r=json.loads(Path(path).read_text(encoding='utf-8'));out=Path(r['output']).resolve();out.mkdir(parents=True,exist_ok=True)
 os.environ['HF_HOME']=str(Path(r['vault'])/'Models/HF');os.environ['XDG_CACHE_HOME']=str(Path(r['vault'])/'Models/Cache')
 from .gl import render as gl
 from .frei import render as frei
 result={'scenes':scenes,'whisper':whisper,'qwen':qwen,'comfy':comfy,'deepfilter':deepfilter,'upscale':upscale,'sam':sam,'ocio':ocio,'gl':gl,'frei0r':frei}[r['engine']](r,out)
 (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False),flush=True);return result
