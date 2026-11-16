"""Real Qt window lifecycle check; no claim of manual usability/GPU validation."""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer, QThreadPool
from PySide6.QtWidgets import QApplication
from kadrgo.core.vault import Vault
from kadrgo.core.hardware import detect
from kadrgo.ui.main_window import MainWindow
app=QApplication([])
with tempfile.TemporaryDirectory() as tmp:
    vault=Vault(tmp)
    win=MainWindow(vault,detect(),None);win.show()
    QTimer.singleShot(2000,win.close)
    QTimer.singleShot(10000,app.quit)
    app.exec()
    assert QThreadPool.globalInstance().waitForDone(30000), "Background work did not finish"
    vault.close()
print('Qt window opened and closed successfully')
