"""Lokal audio tahlil: sukunat, jump-cut, beat. Hammasi kompyuterda, internetsiz (FFmpeg + NumPy)."""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Optional

import numpy as np

from ..core import edit
from ..core.history import History
from ..core.model import Marker, Project
from ..media.probe import FFMPEG, run


def detect_silence(path: str, noise_db: float = -35.0, min_len: float = 0.35) -> list[tuple[float, float]]:
    r = run([FFMPEG, "-v", "info", "-i", path, "-vn", "-af", f"silencedetect=noise={noise_db}dB:d={min_len}",
             "-f", "null", "-"])
    txt = r.stderr.decode(errors="ignore")
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", txt)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", txt)]
    out = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else float("inf")
        out.append((s, e))
    return out


def speech_segments(path: str, duration: float, noise_db: float = -35.0, min_silence: float = 0.35,
                    pad: float = 0.08) -> list[tuple[float, float]]:
    sil = detect_silence(path, noise_db, min_silence)
    segs, cur = [], 0.0
    for s, e in sil:
        if s - cur > 0.05:
            segs.append((max(cur - pad, 0), min(s + pad, duration)))
        cur = e if e != float("inf") else duration
    if duration - cur > 0.05:
        segs.append((max(cur - pad, 0), duration))
    merged = []
    for a, b in segs:                                  # pad tufayli qoplanganlarni birlashtiramiz
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def jump_cut(history: History, clip_id: str, noise_db: float = -35.0, min_silence: float = 0.35) -> int:
    """Klipdagi sukunatlarni olib tashlaydi. Bitta qaytariladigan qadam. Qaytadi: qolgan bo'laklar soni."""
    p = history.project
    track, c = p.find(clip_id)
    if c.locked:
        raise edit.EditError("Klip qulflangan: AI tegmaydi")
    a = p.assets[c.asset_id]
    segs_s = speech_segments(a.path, a.duration, noise_db, min_silence)
    fps = p.fps
    segs = [(int(round(float(s * fps))), int(round(float(e * fps)))) for s, e in
            [(Fraction(x).limit_denominator(10000), Fraction(y).limit_denominator(10000)) for x, y in segs_s]]
    out = history.run("AI: sukunatni olib tashlash", edit.replace_with_segments, clip_id, segs)
    return len(out)


def detect_beats(path: str, max_seconds: float = 600.0) -> dict:
    """Spektral flux asosida onset/beat va taxminiy BPM. Natija taxminiy; foydalanuvchi markerlarni tuzatadi."""
    sr, hop, win = 22050, 512, 1024
    r = run([FFMPEG, "-v", "error", "-t", str(max_seconds), "-i", path, "-vn", "-ac", "1", "-ar", str(sr),
             "-f", "s16le", "-"])
    x = np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768.0
    if len(x) < win * 4:
        return {"beats": [], "bpm": 0.0}
    n = (len(x) - win) // hop
    w = np.hanning(win).astype(np.float32)
    frames = np.lib.stride_tricks.as_strided(x, (n, win), (x.strides[0] * hop, x.strides[0]))
    spec = np.abs(np.fft.rfft(frames * w, axis=1))
    flux = np.maximum(np.diff(np.log1p(spec * 10), axis=0), 0).sum(axis=1)
    flux = (flux - flux.mean()) / (flux.std() + 1e-9)
    thr = np.convolve(flux, np.ones(21) / 21, mode="same") + 0.6
    peaks = [i for i in range(1, len(flux) - 1) if flux[i] > thr[i] and flux[i] >= flux[i - 1] and flux[i] > flux[i + 1]]
    times, last = [], -1.0
    for i in peaks:
        t = (i + 1) * hop / sr
        if t - last >= 0.18:
            times.append(round(t, 3))
            last = t
    bpm = 0.0
    if len(times) > 8:
        ioi = np.diff(times)
        ioi = ioi[(ioi > 0.25) & (ioi < 1.2)]
        if len(ioi):
            bpm = float(60.0 / np.median(ioi))
            while bpm < 70:
                bpm *= 2
            while bpm > 180:
                bpm /= 2
    return {"beats": times, "bpm": round(bpm, 1)}


def add_beat_markers(history: History, asset_id: str, offset_frame: int = 0) -> int:
    p = history.project
    a = p.assets[asset_id]
    res = detect_beats(a.path)
    ms = [Marker(offset_frame + p.sec_to_frame(t), "beat", "beat") for t in res["beats"]]
    history.run("AI: beat markerlar", edit.set_markers, ms, "beat")
    return len(ms)


def snap_to_beats(project: Project, frame: int, max_dist_frames: int = 6) -> int:
    """Kesish nuqtasini eng yaqin beat markerga tortadi (yaqin bo'lsa). Ma'no uchun qat'iy emas."""
    beats = [m.frame for m in project.markers if m.kind == "beat"]
    if not beats:
        return frame
    b = min(beats, key=lambda x: abs(x - frame))
    return b if abs(b - frame) <= max_dist_frames else frame
