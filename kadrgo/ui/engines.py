from pathlib import Path
import os,sys,json,uuid,subprocess
from PySide6.QtCore import Qt,QProcess,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QListWidget,QLineEdit,QComboBox,QPlainTextEdit,QPushButton,QWidget,QSplitter,QFileDialog,QMessageBox,QScrollArea
from ..core import edit
ROOT=Path(__file__).resolve().parents[2]
ENGINES={
 'whisper':('Faster-Whisper','Lokal subtitr. Tiny model ichida; o‘zbekcha real nutqda tekshiring.'),
 'scenes':('PySceneDetect','Sahna chegaralaridan taymlayn markerlari.'),
 'ocio':('OpenColorIO / ACES','33³ SDR LUT. 0–1 diapazon; to‘liq HDR/float pipeline emas.'),
 'gl':('GL Transitions','Original GLSL → video asset, 30fps, audio alohida. OpenGL 3.3 kerak.'),
 'frei0r':('frei0r','Native FILTER host. Natija yangi media. Mixer/generatorlar qo‘llanmaydi. Windows DLL ijrosi sinalmagan.'),
 'upscale':('Real-ESRGAN','NCNN executable/model ichida. Vulkan GPU kerak. Yuz detallarini original bilan solishtiring.'),
 'qwen':('Qwen-VL / Ollama','Mahalliy Ollama + ko‘rish modeli kerak. Faqat kadrlar asosidagi montaj taklifi; audio yuborilmaydi.'),
 'comfy':('ComfyUI','Mahalliy server + API-format workflow kerak. Input yo‘llari va modellar ComfyUI ichida avval sozlanadi. Partner API nodlari tashqi xizmatga yuborishi mumkin.'),
 'sam':('SAM 2','Alohida Python + SAM checkpoint/config kerak. Natija PNG maskalar; avtomatik kompoziting yo‘q.'),
 'deepfilter':('DeepFilterNet','Mos alohida Python muhiti kerak. 48 kHz WAV chiqadi. Real model inference sinalmagan.'),
 'ofx':('OpenFX / Natron','Tashqi .ntp loyiha ko‘prigi; KADRGO ichki OFX host emas.'),
 'mlt':('MLT / melt','Tashqi .mlt loyiha ko‘prigi; KADRGO taymlayni MLT emas.')}
