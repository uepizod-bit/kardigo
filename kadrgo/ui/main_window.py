"""Asosiy oyna. Barcha tahrirlar History orqali (Ctrl+Z / Ctrl+Y); og'ir ishlar (preview, export) fon oqimida."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

from shiboken6 import isValid
from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
                               QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSlider,
                               QSpinBox, QSplitter, QStackedWidget, QTabWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..ai import audio_tools, plan as aiplan, subtitles, transcribe
from ..core import edit, storage
from ..core.edit import EditError
from ..core.hardware import Hardware
from ..core.history import History
from ..core.model import PRESETS, Project, Settings
from ..core.vault import Vault
from ..fx.catalog import EFFECTS, LOOKS, TRANSITIONS, normalize_params
from ..library import scanner
from ..media import probe as mprobe
from ..render import encoders, exporter
from .theme import STYLESHEET
from .timeline import TimelineWidget, timecode


class _Sig(QObject):
    done = Signal(object)
    error = Signal(str)
    progress = Signal(float, str)


class _Job(QRunnable):
    def __init__(self, fn: Callable, sig: _Sig):
        super().__init__()
        self.fn, self.sig = fn, sig

    def run(self):
        try:
            result=self.fn(self.sig)
            if isValid(self.sig):self.sig.done.emit(result)
        except exporter.Cancelled:
            if isValid(self.sig):self.sig.error.emit("Bekor qilindi")
        except Exception as e:                                  # noqa: BLE001
            if isValid(self.sig):self.sig.error.emit(str(e))


class ExportDialog(QDialog):
    def __init__(self, win: "MainWindow"):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Eksport")
        self.setMinimumWidth(460)
        self.token: Optional[exporter.CancelToken] = None
        lay = QFormLayout(self)
        self.preset = QComboBox()
        for k, v in exporter.PRESETS.items():
            self.preset.addItem(v.name, k)
        self.path = QLineEdit(str(win.vault.projects / f"{win.project.name}.mp4"))
        b = QPushButton("Tanlash...")
        b.clicked.connect(self._pick)
        row = QHBoxLayout()
        row.addWidget(self.path)
        row.addWidget(b)
        try:
            enc = ", ".join(encoders.available("h264"))
        except Exception:
            enc = "?"
        lay.addRow("Format:", self.preset)
        lay.addRow("Fayl:", row)
        lay.addRow("Kodeklar:", QLabel(enc))
        self.bar = QProgressBar()
        self.msg = QLabel("")
        self.go = QPushButton("Boshlash")
        self.go.clicked.connect(self.start)
        self.stop = QPushButton("Bekor qilish")
        self.stop.setEnabled(False)
        self.stop.clicked.connect(lambda: self.token and self.token.cancel())
        lay.addRow(self.bar)
        lay.addRow(self.msg)
        r2 = QHBoxLayout()
        r2.addWidget(self.go)
        r2.addWidget(self.stop)
        lay.addRow(r2)

    def _pick(self):
        f, _ = QFileDialog.getSaveFileName(self, "Eksport fayli", self.path.text(), "Video (*.mp4 *.mov)")
        if f:
            self.path.setText(f)

    def start(self):
        self.token = exporter.CancelToken()
        proj = self.win.project.clone()
        out, preset, tok = self.path.text(), self.preset.currentData(), self.token
        hw = self.win.hw
        sig = _Sig()
        sig.progress.connect(lambda f, m: (self.bar.setValue(int(f * 100)), self.msg.setText(m)))
        sig.done.connect(self._done)
        sig.error.connect(self._err)
        self._sig = sig
        self.go.setEnabled(False)
        self.stop.setEnabled(True)
        QThreadPool.globalInstance().start(_Job(lambda s: exporter.export(
            proj, out, preset, progress=lambda f, m: s.progress.emit(f, m), cancel=tok,
            chunk_seconds=hw.chunk_seconds), sig))

    def _done(self, r):
        self.go.setEnabled(True)
        self.stop.setEnabled(False)
        self.bar.setValue(100)
        if r.problems:
            self.msg.setText("Tayyor, lekin ogohlantirishlar: " + "; ".join(r.problems))
        else:
            self.msg.setText(f"Tayyor: {r.path}  ({r.seconds:.1f}s, {r.encoder}, tekshiruvdan o'tdi)")

    def _err(self, m: str):
        self.go.setEnabled(True)
        self.stop.setEnabled(False)
        self.msg.setText("Xato: " + m[:400])


class NewProjectDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Yangi loyiha")
        lay = QFormLayout(self)
        self.name = QLineEdit("Yangi loyiha")
        self.fmt = QComboBox()
        for k, t in (("reels", "Reels / Shorts 9:16 (1080x1920, 30 fps)"), ("youtube", "YouTube 16:9 (1080p, 25 fps)"),
                     ("square", "Kvadrat 1:1 (1080x1080)"), ("cinema", "Kino 16:9 (1080p, 23.976 fps)")):
            self.fmt.addItem(t, k)
        ok = QPushButton("Yaratish")
        ok.clicked.connect(self.accept)
        lay.addRow("Nomi:", self.name)
        lay.addRow("Format:", self.fmt)
        lay.addRow(ok)

    def project(self) -> Project:
        s = PRESETS[self.fmt.currentData()]
        return Project(self.name.text().strip() or "Loyiha", Settings(s.width, s.height, s.fps))


class MainWindow(QMainWindow):
    def __init__(self, vault: Vault, hw: Hardware, open_path: Optional[str] = None):
        super().__init__()
        self.vault, self.hw = vault, hw
        self.setWindowTitle(APP_NAME)
        self.resize(1480, 900)
        self.setStyleSheet(STYLESHEET)
        self.project = Project("Yangi loyiha", PRESETS["reels"].__class__(**vars(PRESETS["reels"])))
        self.history = History(self.project)
        self.path: Optional[str] = None
        self._frame_job = 0
        self._jobs: list = []
        self._playing_range: Optional[tuple[int, int]] = None
        self.frame_timer = QTimer(self)
        self.frame_timer.setSingleShot(True)
        self.frame_timer.timeout.connect(self._render_frame)
        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self._autosave)
        self.autosave_timer.start(30000)
        self._build_ui()
        self._build_menu()
        self._attach(self.project)
        self.statusBar().showMessage(self.hw.summary())
        if open_path:
            self.open_project(open_path)

    # ------------------------------------------------------------- UI qurish
    def _build_ui(self):
        toolbar=self.addToolBar('KADRGO');toolbar.setMovable(False)
        brand=QLabel('KADRGO  STUDIO');brand.setStyleSheet('color:#F6B84A;font-size:20px;font-weight:bold;padding:10px');toolbar.addWidget(brand)
        for text,fn in [('Media import',self.import_media),('Saqlash',self.save),('AI / Rang markazi',lambda:self.open_engines()),('Eksport',self.export_dialog)]:
            action=QAction(text,self);action.triggered.connect(fn);toolbar.addAction(action)
        # chap: media / kutubxona / subtitr
        self.tabs = QTabWidget()
        self.media_list = QListWidget()
        self.media_list.setIconSize(QSize(96, 54))
        self.media_list.itemDoubleClicked.connect(self._media_dbl)
        mw = QWidget()
        ml = QVBoxLayout(mw)
        b = QPushButton("+ Media import")
        b.clicked.connect(self.import_media)
        ml.addWidget(b)
        ml.addWidget(self.media_list)
        self.tabs.addTab(mw, "Media")
        lw = QWidget()
        ll = QVBoxLayout(lw)
        self.lib_cat = QComboBox()
        for k, t in (("sfx", "SFX"), ("music", "Musiqa"), ("font", "Shriftlar"), ("lut", "LUT"), ("plugin", "Plaginlar")):
            self.lib_cat.addItem(t, k)
        self.lib_cat.currentIndexChanged.connect(self.refresh_library)
        self.lib_q = QLineEdit()
        self.lib_q.setPlaceholderText("Qidirish...")
        self.lib_q.textChanged.connect(self.refresh_library)
        sb = QPushButton("Kutubxonani skanerlash")
        sb.clicked.connect(self.scan_library)
        self.lib_list = QListWidget()
        self.lib_list.itemDoubleClicked.connect(self._lib_dbl)
        self.lib_info = QLabel(f"Papka: {self.vault.library}")
        self.lib_info.setWordWrap(True)
        for w in (self.lib_cat, self.lib_q, sb, self.lib_list, self.lib_info):
            ll.addWidget(w)
        self.tabs.addTab(lw, "Kutubxona")
        sw = QWidget()
        sl = QVBoxLayout(sw)
        self.cue_list = QListWidget()
        self.cue_list.itemDoubleClicked.connect(self._cue_dbl)
        for text, fn in (("+ Subtitr (playhead)", self.add_cue_here), ("SRT import", self.import_srt),
                         ("SRT eksport", self.export_srt)):
            bb = QPushButton(text)
            bb.clicked.connect(fn)
            sl.addWidget(bb)
        sl.addWidget(self.cue_list)
        self.tabs.addTab(sw, "Subtitr")
        fxhost=QWidget();fxlayout=QVBoxLayout(fxhost);fxlayout.addWidget(QLabel('RANG VA KINO EFFEKTLARI'))
        search=QLineEdit();search.setPlaceholderText('Effekt / rang qidirish');fxlayout.addWidget(search);browser=QListWidget();browser.setSpacing(4);fxlayout.addWidget(browser)
        def populate(query=''):
            browser.clear()
            for key,d in EFFECTS.items():
                text=d.category+' / '+d.name
                if query.lower() in text.lower():
                    item=QListWidgetItem(text);item.setData(Qt.UserRole,('effect',key));browser.addItem(item)
            for key,(group,name,_) in LOOKS.items():
                text=group+' / '+name
                if query.lower() in text.lower():
                    item=QListWidgetItem(text);item.setData(Qt.UserRole,('look',key));browser.addItem(item)
        def add_effect(item):
            c=self._sel()
            if not c:return self.msg('Avval klip tanlang',True)
            kind,key=item.data(Qt.UserRole);self.do('Effekt',edit.add_effect,c.id,'look' if kind=='look' else key,{'look':key,'intensity':.8} if kind=='look' else {})
        search.textChanged.connect(populate);browser.itemDoubleClicked.connect(add_effect);populate();fxlayout.addWidget(QLabel('Ikki marta bosing → klipga qo‘shiladi.'))
        self.tabs.addTab(fxhost,'Effektlar')
        # markaz: preview
        self.preview = QLabel("Preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(380, 260)
        self.preview.setObjectName("preview")
        self.video = None
        self.player = None
        self.audio_out = None
        self.stack = QStackedWidget()
        self.stack.addWidget(self.preview)
        self.tc = QLabel("00:00:00:00")
        self.tc.setObjectName("tc")
        tr = QHBoxLayout()
        for text, fn in (("|<", lambda: self.goto(0)), ("<", lambda: self.step(-1)), (">", lambda: self.step(1)),
                         ("Ijro (preview)", self.toggle_play)):
            bt = QPushButton(text)
            bt.clicked.connect(fn)
            tr.addWidget(bt)
        tr.addStretch(1)
        tr.addWidget(self.tc)
        cw = QWidget()
        cl = QVBoxLayout(cw)
        cl.addWidget(self.stack, 1)
        cl.addLayout(tr)
        # o'ng: inspector
        self.insp_host = QWidget()
        self.insp_layout = QVBoxLayout(self.insp_host)
        self.insp_layout.setAlignment(Qt.AlignTop)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.insp_host)
        sc.setMinimumWidth(330)
        top = QSplitter(Qt.Horizontal)
        top.addWidget(self.tabs)
        top.addWidget(cw)
        top.addWidget(sc)
        top.setSizes([300, 760, 360])
        # past: timeline
        self.timeline = TimelineWidget()
        self.timeline.playheadChanged.connect(self._on_playhead)
        self.timeline.selectionChanged.connect(lambda _: self.rebuild_inspector())
        self.timeline.moveRequested.connect(lambda cid, st, tid: self.do("Siljitish", edit.move_clip, cid, st, tid))
        self.timeline.trimRequested.connect(self._trim)
        self.timeline.trackFlagRequested.connect(self._track_flag)
        self.timeline.contextRequested.connect(self._context_menu)
        zoom = QSlider(Qt.Horizontal)
        zoom.setRange(1, 200)
        zoom.setValue(40)
        zoom.setMaximumWidth(220)
        zoom.valueChanged.connect(lambda v: (setattr(self.timeline, "px", v / 10.0), self.timeline.update()))
        self.zoom = zoom
        tb = QHBoxLayout()
        for text, fn in (("Bo'lish (S)", self.split_here), ("O'chirish", self.delete_sel),
                         ("Ripple o'chirish", self.ripple_sel), ("Marker (M)", self.add_marker)):
            bt = QPushButton(text)
            bt.clicked.connect(fn)
            tb.addWidget(bt)
        self.snap_cb = QCheckBox("Snap")
        self.snap_cb.setChecked(True)
        self.snap_cb.toggled.connect(lambda v: setattr(self.timeline, "snap_on", v))
        tb.addWidget(self.snap_cb)
        fit = QPushButton("Hammasi")
        fit.clicked.connect(lambda: (self.timeline.fit_all(), self.zoom.setValue(int(min(self.timeline.px * 10, 200)))))
        tb.addWidget(fit)
        tb.addStretch(1)
        tb.addWidget(QLabel("Zoom"))
        tb.addWidget(zoom)
        bw = QWidget()
        bl = QVBoxLayout(bw)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addLayout(tb)
        bl.addWidget(self.timeline, 1)
        main = QSplitter(Qt.Vertical)
        main.addWidget(top)
        main.addWidget(bw)
        main.setSizes([560, 340])
        self.setCentralWidget(main)

    def _act(self, menu, text, fn, key=None) -> QAction:
        a = QAction(text, self)
        if key:
            a.setShortcut(QKeySequence(key))
        a.triggered.connect(lambda _=False: fn())
        menu.addAction(a)
        self.addAction(a)
        return a

    def _build_menu(self):
        m = self.menuBar()
        f = m.addMenu("Fayl")
        self._act(f, "Yangi loyiha", self.new_project, "Ctrl+N")
        self._act(f, "Ochish...", self.open_dialog, "Ctrl+O")
        self._act(f, "Saqlash", self.save, "Ctrl+S")
        self._act(f, "Boshqa nom bilan saqlash...", self.save_as, "Ctrl+Shift+S")
        f.addSeparator()
        self._act(f, "Media import...", self.import_media, "Ctrl+I")
        self._act(f, "Eksport...", self.export_dialog, "Ctrl+E")
        f.addSeparator()
        self._act(f, "Chiqish", self.close, "Ctrl+Q")
        e = m.addMenu("Tahrir")
        self._act(e, "Bekor qilish (Undo)", self.undo, "Ctrl+Z")
        self._act(e, "Qaytarish (Redo)", self.redo, "Ctrl+Y")
        self._act(e, "Qaytarish (Redo) ", self.redo, "Ctrl+Shift+Z")
        e.addSeparator()
        self._act(e, "Playhead da bo'lish", self.split_here, "S")
        self._act(e, "O'chirish", self.delete_sel, "Delete")
        self._act(e, "Ripple o'chirish", self.ripple_sel, "Shift+Delete")
        self._act(e, "Marker qo'yish", self.add_marker, "M")
        self._act(e, "Kadr oldinga", lambda: self.step(1), "Right")
        self._act(e, "Kadr orqaga", lambda: self.step(-1), "Left")
        self._act(e, "10 kadr oldinga", lambda: self.step(10), "Shift+Right")
        self._act(e, "10 kadr orqaga", lambda: self.step(-10), "Shift+Left")
        self._act(e, "Ijro / to'xtatish", self.toggle_play, "Space")
        a = m.addMenu("AI")
        self._act(a, "Sukunatni kesish (tanlangan klip)", self.ai_jump_cut)
        self._act(a, "Beat markerlar (tanlangan klip)", self.ai_beats)
        self._act(a, "Transkripsiya -> subtitr (tanlangan klip)", self.ai_transcribe)
        self._act(a, "AI reja (JSON) qo'llash...", self.ai_plan)
        k = m.addMenu("Kutubxona")
        self._act(k, "Skanerlash", self.scan_library)
        self._act(k, "Papkani ko'rsatish", lambda: QMessageBox.information(self, "Kutubxona", str(self.vault.library)))
        h = m.addMenu("Yordam")
        self._act(h, "Uskuna haqida", lambda: QMessageBox.information(self, "Uskuna", self.hw.summary() + "\n\n"
                                                                    + "\n".join(self.hw.notes)))
        self._act(h, "Dastur haqida", lambda: QMessageBox.information(
            self, APP_NAME, f"{APP_NAME} {__version__} (texnik prototip)\nVault: {self.vault.root}\n"
            f"FFmpeg: {mprobe.FFMPEG}"))

    # ------------------------------------------------------------- holat
    def _attach(self, project: Project):
        self.project = project
        self.history = History(project)
        self.history.on_change.append(self.refresh)
        self.timeline.set_project(project)
        self.timeline.selected = None
        self.timeline.playhead = 0
        self.refresh_media()
        self.refresh_library()
        self.refresh()

    def refresh(self):
        self.timeline.update()
        self.rebuild_inspector()
        self.refresh_cues()
        d = "*" if self.history.dirty else ""
        self.setWindowTitle(f"{APP_NAME} - {self.project.name}{d}")
        self.tc.setText(timecode(self.timeline.playhead, float(self.project.fps)) + "   /   " +
                        timecode(self.project.duration(), float(self.project.fps)))
        self.frame_timer.start(140)

    def msg(self, text: str, err: bool = False):
        self.statusBar().showMessage(("Xato: " if err else "") + text, 8000)

    def do(self, label: str, fn: Callable, *args, **kw):
        try:
            res = self.history.run(label, fn, *args, **kw)
            self.refresh()
            return res
        except EditError as e:
            self.msg(str(e), True)
        except Exception as e:                                   # noqa: BLE001
            self.msg(f"{label}: {e}", True)
        return None

    def _sel(self):
        if self.timeline.selected:
            try:
                return self.project.find(self.timeline.selected)[1]
            except KeyError:
                return None
        return None

    # ------------------------------------------------------------- fayl
    def _confirm_discard(self) -> bool:
        if not self.history.dirty:
            return True
        r = QMessageBox.question(self, "Saqlash", "Saqlanmagan o'zgarishlar bor. Saqlansinmi?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def new_project(self):
        if not self._confirm_discard():
            return
        d = NewProjectDialog(self)
        if d.exec():
            self.path = None
            self._attach(d.project())

    def open_dialog(self):
        f, _ = QFileDialog.getOpenFileName(self, "Loyihani ochish", str(self.vault.projects), "KADRGO (*.kadrgo)")
        if f and self._confirm_discard():
            self.open_project(f)

    def open_project(self, path: str):
        try:
            if storage.has_recovery(path):
                r = QMessageBox.question(self, "Tiklash", "Saqlanmagan autosave topildi. Tiklansinmi?")
                proj = storage.load_recovery(path) if r == QMessageBox.Yes else storage.load(path)
            else:
                proj = storage.load(path)
        except Exception as e:                                   # noqa: BLE001
            QMessageBox.critical(self, "Xato", f"Loyiha ochilmadi: {e}")
            return
        missing = [a.path for a in proj.assets.values() if not os.path.exists(a.path)]
        if missing:
            miss = storage.relink(proj, [str(Path(path).parent), str(self.vault.library)])
            if miss:
                QMessageBox.warning(self, "Offline media", "Topilmadi:\n" + "\n".join(miss[:8]))
        self.path = path
        self._attach(proj)
        self.vault.db.add_recent(path)

    def save(self) -> bool:
        if not self.path:
            return self.save_as()
        try:
            storage.save(self.project, self.path)
            self.vault.db.snapshot_project(self.project.uid, self.project.name, self.project.to_dict(), "save")
            self.history.dirty = False
            self.refresh()
            self.msg("Saqlandi: " + self.path)
            return True
        except Exception as e:                                   # noqa: BLE001
            QMessageBox.critical(self, "Xato", str(e))
            return False

    def save_as(self) -> bool:
        f, _ = QFileDialog.getSaveFileName(self, "Saqlash", str(self.vault.projects / f"{self.project.name}.kadrgo"),
                                           "KADRGO (*.kadrgo)")
        if not f:
            return False
        self.path = f
        return self.save()

    def _autosave(self):
        if not self.history.dirty:
            return
        try:
            p = self.path or str(self.vault.projects / f"{self.project.uid}.kadrgo")
            storage.autosave(self.project, p)
            self.vault.db.snapshot_project(self.project.uid, self.project.name, self.project.to_dict(), "autosave")
        except Exception as e:                                   # noqa: BLE001
            self.msg(f"Autosave xatosi: {e}", True)

    def closeEvent(self, ev):
        if getattr(self,'engine_dialog',None) and self.engine_dialog.proc:
            self.msg('AI jarayonini markazdan to‘xtating',True);ev.ignore();return
        if self._confirm_discard():
            if self.player:
                self.player.stop()
            ev.accept()
        else:
            ev.ignore()

    # ------------------------------------------------------------- media
    def import_media(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Media tanlang", str(Path.home()),
                                                "Media (*.mp4 *.mov *.mkv *.avi *.m4v *.webm *.mp3 *.wav *.m4a *.aac "
                                                "*.flac *.png *.jpg *.jpeg *.webp)")
        for f in files:
            self.add_asset(f)

    def add_asset(self, path: str):
        try:
            a = mprobe.probe(path)
        except ValueError as e:
            self.msg(str(e), True)
            return None
        for ex in self.project.assets.values():
            if ex.hash == a.hash and ex.path == a.path:
                return ex
        self.project.assets[a.id] = a
        self.vault.db.put_asset(a.hash, a.path, {"kind": a.kind, "duration": a.duration})
        self.history.dirty = True
        self.refresh_media()
        self.refresh()
        return a

    def refresh_media(self):
        self.media_list.clear()
        for a in self.project.assets.values():
            it = QListWidgetItem(f"{os.path.basename(a.path)}\n{a.duration:.1f}s  {a.width}x{a.height}")
            it.setData(Qt.UserRole, a.id)
            th = mprobe.thumbnail(a, min(0.5, a.duration / 2)) if (a.has_video or a.kind == "image") else None
            if th:
                it.setIcon(QIcon(str(th)))
            self.media_list.addItem(it)

    def _media_dbl(self, it: QListWidgetItem):
        a = self.project.assets[it.data(Qt.UserRole)]
        tid = "V1" if (a.has_video or a.kind == "image") else "A1"
        self.do("Klip qo'shish", edit.add_clip, tid, a.id, self.timeline.playhead)

    # ------------------------------------------------------------- kutubxona
    def scan_library(self):
        self.msg("Kutubxona skanerlanmoqda...")
        sig = _Sig()
        sig.done.connect(self._scan_done)
        sig.error.connect(lambda m: self.msg(m, True))
        self._jobs.append(sig)
        QThreadPool.globalInstance().start(_Job(lambda s: scanner.scan(self.vault), sig))

    def _scan_done(self, r):
        self.refresh_library()
        txt = (f"SFX {r['sfx']}, musiqa {r['music']}, shrift {r['fonts']}, LUT {r['luts']}, "
               f"plagin {r['plugins']}; muammolar: {len(r['problems'])}")
        self.msg(txt)
        self.lib_info.setText(txt + ("\n" + "\n".join(r["problems"][:6]) if r["problems"] else ""))

    def refresh_library(self):
        cat = self.lib_cat.currentData()
        self.lib_list.clear()
        if cat == "plugin":
            for p in scanner.list_plugins(self.vault.db):
                it = QListWidgetItem(f"{p['name']}  [{p['standard']}]  {p['vendor']}  - {p['status']}")
                it.setData(Qt.UserRole, p)
                self.lib_list.addItem(it)
            return
        for r in scanner.list_library(self.vault.db, cat, self.lib_q.text()):
            mark = "" if r["status"] == "ok" else f"  [{r['status']}]"
            extra = f"  {r['meta'].get('duration', '')}s" if cat in ("sfx", "music") else ""
            it = QListWidgetItem(r["name"] + extra + mark)
            it.setToolTip(r["note"] or r["path"])
            it.setData(Qt.UserRole, r)
            self.lib_list.addItem(it)

    def _lib_dbl(self, it: QListWidgetItem):
        r = it.data(Qt.UserRole)
        cat = self.lib_cat.currentData()
        if cat == "plugin":
            QMessageBox.information(self, r["name"], f"{r['path']}\n\nPlagin topildi, lekin ijro etish uchun OpenFX/VST3 "
                                    "host moduli kerak (keyingi versiya). Hozircha ichki effektlar ishlaydi.")
            return
        if r["status"] == "xato":
            self.msg(r["note"], True)
            return
        if cat in ("sfx", "music"):
            a = self.add_asset(r["path"])
            if a:
                self.do("SFX qo'shish", edit.add_clip, "A3" if cat == "sfx" else "A2", a.id, self.timeline.playhead)
        elif cat == "font":
            fam = r["meta"].get("family", "")
            self.project.settings.sub_font = fam
            self.history.dirty = True
            self.msg(f"Subtitr shrifti: {fam}")
        elif cat == "lut":
            c = self._sel()
            if c is None:
                self.msg("Avval klipni tanlang", True)
                return
            self.do("LUT", edit.add_effect, c.id, "lut", {"file": r["path"], "intensity": 1.0})

    # ------------------------------------------------------------- subtitr
    def refresh_cues(self):
        fps = float(self.project.fps)
        self.cue_list.clear()
        for q in self.project.cues:
            it = QListWidgetItem(f"{timecode(q.start, fps)}  {q.text[:60]}")
            it.setData(Qt.UserRole, q.id)
            self.cue_list.addItem(it)

    def add_cue_here(self):
        t, ok = QInputDialog.getText(self, "Subtitr", "Matn:")
        if ok and t.strip():
            s = self.timeline.playhead
            self.do("Subtitr", edit.add_cue, s, s + int(round(2 * float(self.project.fps))), t.strip())

    def _cue_dbl(self, it):
        cid = it.data(Qt.UserRole)
        q = next(x for x in self.project.cues if x.id == cid)
        t, ok = QInputDialog.getText(self, "Subtitr", "Matn:", text=q.text)
        if ok:
            self.do("Subtitr tahriri", edit.update_cue, cid, text=t)

    def import_srt(self):
        f, _ = QFileDialog.getOpenFileName(self, "SRT", str(Path.home()), "SRT (*.srt)")
        if f:
            cues = subtitles.srt_to_cues(self.project, Path(f).read_text(encoding="utf-8-sig"))

            def op(p):
                for q in cues:
                    edit.add_cue(p, q.start, q.end, q.text)
            self.do("SRT import", op)

    def export_srt(self):
        f, _ = QFileDialog.getSaveFileName(self, "SRT", str(self.vault.projects / "subtitr.srt"), "SRT (*.srt)")
        if f:
            Path(f).write_text(subtitles.cues_to_srt(self.project), encoding="utf-8")
            self.msg("SRT saqlandi")

    # ------------------------------------------------------------- tahrir
    def undo(self):
        l = self.history.undo()
        self.msg("Bekor: " + l if l else "Bekor qilinadigan narsa yo'q")

    def redo(self):
        l = self.history.redo()
        self.msg("Qaytarildi: " + l if l else "Qaytariladigan narsa yo'q")

    def split_here(self):
        c = self._sel()
        if c is None:
            for _, cc in self.project.all_clips():
                if cc.start < self.timeline.playhead < cc.end:
                    c = cc
                    break
        if c is None:
            self.msg("Klip tanlang", True)
            return
        self.do("Bo'lish", edit.split_clip, c.id, self.timeline.playhead)

    def delete_sel(self):
        c = self._sel()
        if c:
            self.do("O'chirish", edit.delete_clip, c.id)
            self.timeline.selected = None

    def ripple_sel(self):
        c = self._sel()
        if c:
            self.do("Ripple o'chirish", edit.ripple_delete, c.id)
            self.timeline.selected = None

    def add_marker(self):
        from ..core.model import Marker

        def op(p):
            p.markers.append(Marker(self.timeline.playhead, "", "user"))
            p.markers.sort(key=lambda m: m.frame)
        self.do("Marker", op)

    def _trim(self, cid: str, edge: str, frame: int):
        self.do("Qirqish", edit.trim_start if edge == "start" else edit.trim_end, cid, frame)

    def _track_flag(self, tid: str, flag: str):
        t = self.project.track(tid)
        self.do("Trek", edit.set_track_flag, tid, **{flag: not getattr(t, flag)})

    def _context_menu(self, pos):
        m = QMenu(self)
        for text, fn in (("Playhead da bo'lish", self.split_here), ("O'chirish", self.delete_sel),
                         ("Ripple o'chirish", self.ripple_sel)):
            m.addAction(text, fn)
        c = self._sel()
        if c:
            m.addAction("Qulfni almashtirish", lambda: self.do("Qulf", edit.set_props, c.id, locked=not c.locked))
        m.exec(pos)

    # ------------------------------------------------------------- playhead / preview
    def goto(self, f: int):
        self.timeline.set_playhead(max(f, 0))
        self._on_playhead(self.timeline.playhead)

    def step(self, n: int):
        self.goto(self.timeline.playhead + n)

    def _on_playhead(self, f: int):
        self.tc.setText(timecode(f, float(self.project.fps)) + "   /   " +
                        timecode(self.project.duration(), float(self.project.fps)))
        if self.stack.currentIndex() == 0:
            self.frame_timer.start(120)

    def _render_frame(self):
        if self.project.duration() <= 0:
            self.preview.setText("Timeline bo'sh: media import qilib, ikki marta bosing")
            return
        self._frame_job += 1
        jid = self._frame_job
        proj = self.project.clone()
        f = min(self.timeline.playhead, max(proj.duration() - 1, 0))
        scale = self.hw.preview_scale * 0.8
        sig = _Sig()
        self._jobs = self._jobs[-6:] + [sig]

        def done(png):
            if jid != self._frame_job:
                return
            img = QImage.fromData(png)
            self.preview.setPixmap(QPixmap.fromImage(img).scaled(self.preview.size(), Qt.KeepAspectRatio,
                                                                  Qt.SmoothTransformation))
        sig.done.connect(done)
        sig.error.connect(lambda m: self.msg("Preview: " + m[-160:], True))
        QThreadPool.globalInstance().start(_Job(lambda s: exporter.render_frame(proj, f, scale), sig))

    def _ensure_player(self) -> bool:
        """Pleer faqat kerak bo'lganda yaratiladi (audio qurilmasi bo'lmasa ham dastur ishlayveradi)."""
        if self.player is not None:
            return True
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            from PySide6.QtMultimediaWidgets import QVideoWidget
            self.video = QVideoWidget()
            self.stack.addWidget(self.video)
            self.player = QMediaPlayer(self)
            self.audio_out = QAudioOutput(self)
            self.player.setAudioOutput(self.audio_out)
            self.player.setVideoOutput(self.video)
            self.player.positionChanged.connect(self._player_pos)
            self.player.mediaStatusChanged.connect(self._player_status)
            return True
        except Exception as e:                                   # noqa: BLE001
            self.msg(f"Pleer ishga tushmadi: {e}", True)
            return False

    def toggle_play(self):
        if self.stack.currentIndex() == 1:
            if self.player:
                self.player.stop()
            self.stack.setCurrentIndex(0)
            return
        if not self._ensure_player():
            return
        a = self.timeline.playhead
        b = min(a + int(10 * float(self.project.fps)), self.project.duration())
        if b <= a:
            self.msg("Ijro uchun timeline bo'sh yoki oxirida", True)
            return
        proj = self.project.clone()
        out = os.path.join(tempfile.gettempdir(), f"kadrgo_pv_{int(time.time())}.mp4")
        sig = _Sig()
        self._jobs.append(sig)
        self.msg("Preview tayyorlanmoqda...")

        def ready(path):
            self._playing_range = (a, b)
            self.stack.setCurrentIndex(1)
            self.player.setSource(QUrl.fromLocalFile(path))
            self.player.play()
            self.msg("Ijro")
        sig.done.connect(ready)
        sig.error.connect(lambda m: self.msg("Preview xatosi: " + m[-200:], True))
        scale = self.hw.preview_scale
        QThreadPool.globalInstance().start(_Job(lambda s: exporter.render_preview(proj, a, b, out, scale), sig))

    def _player_pos(self, ms: int):
        if self._playing_range:
            self.timeline.set_playhead(self._playing_range[0] + int(ms / 1000.0 * float(self.project.fps)))

    def _player_status(self, st):
        from PySide6.QtMultimedia import QMediaPlayer
        if st == QMediaPlayer.EndOfMedia:
            self.stack.setCurrentIndex(0)

    # ------------------------------------------------------------- inspector
    def _clear_inspector(self):
        while self.insp_layout.count():
            it = self.insp_layout.takeAt(0)
            w = it.widget()
            if w:
                w.hide();w.deleteLater()

    def rebuild_inspector(self):
        self._clear_inspector()
        c = self._sel()
        L = self.insp_layout
        if c is None:
            L.addWidget(QLabel("Klip tanlang.\n\nTimeline: sichqoncha bilan siljiting, chetini tortib qirqing,\n"
                               "Ctrl+g'ildirak = zoom, S = bo'lish, Ctrl+Z = bekor qilish."))
            L.addWidget(self._project_box())
            return
        track, _ = self.project.find(c.id)
        box = QGroupBox(f"Klip: {c.label or c.id}")
        form = QFormLayout(box)

        def dspin(val, lo, hi, step, cb, dec=2):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setSingleStep(step)
            s.setDecimals(dec)
            s.setValue(val)
            s.editingFinished.connect(lambda: cb(s.value()))
            return s

        def ispin(val, lo, hi, cb):
            s = QSpinBox()
            s.setRange(lo, hi)
            s.setValue(val)
            s.editingFinished.connect(lambda: cb(s.value()))
            return s
        name = QLineEdit(c.label)
        name.editingFinished.connect(lambda: self.do("Nom", edit.set_props, c.id, label=name.text()))
        form.addRow("Nom", name)
        form.addRow("Tezlik (x)", dspin(c.speed, 0.1, 16, 0.1, lambda v: v != c.speed and self.do(
            "Tezlik", edit.set_speed, c.id, v)))
        form.addRow("Ovoz (dB)", dspin(c.gain_db, -60, 24, 0.5, lambda v: self.do("Ovoz", edit.set_props, c.id, gain_db=v)))
        if track.kind == "video":
            form.addRow("Shaffoflik", dspin(c.opacity, 0, 1, 0.05, lambda v: self.do("Opacity", edit.set_props, c.id,
                                                                                     opacity=v)))
            form.addRow("Masshtab", dspin(c.scale, 0.1, 8, 0.05, lambda v: self.do("Masshtab", edit.set_props, c.id,
                                                                                   scale=v)))
            form.addRow("X (px)", ispin(c.x, -8000, 8000, lambda v: self.do("X", edit.set_props, c.id, x=v)))
            form.addRow("Y (px)", ispin(c.y, -8000, 8000, lambda v: self.do("Y", edit.set_props, c.id, y=v)))
            fit = QComboBox()
            for k, t in (("fit", "Sig'dirish"), ("fill", "To'ldirish"), ("blur", "Xira fon (Reels)")):
                fit.addItem(t, k)
            fit.setCurrentIndex(["fit", "fill", "blur"].index(c.fit))
            fit.activated.connect(lambda _i: self.do("Fit", edit.set_props, c.id, fit=fit.currentData()))
            form.addRow("Joylash", fit)
        form.addRow("Fade in (kadr)", ispin(c.fade_in, 0, 10000, lambda v: self.do("Fade", edit.set_props, c.id, fade_in=v)))
        form.addRow("Fade out (kadr)", ispin(c.fade_out, 0, 10000, lambda v: self.do("Fade", edit.set_props, c.id,
                                                                                       fade_out=v)))
        L.addWidget(box)
        if track.kind == "video":
            L.addWidget(self._transition_box(c))
            L.addWidget(self._effects_box(c))
        L.addWidget(self._project_box())

    def _project_box(self) -> QGroupBox:
        b = QGroupBox("Loyiha")
        f = QFormLayout(b)
        s = self.project.settings
        f.addRow("Format", QLabel(f"{s.width}x{s.height} @ {float(s.fps_frac):.3f} fps"))
        duck = QCheckBox("Musiqa dialog ostida pasayadi (ducking)")
        duck.setChecked(s.ducking)
        duck.toggled.connect(lambda v: (setattr(s, "ducking", v), setattr(self.history, "dirty", True)))
        f.addRow(duck)
        f.addRow("Subtitr shrifti", QLabel(getattr(s, "sub_font", "Inter")))
        return b

    def _transition_box(self, c) -> QGroupBox:
        b = QGroupBox("Perexod (shu klip boshida)")
        f = QFormLayout(b)
        cb = QComboBox()
        for k, (g, n) in TRANSITIONS.items():
            cb.addItem(f"{g} / {n}", k)
        if c.transition_in:
            cb.setCurrentIndex(list(TRANSITIONS).index(c.transition_in["kind"]))
        sp = QSpinBox()
        sp.setRange(2, 200)
        sp.setValue(c.transition_in["duration"] if c.transition_in else int(round(float(self.project.fps) * 0.5)))
        apply = QPushButton("Qo'llash")
        apply.clicked.connect(lambda: self.do("Perexod", edit.set_transition, c.id, cb.currentData(), sp.value()))
        rm = QPushButton("Olib tashlash")
        rm.clicked.connect(lambda: self.do("Perexodni olib tashlash", edit.remove_transition, c.id))
        f.addRow("Tur", cb)
        f.addRow("Kadr", sp)
        row = QHBoxLayout()
        row.addWidget(apply)
        row.addWidget(rm)
        f.addRow(row)
        return b

    def _effects_box(self, c) -> QGroupBox:
        b = QGroupBox("Effektlar")
        v = QVBoxLayout(b)
        for e in c.effects:
            v.addWidget(self._effect_widget(c, e))
        add = QComboBox()
        for k, d in EFFECTS.items():
            add.addItem(f"{d.category} / {d.name}", k)
        bt = QPushButton("+ Effekt qo'shish")
        bt.clicked.connect(lambda: self.do("Effekt", edit.add_effect, c.id, add.currentData(), {}))
        rt = QPushButton("Retush (teri)")
        rt.clicked.connect(lambda: self.do("Retush", edit.add_effect, c.id, "retouch", {}))
        v.addWidget(add)
        v.addWidget(bt)
        v.addWidget(rt)
        return b

    def _effect_widget(self, c, e) -> QWidget:
        d = EFFECTS[e.fx]
        fr = QFrame()
        fr.setObjectName("fx")
        lay = QVBoxLayout(fr)
        head = QHBoxLayout()
        en = QCheckBox(d.name)
        en.setChecked(e.enabled)
        en.toggled.connect(lambda val: self.do("Effekt", edit.toggle_effect, c.id, e.id, val))
        rm = QPushButton("x")
        rm.setMaximumWidth(26)
        rm.clicked.connect(lambda: self.do("Effektni olib tashlash", edit.remove_effect, c.id, e.id))
        head.addWidget(en, 1)
        head.addWidget(rm)
        lay.addLayout(head)
        prm = normalize_params(e.fx, e.params)
        for sp in d.params:
            row = QHBoxLayout()
            row.addWidget(QLabel(sp.label))
            if sp.type == "str" and sp.choices:
                w = QComboBox()
                w.addItems(list(sp.choices))
                w.setCurrentText(str(prm[sp.key]))
                w.activated.connect(lambda _i, k=sp.key, ww=w: self.do("Effekt", edit.update_effect, c.id, e.id,
                                                                       **{k: ww.currentText()}))
                row.addWidget(w, 1)
            elif sp.type == "str":
                w = QPushButton(os.path.basename(str(prm[sp.key])) or "Tanlash...")

                def pick(_=False, k=sp.key):
                    fn, _f = QFileDialog.getOpenFileName(self, "LUT", str(self.vault.library / "LUT"), "LUT (*.cube)")
                    if fn:
                        self.do("Effekt", edit.update_effect, c.id, e.id, **{k: fn})
                w.clicked.connect(pick)
                row.addWidget(w, 1)
            elif sp.type == "bool":
                w = QCheckBox()
                w.setChecked(bool(prm[sp.key]))
                w.toggled.connect(lambda val, k=sp.key: self.do("Effekt", edit.update_effect, c.id, e.id,
                                                                **{k: 1 if val else 0}))
                row.addWidget(w, 1)
            else:
                sl = QSlider(Qt.Horizontal)
                sl.setRange(0, 1000)
                span = (sp.hi - sp.lo) or 1
                sl.setValue(int((float(prm[sp.key]) - sp.lo) / span * 1000))
                lab = QLabel(f"{float(prm[sp.key]):.2f}")
                sl.valueChanged.connect(lambda val, l=lab, s=sp: l.setText(f"{s.lo + (s.hi - s.lo) * val / 1000:.2f}"))
                sl.sliderReleased.connect(lambda s=sp, ww=sl: self.do(
                    "Effekt", edit.update_effect, c.id, e.id, **{s.key: s.lo + (s.hi - s.lo) * ww.value() / 1000}))
                row.addWidget(sl, 1)
                row.addWidget(lab)
            lay.addLayout(row)
        if d.doc:
            n = QLabel(d.doc)
            n.setWordWrap(True)
            n.setObjectName("hint")
            lay.addWidget(n)
        return fr

    # ------------------------------------------------------------- eksport / AI
    def export_dialog(self):
        errs = edit.validate(self.project)
        if errs:
            QMessageBox.warning(self, "Loyiha xatolari", "\n".join(errs[:8]))
            return
        ExportDialog(self).exec()

    def _ai_job(self, label: str, fn: Callable, done: Callable):
        sig = _Sig()
        self._jobs.append(sig)
        self.msg(label + "...")
        sig.done.connect(done)
        sig.error.connect(lambda m: self.msg(m[-240:], True))
        QThreadPool.globalInstance().start(_Job(lambda s: fn(), sig))

    def ai_jump_cut(self):
        c = self._sel()
        if c is None:
            self.msg("Avval klipni tanlang", True)
            return
        self._ai_job("Sukunat tahlil qilinmoqda", lambda: audio_tools.speech_segments(
            self.project.assets[c.asset_id].path, self.project.assets[c.asset_id].duration),
            lambda segs: self._apply_cuts(c.id, segs))

    def _apply_cuts(self, cid, segs):
        p = self.project
        fps = float(p.fps)
        fr = [(int(round(a * fps)), int(round(b * fps))) for a, b in segs]
        r = self.do("AI: sukunatni olib tashlash", edit.replace_with_segments, cid, fr)
        if r:
            self.msg(f"{len(r)} ta bo'lak qoldi")

    def ai_beats(self):
        c = self._sel()
        if c is None:
            self.msg("Avval musiqa klipini tanlang", True)
            return
        a = self.project.assets[c.asset_id]
        self._ai_job("Beat tahlili", lambda: audio_tools.detect_beats(a.path), lambda res: self._apply_beats(c, res))

    def _apply_beats(self, c, res):
        from ..core.model import Marker
        p = self.project
        ms = [Marker(c.start + p.sec_to_frame(t) - c.src_in, "beat", "beat") for t in res["beats"]
              if c.src_in <= p.sec_to_frame(t) < c.src_in + c.duration]
        self.do("AI: beat markerlar", edit.set_markers, ms, "beat")
        self.msg(f"{len(ms)} beat, taxminiy {res['bpm']} BPM (markerlarni qo'lda tuzating)")

    def ai_transcribe(self):
        self.open_engines('whisper')

    def open_engines(self, key='whisper'):
        if getattr(self,'engine_dialog',None) and self.engine_dialog.isVisible():
            self.engine_dialog.raise_();self.engine_dialog.activateWindow();return
        from .engines import EnginesDialog
        self.engine_dialog=EnginesDialog(self,key);self.engine_dialog.show()

    def ai_plan(self):
        f, _ = QFileDialog.getOpenFileName(self, "AI reja (JSON)", str(Path.home()), "JSON (*.json)")
        if not f:
            return
        try:
            plan = json.loads(Path(f).read_text(encoding="utf-8"))
            aiplan.apply_plan(self.history, plan, self.timeline.playhead)
            self.refresh()
            self.msg("AI reja qo'llandi (Ctrl+Z bilan bir qadamda qaytariladi)")
        except Exception as e:                                   # noqa: BLE001
            QMessageBox.warning(self, "AI reja", str(e))
