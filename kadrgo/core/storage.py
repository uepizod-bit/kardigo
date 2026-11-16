"""Loyihani saqlash: atomik yozish, versiyalar, autosave, buzilgan faylni tiklash.

Fayl tuzilishi (loyiha `Sinfdosh.kadrgo` bo'lsa):
  Sinfdosh.kadrgo                 asosiy fayl
  Sinfdosh.kadrgo.autosave        oxirgi autosave (saqlanmagan ish)
  Sinfdosh.kadrgo.versions/       oxirgi N ta saqlangan versiya
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

from .model import Project

EXT = ".kadrgo"
KEEP_VERSIONS = 20


def _atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)         # atomik: yarim yozilgan fayl hech qachon ko'rinmaydi
    except BaseException:
        with_suppress_remove(tmp)
        raise


def with_suppress_remove(p):
    try:
        os.remove(p)
    except OSError:
        pass


def _dump(project: Project) -> str:
    return json.dumps(project.to_dict(), ensure_ascii=False, indent=1)


def save(project: Project, path: str | Path, keep_version: bool = True) -> Path:
    path = Path(path)
    if path.suffix != EXT:
        path = path.with_suffix(EXT)
    if keep_version and path.exists():
        vdir = Path(str(path) + ".versions")
        vdir.mkdir(exist_ok=True)
        stamp = time.time_ns()
        prefix = time.strftime('%Y%m%d-%H%M%S')
        while True:
            backup = vdir / f"{prefix}-{stamp:019d}.kadrgo"
            try:
                with backup.open("xb") as dst, path.open("rb") as src:
                    shutil.copyfileobj(src, dst)
                break
            except FileExistsError:
                # Windows clock resolution can tie even for time_ns(). Exclusive
                # creation prevents two fast saves from overwriting a version.
                stamp += 1
        olds = sorted(vdir.glob("*.kadrgo"))
        for o in olds[:-KEEP_VERSIONS]:
            with_suppress_remove(o)
    _atomic_write(path, _dump(project))
    with_suppress_remove(str(path) + ".autosave")
    return path


def autosave(project: Project, path: str | Path):
    _atomic_write(Path(str(path) + ".autosave"), _dump(project))


def has_recovery(path: str | Path) -> bool:
    a = Path(str(path) + ".autosave")
    p = Path(path)
    try:
        if not a.exists():
            return False
        if not p.exists():
            return True
        auto_time, saved_time = a.stat().st_mtime_ns, p.stat().st_mtime_ns
        if auto_time != saved_time:
            return auto_time > saved_time
        # Windows can give consecutive writes identical timestamps. Never hide
        # different unsaved work just because the filesystem clock tied.
        return a.read_bytes() != p.read_bytes()
    except FileNotFoundError:
        return False


def load(path: str | Path) -> Project:
    """Asosiy faylni o'qiydi; buzilgan bo'lsa eng yangi sog'lom versiyaga qaytadi."""
    path = Path(path)
    try:
        return Project.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception as first:
        vdir = Path(str(path) + ".versions")
        for v in sorted(vdir.glob("*.kadrgo"), reverse=True) if vdir.exists() else []:
            try:
                return Project.from_dict(json.loads(v.read_text(encoding="utf-8")))
            except Exception:
                continue
        raise first


def load_recovery(path: str | Path) -> Project:
    return Project.from_dict(json.loads(Path(str(path) + ".autosave").read_text(encoding="utf-8")))


def relink(project: Project, search_dirs: list[str]) -> list[str]:
    """Ko'chirilgan media fayllarni nomi va hajmi bo'yicha qayta topadi. Topilmaganlar ro'yxati qaytadi."""
    missing = []
    for a in project.assets.values():
        if os.path.exists(a.path):
            continue
        name = os.path.basename(a.path.replace("\\", "/"))
        found = None
        for d in search_dirs:
            for root, _, files in os.walk(d):
                if name in files:
                    cand = os.path.join(root, name)
                    if a.size == 0 or os.path.getsize(cand) == a.size:
                        found = cand
                        break
            if found:
                break
        if found:
            a.path = found
        else:
            missing.append(a.path)
    return missing
