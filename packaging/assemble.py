from pathlib import Path
import zipfile,shutil,hashlib,json,sys
root=Path(__file__).resolve().parents[1];downloads=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve();runtime=out/'runtime';runtime.mkdir(parents=True,exist_ok=True);manifest=[]
for p in [downloads/'python.zip',*sorted((downloads/'next-wheels').glob('*.whl')),downloads/'ffmpeg.zip']:
 manifest.append({'name':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
 with zipfile.ZipFile(p) as z:
  assert z.testzip() is None
  if p.suffix=='.whl':z.extractall(runtime/'Lib/site-packages')
  elif p.name=='python.zip':z.extractall(runtime)
  else:
   for name in z.namelist():
    n=Path(name).name;dest=out/'bin'/n if n in ('ffmpeg.exe','ffprobe.exe') else out/'licenses/ffmpeg'/n if n in ('LICENSE','README.txt') else None
    if dest:dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(name))
for p in (runtime/'Lib/site-packages/PySide6').rglob('*'):
 if p.is_file() and ('webengine' in p.name.lower() or p.suffix in ('.pyi','.h','.lib')):p.unlink()
(runtime/'python311._pth').write_text('python311.zip\n.\nLib/site-packages\n..\nimport site\n')
for n in ('kadrgo','assets','third_party'):shutil.copytree(root/n,out/n,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.so','*.dylib'))
for n in ('engine_worker.py','README_UZ.md','THIRD_PARTY_NOTICES.md'):shutil.copy2(root/n,out/n)
shutil.copy2(root/'packaging/bootstrap.py',out/'bootstrap.py');shutil.copy2(root/'assets/kadrgo.ico',out/'KADRGO.ico');shutil.copy2(root/'packaging/BOSHLASH.txt',out/'BOSHLASH.txt')
(out/'licenses/qt').mkdir(parents=True,exist_ok=True);shutil.copy2(downloads/'LGPL.txt',out/'licenses/qt/LGPL-3.0.txt');shutil.copy2(out/'licenses/ffmpeg/LICENSE',out/'licenses/qt/GPL-3.0.txt')
(out/'BUILD_INPUTS.json').write_text(json.dumps(manifest,indent=2));print('Payload bytes',sum(p.stat().st_size for p in out.rglob('*') if p.is_file()),flush=True)
