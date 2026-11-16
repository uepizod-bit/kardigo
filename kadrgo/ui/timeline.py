"""Timeline vidjeti: chizish, snap, siljitish, qirqish, zoom, waveform. Faqat ko'rinadigan klip chiziladi (virtualizatsiya)."""
from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from ..core.model import Project
from ..media import probe as mprobe

BG, PANEL, PANEL2 = QColor("#111318"), QColor("#1B1F27"), QColor("#161922")
ACCENT, AUDIO, AI = QColor("#F6B84A"), QColor("#3CB8B0"), QColor("#A78BFA")
VIDEO = QColor("#4A6FA5")
HEADER_W, RULER_H, EDGE = 128, 26, 6


def timecode(frame: int, fps: float) -> str:
    f = int(round(fps))
    s, ff = divmod(max(frame, 0), max(f, 1))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}:{ff:02d}"


class _WfSignals(QObject):
    done = Signal(str, object)


class _WfJob(QRunnable):
    def __init__(self, asset, sig):
        super().__init__()
        self.asset, self.sig = asset, sig

    def run(self):
        try:
            peaks = mprobe.waveform(self.asset, 50)
        except Exception:
            peaks = None
        self.sig.done.emit(self.asset.id, peaks)


class TimelineWidget(QWidget):
    playheadChanged = Signal(int)
    selectionChanged = Signal(str)
    moveRequested = Signal(str, int, str)          # clip_id, new_start, track_id
    trimRequested = Signal(str, str, int)          # clip_id, 'start'|'end', frame
    trackFlagRequested = Signal(str, str)          # track_id, 'locked'|'muted'
    contextRequested = Signal(object)              # QPoint (global)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Optional[Project] = None
        self.px = 4.0                 # piksel / kadr
        self.scroll = 0               # chap chekkadagi kadr
        self.playhead = 0
        self.selected: Optional[str] = None
        self.snap_on = True
        self._drag: Optional[dict] = None
        self._wf: dict = {}
        self._wf_pending: set = set()
        self._sig = _WfSignals()
        self._sig.done.connect(self._wf_ready)
        self.setMinimumHeight(250)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._font = QFont()
        self._font.setPointSize(8)

    # -- geometriya ---------------------------------------------------
    def set_project(self, p: Project):
        self.project = p
        self.update()

    def fps(self) -> float:
        return float(self.project.fps) if self.project else 25.0

    def _rows(self):
        y = RULER_H
        for t in self.project.tracks:
            h = 56 if t.kind == "video" else 46
            yield t, y, h
            y += h + 2

    def frame_x(self, f: float) -> float:
        return HEADER_W + (f - self.scroll) * self.px

    def x_frame(self, x: float) -> int:
        return int(round((x - HEADER_W) / self.px + self.scroll))

    def _track_at(self, y: float):
        if not self.project:
            return None
        for t, ty, h in self._rows():
            if ty <= y < ty + h:
                return t
        return None

    def _clip_at(self, x: float, y: float):
        t = self._track_at(y)
        if not t:
            return None, None
        f = self.x_frame(x)
        hit = None
        for c in t.clips:
            if c.start <= f < c.end:
                hit = c
        return t, hit

    def total_height(self) -> int:
        return sum((56 if t.kind == "video" else 46) + 2 for t in self.project.tracks) + RULER_H if self.project else 120

    # -- chizish ------------------------------------------------------
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), BG)
        if not self.project:
            return
        p.setFont(self._font)
        fps = self.fps()
        W = self.width()
        f0, f1 = self.scroll, self.scroll + int((W - HEADER_W) / self.px) + 2
        # ruler
        p.fillRect(QRectF(HEADER_W, 0, W - HEADER_W, RULER_H), PANEL)
        step_s = 1
        for cand in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600):
            if cand * fps * self.px >= 70:
                step_s = cand
                break
        else:
            step_s = 600
        s0 = int(f0 / fps / step_s) * step_s
        p.setPen(QPen(QColor("#8a93a6")))
        t = s0
        while t * fps <= f1:
            x = self.frame_x(t * fps)
            if x >= HEADER_W:
                p.drawLine(QPointF(x, RULER_H - 8), QPointF(x, RULER_H))
                p.drawText(QPointF(x + 3, RULER_H - 10), f"{t // 60}:{t % 60:02d}")
            t += step_s
        for m in self.project.markers:
            x = self.frame_x(m.frame)
            if HEADER_W <= x <= W:
                p.setPen(QPen(AUDIO if m.kind == "beat" else ACCENT, 1))
                p.drawLine(QPointF(x, RULER_H - 6), QPointF(x, self.height()))
        # treklar
        for tr, y, h in self._rows():
            p.fillRect(QRectF(HEADER_W, y, W - HEADER_W, h), PANEL2)
            p.fillRect(QRectF(0, y, HEADER_W, h), PANEL)
            p.setPen(QColor("#cfd6e4"))
            p.drawText(QRectF(8, y, HEADER_W - 50, h), Qt.AlignVCenter | Qt.AlignLeft, tr.name)
            p.setPen(ACCENT if tr.locked else QColor("#555d70"))
            p.drawText(QRectF(HEADER_W - 44, y, 20, h), Qt.AlignCenter, "L")
            p.setPen(ACCENT if tr.muted else QColor("#555d70"))
            p.drawText(QRectF(HEADER_W - 24, y, 20, h), Qt.AlignCenter, "M")
            for c in tr.clips:
                if c.end < f0 or c.start > f1:
                    continue
                self._paint_clip(p, tr, c, y, h)
        # subtitr izi
        # playhead
        x = self.frame_x(self.playhead)
        if x >= HEADER_W:
            p.setPen(QPen(ACCENT, 2))
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
            p.setBrush(ACCENT)
            p.drawPolygon(QPolygonF([QPointF(x - 6, 0), QPointF(x + 6, 0), QPointF(x, 10)]))
        if self._drag and self._drag.get("ghost"):
            g = self._drag["ghost"]
            p.setPen(QPen(ACCENT, 1, Qt.DashLine))
            p.setBrush(QColor(246, 184, 74, 40))
            p.drawRect(QRectF(self.frame_x(g[0]), g[2], (g[1] - g[0]) * self.px, g[3]))
            if self._drag.get("snap") is not None:
                sx = self.frame_x(self._drag["snap"])
                p.setPen(QPen(QColor("#ffffff"), 1, Qt.DotLine))
                p.drawLine(QPointF(sx, RULER_H), QPointF(sx, self.height()))
        p.end()

    def _paint_clip(self, p: QPainter, tr, c, y, h):
        x0, x1 = self.frame_x(c.start), self.frame_x(c.end)
        r = QRectF(max(x0, HEADER_W), y + 3, max(min(x1, self.width()) - max(x0, HEADER_W), 1), h - 6)
        base = AUDIO if tr.kind == "audio" else VIDEO
        if c.provenance.startswith("ai") or c.provenance.startswith("generated"):
            base = AI
        col = QColor(base)
        col.setAlpha(110 if c.muted or tr.muted else 210)
        p.setBrush(col)
        p.setPen(QPen(ACCENT, 2) if c.id == self.selected else QPen(QColor(0, 0, 0, 90), 1))
        p.drawRoundedRect(r, 4, 4)
        a = self.project.assets.get(c.asset_id)
        if a is not None and a.has_audio and tr.kind == "audio":
            self._paint_wave(p, a, c, r)
        if c.fade_in:
            p.setPen(QPen(QColor(255, 255, 255, 120), 1))
            p.drawLine(QPointF(x0, r.bottom()), QPointF(x0 + c.fade_in * self.px, r.top()))
        if c.fade_out:
            p.setPen(QPen(QColor(255, 255, 255, 120), 1))
            p.drawLine(QPointF(x1 - c.fade_out * self.px, r.top()), QPointF(x1, r.bottom()))
        if c.transition_in:
            d = c.transition_in["duration"] * self.px
            p.setBrush(QColor(246, 184, 74, 150))
            p.setPen(Qt.NoPen)
            p.drawRect(QRectF(x0, r.top(), d, r.height()))
        p.setPen(QColor("#ffffff"))
        txt = c.label or c.id
        if c.effects:
            txt += "  fx"
        if c.locked:
            txt += "  [L]"
        if c.speed != 1.0:
            txt += f"  {c.speed:g}x"
        if r.width() > 30:
            p.drawText(r.adjusted(5, 2, -3, 0), Qt.AlignTop | Qt.AlignLeft, p.fontMetrics().elidedText(
                txt, Qt.ElideRight, int(r.width() - 8)))

    def _paint_wave(self, p: QPainter, a, c, r: QRectF):
        pk = self._wf.get(a.id)
        if pk is None:
            if a.id not in self._wf_pending:
                self._wf_pending.add(a.id)
                job = _WfJob(a, self._sig)
                QThreadPool.globalInstance().start(job)
            return
        if len(pk) == 0:
            return
        fps = self.fps()
        mid = r.center().y()
        amp = r.height() * 0.42
        p.setPen(QPen(QColor(255, 255, 255, 170), 1))
        x = max(r.left(), HEADER_W)
        end = r.right()
        while x < end:
            f = c.start + (x - self.frame_x(c.start)) / self.px
            sec = (c.src_in + (f - c.start) * c.speed) / fps
            i = int(sec * 50)
            if 0 <= i < len(pk):
                j = min(i + max(int(50 / fps / self.px * c.speed * 1.0) + 1, 1), len(pk))
                lo, hi = float(pk[i:j, 0].min()), float(pk[i:j, 1].max())
                p.drawLine(QPointF(x, mid - hi * amp), QPointF(x, mid - lo * amp))
            x += 1

    def _wf_ready(self, asset_id: str, peaks):
        self._wf[asset_id] = peaks if peaks is not None else np.zeros((0, 2))
        self.update()

    # -- sichqoncha ---------------------------------------------------
    def _snap_points(self, exclude: str = "") -> list[int]:
        pts = [0, self.playhead]
        for t in self.project.tracks:
            for c in t.clips:
                if c.id != exclude:
                    pts += [c.start, c.end]
        pts += [m.frame for m in self.project.markers]
        return pts

    def _snap(self, frame: int, exclude: str = "") -> tuple[int, Optional[int]]:
        if not self.snap_on:
            return frame, None
        thr = 8 / self.px
        best = min(self._snap_points(exclude), key=lambda q: abs(q - frame))
        return (best, best) if abs(best - frame) <= thr else (frame, None)

    def mousePressEvent(self, e):
        if not self.project:
            return
        pos = e.position()
        self.setFocus()
        if e.button() == Qt.RightButton:
            t, c = self._clip_at(pos.x(), pos.y())
            if c:
                self.selected = c.id
                self.selectionChanged.emit(c.id)
                self.update()
            self.contextRequested.emit(e.globalPosition().toPoint())
            return
        if pos.y() < RULER_H and pos.x() > HEADER_W:
            self.playhead = max(self.x_frame(pos.x()), 0)
            self._drag = {"mode": "scrub"}
            self.playheadChanged.emit(self.playhead)
            self.update()
            return
        if pos.x() < HEADER_W:
            t = self._track_at(pos.y())
            if t:
                if pos.x() > HEADER_W - 24:
                    self.trackFlagRequested.emit(t.id, "muted")
                elif pos.x() > HEADER_W - 44:
                    self.trackFlagRequested.emit(t.id, "locked")
            return
        t, c = self._clip_at(pos.x(), pos.y())
        if c is None:
            self.selected = None
            self.selectionChanged.emit("")
            self.playhead = max(self.x_frame(pos.x()), 0)
            self._drag = {"mode": "scrub"}
            self.playheadChanged.emit(self.playhead)
            self.update()
            return
        self.selected = c.id
        self.selectionChanged.emit(c.id)
        x0, x1 = self.frame_x(c.start), self.frame_x(c.end)
        mode = "trim_s" if pos.x() - x0 <= EDGE else ("trim_e" if x1 - pos.x() <= EDGE else "move")
        self._drag = {"mode": mode, "clip": c, "track": t, "grab": self.x_frame(pos.x()) - c.start}
        self.update()

    def mouseMoveEvent(self, e):
        if not self.project:
            return
        pos = e.position()
        d = self._drag
        if d is None:
            t, c = self._clip_at(pos.x(), pos.y())
            if c:
                x0, x1 = self.frame_x(c.start), self.frame_x(c.end)
                self.setCursor(Qt.SizeHorCursor if (pos.x() - x0 <= EDGE or x1 - pos.x() <= EDGE) else Qt.OpenHandCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
            return
        if d["mode"] == "scrub":
            self.playhead = max(self.x_frame(pos.x()), 0)
            self.playheadChanged.emit(self.playhead)
            self.update()
            return
        c, tr = d["clip"], d["track"]
        rows = {t.id: (y, h) for t, y, h in self._rows()}
        if d["mode"] == "move":
            raw = self.x_frame(pos.x()) - d["grab"]
            new, snap_to = self._snap(raw, c.id)
            new2, snap2 = self._snap(raw + c.duration, c.id)
            if snap_to is None and snap2 is not None:
                new, snap_to = new2 - c.duration, snap2
            new = max(new, 0)
            dest = self._track_at(pos.y())
            dest = dest if (dest and dest.kind == tr.kind) else tr
            y, h = rows[dest.id]
            d.update(ghost=(new, new + c.duration, y + 3, h - 6), new=new, dest=dest.id, snap=snap_to)
        elif d["mode"] == "trim_s":
            f, sn = self._snap(self.x_frame(pos.x()), c.id)
            f = min(f, c.end - 1)
            y, h = rows[tr.id]
            d.update(ghost=(f, c.end, y + 3, h - 6), new=f, snap=sn)
        else:
            f, sn = self._snap(self.x_frame(pos.x()), c.id)
            f = max(f, c.start + 1)
            y, h = rows[tr.id]
            d.update(ghost=(c.start, f, y + 3, h - 6), new=f, snap=sn)
        self.update()

    def mouseReleaseEvent(self, e):
        d, self._drag = self._drag, None
        if d and d.get("clip") is not None and "new" in d:
            c = d["clip"]
            if d["mode"] == "move" and (d["new"] != c.start or d["dest"] != d["track"].id):
                self.moveRequested.emit(c.id, d["new"], d["dest"])
            elif d["mode"] == "trim_s" and d["new"] != c.start:
                self.trimRequested.emit(c.id, "start", d["new"])
            elif d["mode"] == "trim_e" and d["new"] != c.end:
                self.trimRequested.emit(c.id, "end", d["new"])
        self.update()

    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        if e.modifiers() & Qt.ControlModifier:
            fx = self.x_frame(e.position().x())
            self.px = min(max(self.px * (1.18 if dy > 0 else 1 / 1.18), 0.1), 60)
            self.scroll = max(int(fx - (e.position().x() - HEADER_W) / self.px), 0)
        else:
            self.scroll = max(self.scroll - int(dy / 120 * 60 / self.px * 2), 0)
        self.update()

    def set_playhead(self, f: int, follow: bool = True):
        self.playhead = max(f, 0)
        if follow:
            vis = int((self.width() - HEADER_W) / self.px)
            if self.playhead < self.scroll or self.playhead > self.scroll + vis:
                self.scroll = max(self.playhead - vis // 4, 0)
        self.update()

    def fit_all(self):
        if self.project and self.project.duration() > 0:
            self.px = max((self.width() - HEADER_W - 20) / self.project.duration(), 0.1)
            self.scroll = 0
            self.update()