LINKS={'whisper':'SYSTRAN/faster-whisper','scenes':'Breakthrough/PySceneDetect','ocio':'AcademySoftwareFoundation/OpenColorIO','gl':'gl-transitions/gl-transitions','frei0r':'dyne/frei0r','upscale':'xinntao/Real-ESRGAN-ncnn-vulkan','qwen':'QwenLM/Qwen3-VL','comfy':'Comfy-Org/ComfyUI','sam':'facebookresearch/sam2','deepfilter':'Rikorose/DeepFilterNet','ofx':'NatronGitHub/openfx-misc','mlt':'mltframework/mlt'}
class EnginesDialog(QDialog):
 def __init__(self,win,key='whisper'):
  super().__init__(win);self.win=win;self.proc=None;self.result=None;self.req=None;self.settings_path=win.vault.root/'engines.json'
  try:self.settings=json.loads(self.settings_path.read_text())
  except (OSError,ValueError):self.settings={}
  self.setWindowTitle('KADRGO · AI / Rang markazi');self.resize(1140,800);outer=QVBoxLayout(self);title=QLabel('KADRGO  /  AI VA RANG MARKAZI');title.setStyleSheet('font-size:22px;font-weight:bold;color:#F6B84A;padding:12px');outer.addWidget(title)
  split=QSplitter();self.list=QListWidget();self.keys=list(ENGINES)
  for k in self.keys:self.list.addItem(ENGINES[k][0])
  self.list.setMinimumWidth(240);self.list.setSpacing(5);self.list.setStyleSheet('QListWidget::item{padding:14px;border:1px solid #303746;border-radius:5px;} QListWidget::item:selected{background:#3e3220;color:#F6B84A;}');split.addWidget(self.list)
  pane=QWidget();layout=QVBoxLayout(pane);self.title=QLabel();self.title.setStyleSheet('font-size:20px;font-weight:bold');layout.addWidget(self.title);self.note=QLabel();self.note.setWordWrap(True);layout.addWidget(self.note);self.form=QFormLayout();layout.addLayout(self.form)
  row=QHBoxLayout();self.go=QPushButton('Ishga tushirish');self.go.setStyleSheet('background:#F6B84A;color:#111318;font-weight:bold;padding:12px');self.go.clicked.connect(self.start);self.stop=QPushButton('Bekor qilish');self.stop.clicked.connect(self.cancel);web=QPushButton('Rasmiy loyiha');web.clicked.connect(lambda:QDesktopServices.openUrl(QUrl('https://github.com/'+LINKS[self.key])))
  for b in (self.go,self.stop,web):row.addWidget(b)
  layout.addLayout(row);self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumBlockCount(1500);layout.addWidget(self.log,1);self.apply=QPushButton('Natijani loyihaga olish');self.apply.setEnabled(False);self.apply.clicked.connect(self.apply_result);layout.addWidget(self.apply);folder=QPushButton('Natija papkasi');folder.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(self.req['output'] if self.req else str(win.vault.root))));layout.addWidget(folder)
  scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(pane);split.addWidget(scroll);split.setSizes([250,850]);outer.addWidget(split,1);self.list.currentRowChanged.connect(self.select);self.list.setCurrentRow(self.keys.index(key))
 def field(self,k,label,value='',pick=False):
  v=QLineEdit(str(value));self.fields[k]=v
  if pick:
   h=QWidget();row=QHBoxLayout(h);row.setContentsMargins(0,0,0,0);row.addWidget(v);b=QPushButton('…');b.setMaximumWidth(35)
   def choose():
    result=QFileDialog.getExistingDirectory(self,label) if k=='models' else QFileDialog.getOpenFileName(self,label)[0]
    if result:v.setText(result)
   b.clicked.connect(choose);row.addWidget(b);self.form.addRow(label,h)
  else:self.form.addRow(label,v)
 def combo(self,k,label,values,default):
  v=QComboBox();v.addItems(values);v.setCurrentText(self.saved.get(k,default));self.fields[k]=v;self.form.addRow(label,v)
 def select(self,index):
  self.key=self.keys[index];self.saved=self.settings.get(self.key,{});self.fields={};self.result=None;self.apply.setEnabled(False)
  while self.form.rowCount():self.form.removeRow(0)
  self.title.setText(ENGINES[self.key][0]);self.note.setText(ENGINES[self.key][1])
  def field(k,label,default='',pick=False):self.field(k,label,self.saved.get(k,default),pick)
  if self.key=='whisper':field('model','Model / papka',ROOT/'assets/models/whisper-tiny');field('language','Til','uz')
  elif self.key=='qwen':field('endpoint','Ollama API','http://127.0.0.1:11434');field('model','O‘rnatilgan model','qwen3-vl:4b');field('brief','Topshiriq','30 soniyali Buxoro treyleri')
  elif self.key=='comfy':field('endpoint','ComfyUI API','http://127.0.0.1:8188');field('workflow','API workflow JSON','',True)
  elif self.key=='sam':field('python','SAM o‘rnatilgan Python','',True);field('checkpoint','SAM 2.1 checkpoint','',True);field('model','Config','configs/sam2.1/sam2.1_hiera_t.yaml');field('x','Obyekt nuqtasi X (0–1)','.5');field('y','Obyekt nuqtasi Y (0–1)','.5')
  elif self.key=='deepfilter':field('python','DeepFilterNet o‘rnatilgan Python','',True)
  elif self.key=='upscale':field('executable','NCNN executable',ROOT/'assets/realesrgan/realesrgan-ncnn-vulkan.exe',True);field('models','Models papkasi',ROOT/'assets/realesrgan/models',True);field('model','Model nomi','realesrgan-x4plus')
  elif self.key=='gl':
   from ..integrations.gl import shaders
   self.combo('model','Shader',shaders(),'Fade');field('second','Ikkinchi media','',True);field('duration','Davomiylik (0.1–3 s)','1');field('width','Kenglik',str(self.win.project.settings.width));field('height','Balandlik',str(self.win.project.settings.height))
  elif self.key=='frei0r':
   from ..integrations.frei import plugins
   self.combo('model','Filter',sorted(plugins()),'softglow');field('parameters','Parametrlar: 0–1, |, r/g/b','')
  elif self.key=='ocio':
   try:
    from ..integrations.color import config
    c=config();self.combo('input_space','Kirish profili',list(c.getColorSpaceNames()),'sRGB - Display');self.combo('display','Chiqish displeyi',list(c.getDisplays()),'Rec.1886 Rec.709 - Display');field('view','View','ACES 1.0 - SDR Video')
   except Exception as e:self.note.setText(str(e))
  elif self.key in ('ofx','mlt'):field('executable','Natron / melt executable','',True);field('project_file','Tashqi loyiha','',True)
 def start(self):
  if self.proc:return
  try:
   vals={k:v.currentText() if isinstance(v,QComboBox) else v.text().strip() for k,v in self.fields.items()};self.settings[self.key]=vals;tmp=self.settings_path.with_suffix('.tmp');tmp.write_text(json.dumps(self.settings,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,self.settings_path)
   if self.key in ('ofx','mlt'):
    if not Path(vals['executable']).is_file() or not Path(vals['project_file']).is_file():raise ValueError('Dastur va loyiha faylini tanlang')
    ok,pid=QProcess.startDetached(vals['executable'],[vals['project_file']])
    if not ok:raise RuntimeError('Tashqi dastur ochilmadi')
    self.log.appendPlainText('Tashqi dasturga yuborildi.');return
   clip=self.win._sel();a=self.win.project.assets[clip.asset_id] if clip else None
   if self.key not in ('comfy','qwen','ocio') and not a:raise ValueError('Taymlayn klipini tanlang')
   out=self.win.vault.root/'Results'/(self.key+'-'+uuid.uuid4().hex[:10]);out.mkdir(parents=True)
   self.req={'engine':self.key,'source':a.path if a else '', 'vault':str(self.win.vault.root),'output':str(out),'project':self.win.project.to_dict(),'assets':[{'id':x.id,'path':x.path,'duration':x.duration} for x in self.win.project.assets.values() if x.kind=='video'],**vals}
   self.snapshot=self.win.project.to_dict();self.clip=clip.clone() if clip else None;self.identity=id(self.win.project);path=out/'request.json';path.write_text(json.dumps(self.req,ensure_ascii=False),encoding='utf-8');self.result_path=out/'result.json'
   exe=vals.get('python') or sys.executable
   if Path(exe).name.lower()=='pythonw.exe':exe=str(Path(exe).with_name('python.exe'))
   self.result=None;self.apply.setEnabled(False);self.log.clear();self.list.setEnabled(False);self.go.setEnabled(False);self.proc=QProcess(self);proc=self.proc;proc.setProcessChannelMode(QProcess.MergedChannels);proc.readyReadStandardOutput.connect(lambda:self.log.appendPlainText(bytes(proc.readAllStandardOutput()).decode(errors='replace')));proc.errorOccurred.connect(lambda _:self.log.appendPlainText(proc.errorString()));proc.finished.connect(self.finished);proc.start(exe,[str(ROOT/'engine_worker.py'),str(path)])
   if not proc.waitForStarted(3000):self.finished(1)
  except Exception as e:QMessageBox.warning(self,'Engine',str(e))
 def finished(self,code,*_):
  proc=self.proc
  if not proc:return
  self.proc=None;self.list.setEnabled(True);self.go.setEnabled(True)
  if code==0 and self.result_path.exists():self.result=json.loads(self.result_path.read_text(encoding='utf-8'));self.log.appendPlainText(json.dumps(self.result,ensure_ascii=False,indent=2));self.apply.setEnabled(self.result['kind'] in ('captions','scenes','plan','media','lut'))
  else:self.log.appendPlainText('Jarayon tugamadi; yuqoridagi xatoni tekshiring. Loyiha o‘zgarmadi.')
  proc.deleteLater()
 def cancel(self):
  if self.proc:
   pid=int(self.proc.processId())
   if os.name=='nt':subprocess.run(['taskkill','/F','/T','/PID',str(pid)],capture_output=True,creationflags=0x08000000)
   else:
    import signal
    try:
     if os.getpgid(pid)==pid:os.killpg(pid,signal.SIGTERM)
     else:self.proc.kill()
    except ProcessLookupError:pass
   if self.key=='comfy':self.log.appendPlainText('ComfyUI serverida ish davom etishi mumkin; ComfyUI ichida Stop bosing.')
 def apply_result(self):
  if not self.result:return
  if id(self.win.project)!=self.identity or self.win.project.to_dict()!=self.snapshot:return QMessageBox.warning(self,'Loyiha','Tahlil vaqtida loyiha o‘zgargan. Qayta tahlil qiling.')
  r=self.result;p=self.win.project;c=self.clip
  try:
   if r['kind']=='media':
    for f in r['files']:self.win.add_asset(f)
   elif r['kind']=='lut':
    selected=self.win._sel()
    if not selected:raise ValueError('LUT uchun klip tanlang')
    self.win.do('OCIO transform',edit.add_effect,selected.id,'lut',{'file':r['file'],'intensity':1.0})
   elif r['kind']=='plan':
    from ..ai.plan import apply_plan
    apply_plan(self.win.history,r['plan'],self.win.timeline.playhead)
   elif r['kind']=='captions':
    with self.win.history.transaction('AI: subtitr'):
     for s in r['segments']:
      lo=max(float(s['start']),c.src_in/float(p.fps));hi=min(float(s['end']),(c.src_in+c.src_frames)/float(p.fps))
      if hi>lo:
       start=c.start+round((lo*float(p.fps)-c.src_in)/c.speed);end=c.start+round((hi*float(p.fps)-c.src_in)/c.speed)
       if end>start:edit.add_cue(p,start,end,s['text'])
   elif r['kind']=='scenes':
    from ..core.model import Marker
    with self.win.history.transaction('Sahna markerlari'):
     for s in r['scenes']:
      f=p.sec_to_frame(s['start'])
      if c.src_in<=f<c.src_in+c.src_frames:p.markers.append(Marker(c.start+round((f-c.src_in)/c.speed),'Sahna','scene'))
   self.win.refresh();self.apply.setEnabled(False);self.log.appendPlainText('Loyihaga olindi. Tahrirlar Ctrl+Z bilan qaytariladi; import media kutubxonada qoladi.')
  except Exception as e:QMessageBox.warning(self,'Natija',str(e))
 def closeEvent(self,event):
  if self.proc:QMessageBox.information(self,'Engine','Avval jarayonni bekor qiling va tugashini kuting.');event.ignore()
  else:event.accept()
