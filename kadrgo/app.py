"""Grafik dasturni ishga tushirish."""
from __future__ import annotations

import sys
from typing import Optional

from . import APP_NAME


def run(open_path: Optional[str] = None, vault_dir: Optional[str] = None) -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .core import hardware
    from .core.vault import Vault
    from .media import probe as mprobe
    from .ui.main_window import MainWindow
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    from pathlib import Path
    from PySide6.QtGui import QIcon,QFontDatabase
    ico = Path(__file__).resolve().parents[1] / "assets" / "kadrgo.png"
    if ico.exists():
        app.setWindowIcon(QIcon(str(ico)))
    r = mprobe.run([mprobe.FFMPEG, "-version"]) if mprobe.shutil.which(mprobe.FFMPEG) or mprobe.os.path.exists(mprobe.FFMPEG) else None
    if r is None or r.returncode != 0:
        QMessageBox.critical(None, APP_NAME, "FFmpeg topilmadi.\n\nWindows:  winget install Gyan.FFmpeg\n"
                             "macOS:    brew install ffmpeg\nso'ng dasturni qayta ishga tushiring.")
        return 2
    root=Path(__file__).resolve().parents[1]
    for font in (root/'assets/fonts').glob('*/*.ttf'):QFontDatabase.addApplicationFont(str(font))
    vault = Vault(vault_dir)
    import shutil
    for folder,dest in [('fonts','Fonts'),('sfx','SFX')]:
        for source in (root/'assets'/folder).rglob('*'):
            if source.is_file():
                target=vault.library/dest/source.relative_to(root/'assets'/folder)
                if not target.exists():target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    hw = hardware.detect()
    win = MainWindow(vault, hw, open_path)
    win.show()
    win.timeline.fit_all()
    return app.exec()
