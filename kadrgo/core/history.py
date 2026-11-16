"""Undo/redo: har bir tahrir (yoki AI tranzaksiyasi) bitta qaytariladigan qadam.

Mexanizm: amaldan oldin/keyin loyiha holatining *o'zgargan qismlari* (trek klip ro'yxatlari,
trek meta, subtitr, marker) saqlanadi. Shu tufayli har qanday amal, shu jumladan AI amali,
ishonchli qaytariladi.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Callable, Optional

from .edit import EditError
from .model import Clip, Cue, Marker, Project, Track


def snapshot(project: Project) -> dict:
    return {
        "meta": [t.meta() for t in project.tracks],
        "clips": {t.id: [c.to_dict() for c in t.clips] for t in project.tracks},
        "cues": [vars(q).copy() for q in project.cues],
        "markers": [vars(m).copy() for m in project.markers],
    }


def state_hash(project: Project) -> str:
    """Loyiha tahrir holatining barqaror hashi (undo/redo testlari uchun)."""
    d = snapshot(project)
    return hashlib.sha1(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def _diff(before: dict, after: dict) -> tuple[dict, dict]:
    b, a = {}, {}
    if before["meta"] != after["meta"]:
        b["meta"], a["meta"] = before["meta"], after["meta"]
    ids = set(before["clips"]) | set(after["clips"])
    bc, ac = {}, {}
    for i in ids:
        if before["clips"].get(i) != after["clips"].get(i):
            bc[i], ac[i] = before["clips"].get(i), after["clips"].get(i)
    if bc or ac:
        b["clips"], a["clips"] = bc, ac
    for k in ("cues", "markers"):
        if before[k] != after[k]:
            b[k], a[k] = before[k], after[k]
    return b, a


def _apply(project: Project, part: dict):
    if "meta" in part:
        old = {t.id: t for t in project.tracks}
        tracks = []
        for m in part["meta"]:
            t = old.get(m["id"]) or Track(m["id"], m["name"], m["kind"], m["role"])
            t.name, t.kind, t.role = m["name"], m["kind"], m["role"]
            t.locked, t.muted, t.hidden = m["locked"], m["muted"], m["hidden"]
            tracks.append(t)
        project.tracks = tracks
    for tid, clips in part.get("clips", {}).items():
        try:
            t = project.track(tid)
        except KeyError:
            continue
        t.clips = [Clip.from_dict(c) for c in (clips or [])]
    if "cues" in part:
        project.cues = [Cue(**c) for c in part["cues"]]
    if "markers" in part:
        project.markers = [Marker(**m) for m in part["markers"]]


@dataclass
class _Entry:
    label: str
    before: dict
    after: dict


class History:
    def __init__(self, project: Project, limit: int = 500):
        self.project = project
        self.limit = limit
        self.undo_stack: list[_Entry] = []
        self.redo_stack: list[_Entry] = []
        self._depth = 0
        self._tx_label = ""
        self._tx_before: Optional[dict] = None
        self.on_change: list[Callable[[], None]] = []
        self.dirty = False

    # -- tranzaksiya -------------------------------------------------
    @contextlib.contextmanager
    def transaction(self, label: str):
        outer = self._depth == 0
        if outer:
            self._tx_label = label
            self._tx_before = snapshot(self.project)
        self._depth += 1
        try:
            yield self.project
        except BaseException:
            self._depth -= 1
            if outer:
                self._restore_before()
            raise
        else:
            self._depth -= 1
            if outer:
                self._commit()

    def _restore_before(self):
        full_before = self._tx_before
        _apply(self.project, {"meta": full_before["meta"], "clips": full_before["clips"],
                              "cues": full_before["cues"], "markers": full_before["markers"]})
        self._tx_before = None

    def _commit(self):
        after = snapshot(self.project)
        b, a = _diff(self._tx_before, after)
        self._tx_before = None
        if not b and not a:
            return
        self.undo_stack.append(_Entry(self._tx_label, b, a))
        if len(self.undo_stack) > self.limit:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.dirty = True
        self._notify()

    def run(self, label: str, fn: Callable, *args, **kwargs):
        """Bitta amalni qaytariladigan qadam sifatida bajaradi. Xatoda hech narsa o'zgarmaydi."""
        with self.transaction(label):
            return fn(self.project, *args, **kwargs)

    # -- undo/redo ---------------------------------------------------
    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    def can_redo(self) -> bool:
        return bool(self.redo_stack)

    def undo(self) -> Optional[str]:
        if not self.undo_stack:
            return None
        e = self.undo_stack.pop()
        _apply(self.project, copy.deepcopy(e.before))
        self.redo_stack.append(e)
        self.dirty = True
        self._notify()
        return e.label

    def redo(self) -> Optional[str]:
        if not self.redo_stack:
            return None
        e = self.redo_stack.pop()
        _apply(self.project, copy.deepcopy(e.after))
        self.undo_stack.append(e)
        self.dirty = True
        self._notify()
        return e.label

    def _notify(self):
        for cb in self.on_change:
            cb()
