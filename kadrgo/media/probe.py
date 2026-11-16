"""Media tahlili (ffprobe), tezkor hash va kesh (thumbnail, proxy, waveform)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Optional

import numpy as np

from ..core.model import Asset, new_id

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".aiff"}
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def which(name: str) -> str:
    env = os.environ.get(f"KADRGO_{name.upper()}")
    if env:
        return env
    here = Path(__file__).resolve().parents[3] / "bin"
    for cand in (here / f"{name}.exe", here / name):
        if cand.exists():
            return str(cand)
    return shutil.which(name) or name


FFMPEG = which("ffmpeg")
FFPROBE = which("ffprobe")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW, **kw)


def quick_hash(path: str) -> str:
    """Katta fayl uchun tez hash: hajm + boshi + oxiri."""
    size = os.path.getsize(path)
    h = hashlib.sha1(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(65536))
        if size > 131072:
            f.seek(-65536, os.SEEK_END)
            h.update(f.read(65536))
    return h.hexdigest()


def _frac(s: str) -> float:
    try:
        v = Fraction(s)
        return float(v)
    except Exception:
        return 0.0


def probe(path: str) -> Asset:
    """Media faylni tahlil qiladi. Buzilgan/o'qilmaydigan faylda ValueError."""
    if not os.path.exists(path):
        raise ValueError(f"Fayl topilmadi: {path}")
    ext = os.path.splitext(path)[1].lower()
    r = run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    if r.returncode != 0:
        raise ValueError("Faylni o'qib bo'lmadi: " + r.stderr.decode(errors="ignore")[-200:])
    info = json.loads(r.stdout or b"{}")
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"
              and s.get("disposition", {}).get("attached_pic", 0) == 0), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v is None and a is None:
        raise ValueError("Faylda video ham, audio ham yo'q")
    dur = float(info.get("format", {}).get("duration") or 0)
    if not dur and v:
        dur = float(v.get("duration") or 0)
    asset = Asset(id=new_id("a"), path=os.path.abspath(path), kind="video", duration=dur,
                  size=os.path.getsize(path), hash=quick_hash(path))
    if ext in IMAGE_EXT or (v and v.get("codec_name") in ("png", "mjpeg", "webp") and dur < 0.05):
        asset.kind = "image"
    if v is not None:
        w, h = int(v.get("width", 0)), int(v.get("height", 0))
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(round(float(sd["rotation"]))) % 360
        rot = rot or int(v.get("tags", {}).get("rotate", 0) or 0) % 360
        if rot in (90, 270):
            w, h = h, w                    # ffmpeg avtomatik aylantiradi
        r_fps, avg = _frac(v.get("r_frame_rate", "0/1")), _frac(v.get("avg_frame_rate", "0/1"))
        asset.width, asset.height, asset.rotation = w, h, rot
        asset.has_video = True
        asset.fps = v.get("avg_frame_rate") if avg else v.get("r_frame_rate", "0/1")
        asset.vfr = bool(r_fps and avg and abs(r_fps - avg) / max(r_fps, 1e-9) > 0.01)
    if a is not None:
        asset.has_audio = True
        asset.audio_rate = int(a.get("sample_rate", 48000) or 48000)
        if asset.duration == 0:
            asset.duration = float(a.get("duration") or 0)
    if asset.kind == "video" and not asset.has_video:
        asset.kind = "audio"
    if asset.kind == "image":
        asset.has_audio = False
        asset.duration = 0.0
    return asset


# ------------------------------------------------------------------ kesh
def cache_dir(base: Optional[str] = None) -> Path:
    d = Path(base or os.environ.get("KADRGO_CACHE") or Path.home() / ".kadrgo" / "cache")
    d.mkdir(parents=True, exist_ok=True)
    return d


def thumbnail(asset: Asset, t: float = 0.5, width: int = 320, base: Optional[str] = None) -> Optional[Path]:
    out = cache_dir(base) / f"{asset.hash}_{int(t * 1000)}_{width}.jpg"
    if out.exists():
        return out
    if not asset.has_video and asset.kind != "image":
        return None
    t = min(t, max(asset.duration - 0.05, 0))
    r = run([FFMPEG, "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", asset.path, "-frames:v", "1",
             "-vf", f"scale={width}:-2", str(out)])
    return out if r.returncode == 0 and out.exists() else None


def make_proxy(asset: Asset, height: int = 720, base: Optional[str] = None, cancel=None) -> Optional[Path]:
    """Tahrir uchun yengil proxy (qisqa GOP, tez seek). Asl fayl o'zgarmaydi."""
    if not asset.has_video or asset.kind == "image":
        return None
    out = cache_dir(base) / f"{asset.hash}_proxy{height}.mp4"
    if out.exists():
        return out
    tmp = out.with_suffix(".part.mp4")
    cmd = [FFMPEG, "-y", "-v", "error", "-i", asset.path, "-vf", f"scale=-2:{height}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-g", "12", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", str(tmp)]
    r = run(cmd)
    if r.returncode == 0:
        os.replace(tmp, out)
        return out
    return None


def waveform(asset: Asset, bins_per_sec: int = 50, base: Optional[str] = None) -> Optional[np.ndarray]:
    """(N,2) min/max peak massivi; keshlanadi."""
    if not asset.has_audio:
        return None
    out = cache_dir(base) / f"{asset.hash}_wf{bins_per_sec}.npy"
    if out.exists():
        return np.load(out)
    sr = 8000
    r = run([FFMPEG, "-v", "error", "-i", asset.path, "-vn", "-ac", "1", "-ar", str(sr),
             "-f", "s16le", "-"])
    if r.returncode != 0 or not r.stdout:
        return None
    x = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    step = sr // bins_per_sec
    n = len(x) // step
    if n == 0:
        return np.zeros((1, 2), dtype=np.float32)
    x = x[: n * step].reshape(n, step)
    peaks = np.stack([x.min(axis=1), x.max(axis=1)], axis=1).astype(np.float32)
    np.save(out, peaks)
    return peaks
