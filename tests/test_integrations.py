import sys,json,tempfile,subprocess,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from kadrgo.integrations import worker
from kadrgo.integrations.color import bake
from kadrgo.integrations.gl import render
from kadrgo.fx.colorspace import read_cube
from kadrgo.core.model import Project,Settings
from kadrgo.core import edit
from kadrgo.media.probe import probe
from kadrgo.ai.plan import validate_plan
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.out=Path(self.tmp.name);self.src=self.out/'input video.mp4'
  subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=red:s=160x128:r=12:d=1','-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-threads','1','-c:a','aac',str(self.src)],check=True)
 def tearDown(self):self.tmp.cleanup()
 def test_ocio(self):
  p=bake({'input_space':'sRGB - Display','display':'Rec.1886 Rec.709 - Display','view':'ACES 1.0 - SDR Video'},self.out/'t.cube',9);self.assertEqual(read_cube(p)['size'],9)
  worker.ff(['-i',str(self.src),'-vf',f'lut3d={p}','-frames:v','1',str(self.out/'result.png')]);self.assertTrue((self.out/'result.png').is_file())
 def test_scenes(self):
  r=worker.scenes({'source':str(self.src)},self.out);self.assertTrue(r['scenes']);self.assertAlmostEqual(r['scenes'][0]['start'],0)
 def test_gl_video(self):
  r=render({'source':str(self.src),'second':str(self.src),'model':'CrossZoom','duration':.2,'width':160,'height':128},self.out);self.assertTrue(probe(r['files'][0]).has_video)
 def test_local_url(self):
  for s in ['https://example.com','http://127.0.0.1.evil.test','http://u:p@localhost']:
   with self.assertRaises(ValueError):worker.local(s)
  self.assertEqual(worker.local('http://127.0.0.1:8188/'),'http://127.0.0.1:8188')
 def test_comfy_protocol(self):
  p=self.out/'api.json';p.write_text(json.dumps({'1':{'class_type':'SaveImage','inputs':{}}}))
  def response(base,path,data=None,**kwargs):return {'prompt_id':'own'} if path=='/prompt' else {'own':{'outputs':{},'status':{'status_str':'success'}}}
  with patch.object(worker,'api',side_effect=response):r=worker.comfy({'endpoint':'http://127.0.0.1:8188','workflow':str(p)},self.out)
  self.assertEqual(r['prompt_id'],'own')
 def test_qwen_protocol(self):
  p=Project('test',Settings(160,128,'12/1'));a=probe(str(self.src));p.assets[a.id]=a;plan={'track':'V1','items':[{'asset':a.id,'src_in':0,'src_out':.5}]}
  with patch.object(worker,'api',return_value={'message':{'content':json.dumps(plan)}}):r=worker.qwen({'endpoint':'http://127.0.0.1:11434','model':'test','assets':[{'id':a.id,'path':a.path,'duration':a.duration}],'project':p.to_dict()},self.out)
  self.assertEqual(r['plan'],plan);plan['items'][0]['src_out']=float('nan');self.assertTrue(validate_plan(p,plan))
 def test_whisper_real_model(self):
  path=self.out/'silence.wav';worker.ff(['-f','lavfi','-i','anullsrc=r=16000:cl=mono','-t','1',str(path)])
  r=worker.whisper({'source':str(path),'vault':str(self.out),'model':str(ROOT/'assets/models/whisper-tiny'),'language':'uz'},self.out);self.assertEqual(r['segments'],[])
 def test_original_guard(self):
  from kadrgo.render.exporter import export,ExportError
  p=Project('test',Settings(160,128,'12/1'));a=probe(str(self.src));p.assets[a.id]=a;edit.add_clip(p,'V1',a.id,0,0,12);before=self.src.read_bytes()
  with self.assertRaises(ExportError):export(p,str(self.src),'draft',prefer_hw=False)
  self.assertEqual(before,self.src.read_bytes())
if __name__=='__main__':unittest.main()
