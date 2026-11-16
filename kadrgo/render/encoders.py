"""Kodeklarni aniqlash: apparat (NVENC/QSV/AMF/VideoToolbox) real sinov bilan tekshiriladi."""
from __future__ import annotations

import re
import sys
from functools import lru_cache

from ..media.probe import FFMPEG, run

CANDIDATES = {
    "h264": ["h264_nvenc", "h264_videotoolbox", "h264_qsv", "h264_amf", "libx264"],
    "hevc": ["hevc_nvenc", "hevc_videotoolbox", "hevc_qsv", "hevc_amf", "libx265"],
}


@lru_cache(maxsize=1)
def ffmpeg_major() -> int:
    r = run([FFMPEG, "-version"])
    m = re.search(r"ffmpeg version [nN]?(\d+)", r.stdout.decode(errors="ignore"))
    return int(m.group(1)) if m else 6


def filter_script_flag() -> str:
    """FFmpeg 7+ da -filter_complex_script eskirgan: -/filter_complex ishlatiladi."""
    return "-/filter_complex" if ffmpeg_major() >= 7 else "-filter_complex_script"


@lru_cache(maxsize=None)
def works(encoder: str) -> bool:
    """Kodek haqiqatan ishlashini 3 kadrlik sinov bilan tekshiradi (ro'yxatda bor != ishlaydi)."""
    r = run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=640x360:d=0.3:r=25",
             "-frames:v", "3", "-c:v", encoder, "-pix_fmt", "yuv420p", "-f", "null", "-"])
    return r.returncode == 0


def available(codec: str = "h264") -> list[str]:
    return [e for e in CANDIDATES[codec] if works(e)]


def pick(codec: str = "h264", prefer_hw: bool = True) -> str:
    av = available(codec)
    if not av:
        raise RuntimeError(f"{codec} kodeki topilmadi; FFmpeg ni o'rnating")
    sw = CANDIDATES[codec][-1]
    if not prefer_hw and sw in av:
        return sw
    return av[0]


def video_args(encoder: str, quality: str = "high", fast: bool = False) -> list[str]:
    """quality: high | master | draft. fast=True preview uchun."""
    crf = {"master": 12, "high": 17, "draft": 26}[quality]
    if encoder in ("libx264", "libx265"):
        preset = "ultrafast" if fast else ("slow" if quality == "master" else "medium")
        a = ["-c:v", encoder, "-preset", preset, "-crf", str(crf)]
        if encoder == "libx265":
            a += ["-tag:v", "hvc1"]
        return a + ["-pix_fmt", "yuv420p"]
    if encoder.endswith("_nvenc"):
        return ["-c:v", encoder, "-preset", "p3" if fast else "p5", "-rc", "vbr", "-cq", str(crf + 2),
                "-b:v", "0", "-pix_fmt", "yuv420p"]
    if encoder.endswith("_qsv"):
        return ["-c:v", encoder, "-global_quality", str(crf + 3), "-pix_fmt", "nv12"]
    if encoder.endswith("_amf"):
        return ["-c:v", encoder, "-quality", "speed" if fast else "quality", "-rc", "cqp",
                "-qp_i", str(crf + 2), "-qp_p", str(crf + 4), "-pix_fmt", "yuv420p"]
    if encoder.endswith("_videotoolbox"):
        return ["-c:v", encoder, "-b:v", "8M" if fast else "30M", "-pix_fmt", "yuv420p"]
    raise ValueError(encoder)


def prores_args() -> list[str]:
    return ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le", "-vendor", "apl0"]


def color_tags() -> list[str]:
    return ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
