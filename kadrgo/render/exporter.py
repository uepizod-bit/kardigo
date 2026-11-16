"""Export va preview: bo'lak-bo'lak render, aniq audio, bekor qilish, yakuniy tekshiruv.

Tartib (har bo'lak mustaqil, xotira cheklangan):
  1. retush kabi "bake" effektlar keshga pishiriladi (bir marta)
  2. har bo'lak: video-only fayl + 32-bit float WAV
  3. bo'laklar stream-copy bilan ulanadi, audio BIR marta AAC ga kodlanadi (bo'lak chegarasida chertish yo'q)
  4. natija dekod qilib tekshiriladi
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Callable, Optional

from ..core.edit import validate
from ..core.model import Project
from ..media.probe import CREATE_NO_WINDOW, FFMPEG, FFPROBE, cache_dir, run
from . import encoders
from .graph import AVPlan, Graph, cues_ass, plan_chunks, plan_window

Progress = Optional[Callable[[float, str], None]]


class Cancelled(Exception):
    pass


class ExportError(Exception):
    pass


@dataclass
class Preset:
    name: str
    codec: str = "h264"          # h264 | hevc | prores
    quality: str = "high"
    audio_kbps: int = 256
    loudness: Optional[float] = None     # LUFS; None = o'zgartirmaslik
    burn_subs: bool = True
    ext: str = ".mp4"


PRESETS = {
    "reels": Preset("Reels / Shorts (H.264)", "h264", "high", 256, -14.0),
    "youtube": Preset("YouTube (H.264)", "h264", "high", 320, -14.0),
    "hevc": Preset("HEVC (kichik hajm)", "hevc", "high", 256, None),
    "master": Preset("Master (ProRes 422 HQ)", "prores", "master", 0, None, True, ".mov"),
    "draft": Preset("Qoralama (tez)", "h264", "draft", 192, None),
}


@dataclass
class ExportResult:
    path: str
    seconds: float
    frames: int
    encoder: str
    chunks: int
    problems: list = field(default_factory=list)


class CancelToken:
    def __init__(self):
        self._ev = threading.Event()

    def cancel(self):
        self._ev.set()

    def is_set(self) -> bool:
        return self._ev.is_set()


def _kill_tree(p: subprocess.Popen):
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True,
                           creationflags=CREATE_NO_WINDOW)
        else:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def run_ffmpeg(args: list[str], total_frames: int = 0, on_frames: Optional[Callable[[int], None]] = None,
               cancel: Optional[CancelToken] = None) -> None:
    """FFmpeg ni ishga tushiradi, progressni o'qiydi, bekor qilinsa butun jarayon daraxtini to'xtatadi."""
    err = tempfile.TemporaryFile()
    kw = {"creationflags": CREATE_NO_WINDOW} if sys.platform == "win32" else {"start_new_session": True}
    p = subprocess.Popen([FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-progress", "pipe:1", "-nostats", *args],
                         stdout=subprocess.PIPE, stderr=err, text=True, **kw)
    try:
        for line in p.stdout:                              # type: ignore[union-attr]
            if cancel and cancel.is_set():
                _kill_tree(p)
                raise Cancelled()
            if line.startswith("frame=") and on_frames:
                try:
                    on_frames(int(line.split("=")[1]))
                except ValueError:
                    pass
        p.wait()
    except BaseException:
        if p.poll() is None:
            _kill_tree(p)
        raise
    if p.returncode != 0:
        err.seek(0)
        msg = err.read().decode(errors="ignore")[-1500:]
        raise ExportError(f"FFmpeg xatosi ({p.returncode}):\n{msg}")


def _write_script(tmp: Path, name: str, g: Graph) -> list[str]:
    path = tmp / f"{name}.fg"
    path.write_text(g.script, encoding="utf-8")
    return [*g.inputs, encoders.filter_script_flag(), str(path)]


def _concat_list(path: Path, files: list[Path]):
    with open(path, "w", encoding="utf-8") as f:
        for p in files:
            f.write("file '" + str(p).replace("\\", "/").replace("'", "'\\''") + "'\n")


# ------------------------------------------------------------------ bake (retush)
def bake_effects(project: Project, progress: Progress = None, cancel: Optional[CancelToken] = None,
                 cache: Optional[str] = None) -> dict:
    """Retush kabi og'ir effektlarni oldindan keshga pishiradi. {clip_id: fayl yo'li}."""
    from ..fx.catalog import EFFECTS, normalize_params
    from ..fx.retouch import RetouchParams, retouch_file
    out = {}
    clips = [(t, c) for t, c in project.all_clips() if any(e.enabled and EFFECTS[e.fx].bake for e in c.effects)]
    for n, (t, c) in enumerate(clips):
        a = project.assets[c.asset_id]
        e = next(e for e in c.effects if e.enabled and e.fx == "retouch")
        prm = normalize_params("retouch", e.params)
        s0 = float(Fraction(c.src_in) / project.fps)
        ln = float(Fraction(c.duration * c.speed) / project.fps) + 0.1
        key = f"{a.hash}_{c.src_in}_{c.duration}_{c.speed}_{sorted(prm.items())}"
        import hashlib
        h = hashlib.sha1(key.encode()).hexdigest()[:16]
        dst = cache_dir(cache) / f"retouch_{h}.mp4"
        if not dst.exists():
            if progress:
                progress(n / max(len(clips), 1), f"Retush: {c.label or c.id}")
            retouch_file(a.path, str(dst), s0, ln, RetouchParams(**prm),
                         on_frame=(lambda f, _n=n: progress((_n + min(f / max(ln * float(project.fps), 1), 1)) / len(clips),
                                                            f"Retush: {c.label or c.id}") if progress else None),
                         cancel=cancel)
        out[c.id] = str(dst)
    return out


# ------------------------------------------------------------------ export
def export(project: Project, out_path: str, preset: str | Preset = "reels", progress: Progress = None,
           cancel: Optional[CancelToken] = None, encoder: Optional[str] = None, chunk_seconds: int = 45,
           prefer_hw: bool = True, work_dir: Optional[str] = None) -> ExportResult:
    import time
    t0 = time.time()
    pr = PRESETS[preset] if isinstance(preset, str) else preset
    errs = validate(project)
    if errs:
        raise ExportError("Loyihada xatolar bor:\n- " + "\n- ".join(errs[:10]))
    total = project.duration()
    if total <= 0:
        raise ExportError("Timeline bo'sh")
    for a in project.assets.values():
        if not os.path.exists(a.path) and any(c.asset_id == a.id for _, c in project.all_clips()):
            raise ExportError(f"Media fayl topilmadi (offline): {a.path}")
    if pr.codec == "prores":
        enc, vargs = "prores_ks", encoders.prores_args()
    else:
        enc = encoder or encoders.pick(pr.codec, prefer_hw)
        vargs = encoders.video_args(enc, pr.quality)
    out_path = str(Path(out_path).with_suffix(pr.ext))
    target_path=str(Path(out_path).resolve())
    if any(Path(a.path).resolve()==Path(target_path) for a in project.assets.values()):raise ExportError('Original media ustiga eksport mumkin emas')
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="kadrgo_", dir=work_dir))
    try:
        bake = bake_effects(project, (lambda f, m: progress(f * 0.15, m)) if progress else None, cancel)
        base = 0.15 if bake else 0.0
        fps = float(project.fps)
        chunks = plan_chunks(project, max(int(chunk_seconds * fps), 1))
        done_frames = 0
        vfiles, afiles = [], []
        for i, (a, b) in enumerate(chunks):
            if cancel and cancel.is_set():
                raise Cancelled()
            subs_path = None
            plan = plan_window(project, a, b, 1.0, bake, None)
            if pr.burn_subs:
                ass = cues_ass(project, plan.a_eff, b)
                if ass:
                    subs_path = str(tmp / f"subs_{i:04d}.ass")
                    Path(subs_path).write_text(ass, encoding="utf-8")
                    plan = plan_window(project, a, b, 1.0, bake, subs_path)
            vf = tmp / f"v_{i:04d}{'.mov' if pr.codec == 'prores' else '.mp4'}"
            af = tmp / f"a_{i:04d}.wav"
            vcmd = [*_write_script(tmp, f"v{i}", plan.video), "-map", f"[{plan.video.label}]", "-frames:v",
                    str(plan.frames), "-an", *vargs, *encoders.color_tags(), str(vf)]
            acmd = [*_write_script(tmp, f"a{i}", plan.audio), "-map", f"[{plan.audio.label}]", "-c:a", "pcm_f32le",
                    "-ar", str(plan.sample_rate), "-f", "wav", str(af)]

            def on_f(n, _d=done_frames, _t=total):
                if progress:
                    progress(base + (1 - base) * 0.9 * min((_d + n) / _t, 1.0), f"Render {i + 1}/{len(chunks)}")
            run_ffmpeg(vcmd, plan.frames, on_f, cancel)
            run_ffmpeg(acmd, 0, None, cancel)
            done_frames += plan.frames
            vfiles.append(vf)
            afiles.append(af)
        # ulash
        vl, al = tmp / "v.txt", tmp / "a.txt"
        _concat_list(vl, vfiles)
        _concat_list(al, afiles)
        mux = ["-f", "concat", "-safe", "0", "-i", str(vl), "-f", "concat", "-safe", "0", "-i", str(al),
               "-map", "0:v", "-map", "1:a", "-c:v", "copy"]
        if pr.codec == "prores":
            mux += ["-c:a", "pcm_s24le"]
        else:
            if pr.loudness is not None:
                mux += ["-af", f"loudnorm=I={pr.loudness}:TP=-1.0:LRA=11"]
            mux += ["-c:a", "aac", "-b:a", f"{pr.audio_kbps}k", "-ar", str(project.settings.sample_rate),
                    "-movflags", "+faststart"]
        staged_output=str(tmp/("final"+pr.ext))
        mux += [staged_output]
        if progress:
            progress(0.97, "Ulash va audio kodlash")
        run_ffmpeg(mux, 0, None, cancel)
        problems=verify_export(project,staged_output)
        if problems:raise ExportError('; '.join(problems))
        if cancel and cancel.is_set():raise Cancelled()
        os.replace(staged_output,target_path)
        if progress:
            progress(1.0, "Tayyor")
        return ExportResult(out_path, time.time() - t0, total, enc, len(chunks), problems)
    except BaseException:
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def verify_export(project: Project, path: str) -> list[str]:
    """Fayl dekod bo'ladimi, davomiylik mosmi, ovoz bormi."""
    problems = []
    if not os.path.exists(path) or os.path.getsize(path) < 1000:
        return ["Fayl yaratilmadi yoki bo'sh"]
    r = run([FFMPEG, "-v", "error", "-i", path, "-f", "null", "-"])
    if r.returncode != 0 or r.stderr.strip():
        problems.append("Dekod xatosi: " + r.stderr.decode(errors="ignore")[:200])
    import json
    p = run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    info = json.loads(p.stdout or b"{}")
    exp = float(Fraction(project.duration()) / project.fps)
    dur = float(info.get("format", {}).get("duration") or 0)
    tol = 2.5 / float(project.fps)
    if abs(dur - exp) > tol:
        problems.append(f"Davomiylik mos emas: kutilgan {exp:.3f}s, olingan {dur:.3f}s")
    kinds = [s.get("codec_type") for s in info.get("streams", [])]
    if "video" not in kinds:
        problems.append("Video oqimi yo'q")
    if "audio" not in kinds:
        problems.append("Audio oqimi yo'q")
    return problems


