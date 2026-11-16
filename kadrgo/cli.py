"""Buyruq satri: GUI, tahlil, eksport, kutubxona skaneri, o'z-o'zini tekshirish."""
from __future__ import annotations

import argparse
import json
import sys
import time


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="kadrgo", description="KADRGO Studio")
    ap.add_argument("--vault", help="Vault papkasi (standart: avtomatik)")
    sub = ap.add_subparsers(dest="cmd")
    g = sub.add_parser("gui", help="Dasturni ochish (standart)")
    g.add_argument("project", nargs="?")
    sub.add_parser("info", help="Uskuna, FFmpeg va kodeklar")
    s = sub.add_parser("scan", help="Kutubxonani skanerlash va tekshirish")
    s.add_argument("--dir", action="append", help="Qo'shimcha papka")
    s.add_argument("--force", action="store_true")
    sub.add_parser("library", help="Kutubxona hisoboti")
    e = sub.add_parser("export", help="Loyihani eksport qilish")
    e.add_argument("project")
    e.add_argument("output")
    e.add_argument("--preset", default="reels")
    c = sub.add_parser("selfcheck", help="Haqiqiy o'z-o'zini tekshirish (render, undo, saqlash)")
    c.add_argument("--cycles", type=int, default=20)
    a = ap.parse_args(argv)
    cmd = a.cmd or "gui"

    if cmd == "gui":
        from .app import run
        return run(getattr(a, "project", None), a.vault)

    from .core import hardware
    from .core.vault import Vault
    vault = Vault(a.vault)
    if cmd == "info":
        from .media import probe as mp
        from .render import encoders
        hw = hardware.detect()
        print(hw.summary())
        for n in hw.notes:
            print(" -", n)
        print("FFmpeg:", mp.FFMPEG, "| major", encoders.ffmpeg_major())
        print("H.264 kodeklar:", ", ".join(encoders.available("h264")))
        print("HEVC kodeklar:", ", ".join(encoders.available("hevc")) or "yo'q")
        print("Vault:", vault.root)
        return 0
    if cmd == "scan":
        from .library import scanner
        r = scanner.scan(vault, a.dir, force=a.force)
        print({k: v for k, v in r.items() if k != "problems"})
        for p in r["problems"]:
            print(" !", p)
        return 0
    if cmd == "library":
        from .library import scanner
        print(json.dumps(vault.db.stats(), ensure_ascii=False))
        for cat in ("sfx", "music", "font", "lut"):
            items = scanner.list_library(vault.db, cat)
            ok = sum(1 for i in items if i["status"] == "ok")
            print(f"{cat}: {len(items)} ta ({ok} ok)")
        for p in scanner.list_plugins(vault.db):
            print(f"plagin: {p['name']} [{p['standard']}] {p['vendor']} - {p['status']}")
        return 0
    if cmd == "export":
        from .core import storage
        from .render import exporter
        proj = storage.load(a.project)
        t0 = time.time()
        r = exporter.export(proj, a.output, a.preset, progress=lambda f, m: print(f"\r{f * 100:5.1f}%  {m:30}", end=""),
                            chunk_seconds=hardware.detect().chunk_seconds)
        print(f"\nTayyor: {r.path}  {r.seconds:.1f}s  {r.encoder}")
        for p in r.problems:
            print(" !", p)
        return 0 if not r.problems else 1
    if cmd == "selfcheck":
        from .selfcheck import run
        return run(vault, a.cycles)
    return 0
