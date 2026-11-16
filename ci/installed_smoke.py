"""Executed by the installed embedded interpreter, without adding the checkout to sys.path."""
import os,sys,runpy,tempfile
from pathlib import Path
root=Path(os.environ['KADRGO_INSTALLED_ROOT']).resolve()
import kadrgo
assert Path(kadrgo.__file__).resolve().is_relative_to(root), kadrgo.__file__
from kadrgo.integrations.runtime import configure
configure()
os.environ['QT_MEDIA_BACKEND']='ffmpeg'
# No FFmpeg PATH or KADRGO_FFMPEG override: exercise packaged binary discovery.
from kadrgo.media.probe import FFMPEG,FFPROBE
assert Path(FFMPEG).resolve()==root/'bin/ffmpeg.exe',FFMPEG
assert Path(FFPROBE).resolve()==root/'bin/ffprobe.exe',FFPROBE
import subprocess
subprocess.run([FFMPEG,'-v','error','-f','lavfi','-i','color=s=160x128:d=0.1','-frames:v','1','-f','null','-'],check=True)
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer,QThreadPool
from kadrgo.core.vault import Vault
from kadrgo.core.hardware import detect
from kadrgo.ui.main_window import MainWindow
app=QApplication([])
with tempfile.TemporaryDirectory() as tmp:
 vault=Vault(tmp)
 win=MainWindow(vault,detect(),None);win.show();QTimer.singleShot(2000,win.close);QTimer.singleShot(10000,app.quit);app.exec()
 assert QThreadPool.globalInstance().waitForDone(30000), "Background work did not finish"
 vault.close()
print('Installed embedded runtime, FFmpeg discovery and Qt window: PASS')