# ------------------------------------------------------------------ preview
def render_preview(project: Project, a: int, b: int, out_path: str, scale: float = 0.5,
                   progress: Progress = None, cancel: Optional[CancelToken] = None) -> str:
    """[a,b) oynasini kichik o'lchamda render qiladi (ovoz bilan). Export bilan bir xil graf."""
    tmp = Path(tempfile.mkdtemp(prefix="kadrgo_pv_"))
    try:
        bake = {}
        plan = plan_window(project, a, b, scale, bake, None)
        ass = cues_ass(project, plan.a_eff, b)
        if ass:
            sp = tmp / "s.ass"
            sp.write_text(ass, encoding="utf-8")
            plan = plan_window(project, a, b, scale, bake, str(sp))
        enc = encoders.pick("h264", True)
        vf, af = tmp / "v.mp4", tmp / "a.wav"
        run_ffmpeg([*_write_script(tmp, "v", plan.video), "-map", f"[{plan.video.label}]", "-frames:v",
                    str(plan.frames), "-an", *encoders.video_args(enc, "draft", fast=True), str(vf)],
                   plan.frames, (lambda n: progress(0.8 * n / plan.frames, "Preview")) if progress else None, cancel)
        run_ffmpeg([*_write_script(tmp, "a", plan.audio), "-map", f"[{plan.audio.label}]", "-c:a", "pcm_f32le",
                    "-ar", str(plan.sample_rate), "-f", "wav", str(af)], 0, None, cancel)
        run_ffmpeg(["-i", str(vf), "-i", str(af), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "160k", "-shortest", "-movflags", "+faststart", "-y", out_path], 0, None, cancel)
        if progress:
            progress(1.0, "Tayyor")
        return out_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def render_frame(project: Project, frame: int, scale: float = 0.5) -> bytes:
    """Bitta kadrni PNG sifatida qaytaradi (timeline ko'rinishi: effekt, perexod, subtitr bilan)."""
    tmp = Path(tempfile.mkdtemp(prefix="kadrgo_fr_"))
    try:
        plan = plan_window(project, frame, frame + 1, scale, {}, None)
        ass = cues_ass(project, plan.a_eff, frame + 1)
        if ass:
            sp = tmp / "s.ass"
            sp.write_text(ass, encoding="utf-8")
            plan = plan_window(project, frame, frame + 1, scale, {}, str(sp))
        out = tmp / "f.png"
        # eksport fayli bt709 teglangan: PNG ham xuddi shu matritsa bilan RGB ga o'tadi (preview == export ranglari)
        g = plan.video
        g.script += (f";\n[{g.label}]scale=in_color_matrix=bt709:in_range=tv:out_range=pc"
                     ":flags=accurate_rnd+full_chroma_int,format=rgb24[pngout]")
        run_ffmpeg([*_write_script(tmp, "v", g), "-map", "[pngout]", "-frames:v", "1", "-c:v", "png", "-y", str(out)])
        return out.read_bytes()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
