"""O'z-o'zini tekshirish: HAQIQIY render, undo/redo, saqlash va baza yaxlitligi. Natijalar o'lchangan raqamlar.

Bu "30 kunlik sinov" EMAS: u qisqa muddatli funksional tekshiruv. Uzoq muddatli barqarorlik real loyihalarda
vaqt o'tishi bilan aniqlanadi.
"""
from __future__ import annotations

import os
import random
import subprocess
import tempfile
import time
from pathlib import Path

from .core import edit, storage
from .core.history import History, state_hash
from .core.model import Project, Settings
from .media import probe as mp
from .render import exporter


def run(vault, cycles: int = 20) -> int:
    t0 = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="kadrgo_sc_"))
    fails: list[str] = []

    def ok(name: str, cond: bool, info: str = ""):
        print(("  OK    " if cond else "  XATO  ") + name + (f"  ({info})" if info else ""))
        if not cond:
            fails.append(name)

    print("KADRGO o'z-o'zini tekshirish")
    src = tmp / "t.mp4"
    subprocess.run([mp.FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=6", "-f", "lavfi",
                    "-i", "sine=f=440:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(src)], check=True)
    p = Project("selfcheck", Settings(640, 360, "25/1"))
    a = mp.probe(str(src))
    p.assets[a.id] = a
    h = History(p)
    c1 = h.run("add", edit.add_clip, "V1", a.id, 0, 0, 75)
    c2 = h.run("add", edit.add_clip, "V1", a.id, 75, 75, 75)
    h.run("tr", edit.set_transition, c2.id, "fade", 12)
    h.run("fx", edit.add_effect, c1.id, "look", {"look": "drama_teal_orange"})
    ok("loyiha yaxlitligi", not edit.validate(p))
    r = exporter.export(p, str(tmp / "o.mp4"), "draft")
    ok("eksport + dekod tekshiruvi", not r.problems, f"{r.seconds:.1f}s, {r.encoder}")
    rnd = random.Random(3)
    base = state_hash(p)
    depth = len(h.undo_stack)
    n_ok = 0
    for i in range(cycles):
        cl = [c for _, c in p.all_clips()]
        try:
            h.run("split", edit.split_clip, rnd.choice(cl).id, rnd.randint(1, 140))
        except edit.EditError:
            pass
        n_ok += 1
    while len(h.undo_stack) > depth:
        h.undo()
    ok(f"{cycles} amal -> to'liq undo -> aynan boshlang'ich holat", state_hash(p) == base)
    f = tmp / "x.kadrgo"
    storage.save(p, f)
    ok("saqlash/ochish aynan bir xil", state_hash(storage.load(f)) == state_hash(p))
    vault.db.snapshot_project(p.uid, p.name, p.to_dict(), "selfcheck")
    import json
    ok("baza snapshoti checksum bilan qaytadi",
       vault.db.load_project_verified(p.uid) == json.loads(json.dumps(p.to_dict())))
    ok("SQLite yaxlitligi", vault.db.integrity() == "ok")
    print(f"\n{'HAMMASI JOYIDA' if not fails else 'XATOLAR: ' + ', '.join(fails)}  ({time.time() - t0:.1f}s)")
    return 0 if not fails else 1
