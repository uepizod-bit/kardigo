"""Uskunani aniqlash (haqiqiy): RAM, GPU, kodeklar. Shunga qarab preview/proxy/bo'lak sozlamalari tanlanadi."""
from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass, field

from ..media.probe import CREATE_NO_WINDOW


def _sh(cmd: list[str], timeout: int = 6) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def ram_gb() -> float:
    try:
        if sys.platform == "win32":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("ml", ctypes.c_ulong), ("tp", ctypes.c_ulonglong),
                            ("ap", ctypes.c_ulonglong), ("tpf", ctypes.c_ulonglong), ("apf", ctypes.c_ulonglong),
                            ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]
            m = MS()
            m.l = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.tp / 2**30
        if sys.platform == "darwin":
            return int(_sh(["sysctl", "-n", "hw.memsize"]).strip() or 0) / 2**30
        with open("/proc/meminfo") as f:
            return int(re.search(r"MemTotal:\s+(\d+)", f.read()).group(1)) / 2**20
    except Exception:
        return 0.0


def gpus() -> list[dict]:
    out = []
    smi = _sh(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    for line in smi.strip().splitlines():
        try:
            n, m = [x.strip() for x in line.split(",")]
            out.append({"name": n, "vram_mb": int(m), "vendor": "NVIDIA"})
        except ValueError:
            pass
    if out:
        return out
    if sys.platform == "win32":
        txt = _sh(["powershell", "-NoProfile", "-Command",
                   "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"])
        out = [{"name": l.strip(), "vram_mb": 0, "vendor": "?"} for l in txt.splitlines() if l.strip()]
    elif sys.platform == "darwin":
        txt = _sh(["system_profiler", "SPDisplaysDataType"])
        out = [{"name": m, "vram_mb": 0, "vendor": "Apple/AMD"} for m in re.findall(r"Chipset Model:\s*(.+)", txt)]
    return out


@dataclass
class Hardware:
    os: str
    arch: str
    cpu: str
    cores: int
    ram_gb: float
    gpus: list = field(default_factory=list)
    profile: str = "A"
    preview_scale: float = 0.5
    proxy_height: int = 540
    chunk_seconds: int = 30
    notes: list = field(default_factory=list)

    def summary(self) -> str:
        g = ", ".join(f"{x['name']}" + (f" {x['vram_mb']//1024 or x['vram_mb']/1024:.0f}GB" if x["vram_mb"] else "")
                      for x in self.gpus) or "GPU aniqlanmadi"
        return f"{self.os} {self.arch} | {self.cpu} ({self.cores} oqim) | RAM {self.ram_gb:.0f} GB | {g} | profil {self.profile}"


def detect() -> Hardware:
    cpu = platform.processor() or platform.machine()
    if sys.platform == "win32":
        n = _sh(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"]).strip()
        cpu = n or cpu
    elif sys.platform == "darwin":
        cpu = _sh(["sysctl", "-n", "machdep.cpu.brand_string"]).strip() or cpu
    h = Hardware(platform.system(), platform.machine(), cpu, os.cpu_count() or 1, ram_gb(), gpus())
    vram = max((g["vram_mb"] for g in h.gpus), default=0)
    apple = h.os == "Darwin" and h.arch == "arm64"
    if h.ram_gb >= 48 and (vram >= 10000 or apple):
        h.profile, h.preview_scale, h.proxy_height, h.chunk_seconds = "C", 1.0, 1080, 90
    elif h.ram_gb >= 24 and (vram >= 6000 or apple):
        h.profile, h.preview_scale, h.proxy_height, h.chunk_seconds = "B", 0.75, 720, 60
    else:
        h.profile, h.preview_scale, h.proxy_height, h.chunk_seconds = "A", 0.5, 540, 30
        h.notes.append("Yengil profil: preview 50%, proxy 540p. 4K va og'ir retush sekin bo'ladi.")
    if h.ram_gb and h.ram_gb < 12:
        h.notes.append("RAM kam: boshqa dasturlarni yoping.")
    return h
