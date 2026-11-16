"""Loyiha modeli: versiyalangan, tahrirlanadigan, JSON ga saqlanadigan.

Barcha tahrir vaqtlari LOYIHA KADRLARIDA (int). Manba vaqti ham loyiha kadrlarida
(src_in). Shu tufayli preview va export bir xil vaqt xaritasidan foydalanadi.
"""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field, fields
from fractions import Fraction
from typing import Optional

FORMAT = "kadrgo.project"
VERSION = 1

NTSC = {23.976: Fraction(24000, 1001), 29.97: Fraction(30000, 1001), 59.94: Fraction(60000, 1001)}


def new_id(prefix: str = "x") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def parse_fps(v) -> Fraction:
    if isinstance(v, Fraction):
        return v
    if isinstance(v, str):
        return Fraction(v)
    f = float(v)
    for k, fr in NTSC.items():
        if abs(f - k) < 0.01:
            return fr
    return Fraction(f).limit_denominator(1001)


def fps_str(fps: Fraction) -> str:
    return f"{fps.numerator}/{fps.denominator}"


@dataclass
class Asset:
    id: str
    path: str
    kind: str                    # video | audio | image
    duration: float = 0.0        # soniya
    width: int = 0
    height: int = 0
    fps: str = "0/1"
    has_video: bool = False
    has_audio: bool = False
    audio_rate: int = 48000
    rotation: int = 0
    vfr: bool = False
    hash: str = ""
    size: int = 0

    def frames(self, project_fps: Fraction) -> int:
        return int(self.duration * float(project_fps))


@dataclass
class Effect:
    fx: str
    params: dict = field(default_factory=dict)
    enabled: bool = True
    id: str = field(default_factory=lambda: new_id("fx"))


@dataclass
class Clip:
    id: str
    asset_id: str
    start: int                   # timeline kadri
    src_in: int                  # manba kadri (loyiha fps da)
    duration: int                # timeline kadrlari
    speed: float = 1.0
    effects: list = field(default_factory=list)       # list[Effect]
    gain_db: float = 0.0
    fade_in: int = 0
    fade_out: int = 0
    opacity: float = 1.0
    scale: float = 1.0
    x: int = 0
    y: int = 0
    fit: str = "fit"             # fit | fill | blur
    transition_in: Optional[dict] = None   # {"kind": str, "duration": int}
    locked: bool = False
    muted: bool = False
    label: str = ""
    provenance: str = ""         # masalan "ai:rough-cut" yoki "generated:veo"

    @property
    def end(self) -> int:
        return self.start + self.duration

    @property
    def src_frames(self) -> float:
        return self.duration * self.speed

    def to_dict(self) -> dict:
        d = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "effects"}
        d["effects"] = [{"fx": e.fx, "params": dict(e.params), "enabled": e.enabled, "id": e.id}
                        for e in self.effects]
        d["transition_in"] = dict(self.transition_in) if self.transition_in else None
        return d

    @staticmethod
    def from_dict(d: dict) -> "Clip":
        d = dict(d)
        effs = [Effect(fx=e["fx"], params=dict(e.get("params", {})), enabled=e.get("enabled", True),
                       id=e.get("id") or new_id("fx")) for e in d.pop("effects", [])]
        names = {f.name for f in fields(Clip)}
        c = Clip(**{k: v for k, v in d.items() if k in names})
        c.effects = effs
        return c

    def clone(self, **changes) -> "Clip":
        c = Clip.from_dict(self.to_dict())
        for k, v in changes.items():
            setattr(c, k, v)
        return c


@dataclass
class Track:
    id: str
    name: str
    kind: str                    # video | audio
    role: str = "video"          # video | dialog | music | sfx
    clips: list = field(default_factory=list)
    locked: bool = False
    muted: bool = False
    hidden: bool = False

    def meta(self) -> dict:
        return {"id": self.id, "name": self.name, "kind": self.kind, "role": self.role,
                "locked": self.locked, "muted": self.muted, "hidden": self.hidden}

    def sort(self):
        self.clips.sort(key=lambda c: (c.start, c.id))


@dataclass
class Cue:
    id: str
    start: int
    end: int
    text: str
    style: str = "default"
    confidence: float = 1.0


@dataclass
class Marker:
    frame: int
    label: str = ""
    kind: str = "user"           # user | beat | ai


@dataclass
class Settings:
    width: int = 1080
    height: int = 1920
    fps: str = "30/1"
    sample_rate: int = 48000
    color_space: str = "rec709"
    ducking: bool = True
    sub_font: str = "Inter"

    @property
    def fps_frac(self) -> Fraction:
        return Fraction(self.fps)


PRESETS = {
    "reels":   Settings(1080, 1920, "30/1"),
    "youtube": Settings(1920, 1080, "25/1"),
    "square":  Settings(1080, 1080, "30/1"),
    "cinema":  Settings(1920, 1080, "24000/1001"),
}


class Project:
    def __init__(self, name: str = "Nomsiz loyiha", settings: Optional[Settings] = None):
        self.name = name
        self.uid = new_id("p")
        self.settings = settings or Settings()
        self.assets: dict[str, Asset] = {}
        self.tracks: list[Track] = [
            Track("V2", "V2 REAKSIYA", "video", "video"),
            Track("V1", "V1 ASOSIY", "video", "video"),
            Track("A1", "A1 DIALOG", "audio", "dialog"),
            Track("A2", "A2 MUSIQA", "audio", "music"),
            Track("A3", "A3 SFX", "audio", "sfx"),
        ]
        self.cues: list[Cue] = []
        self.markers: list[Marker] = []

    # -- qidiruv ------------------------------------------------------
    @property
    def fps(self) -> Fraction:
        return self.settings.fps_frac

    def track(self, track_id: str) -> Track:
        for t in self.tracks:
            if t.id == track_id:
                return t
        raise KeyError(track_id)

    def find(self, clip_id: str):
        for t in self.tracks:
            for c in t.clips:
                if c.id == clip_id:
                    return t, c
        raise KeyError(clip_id)

    def all_clips(self):
        for t in self.tracks:
            for c in t.clips:
                yield t, c

    def duration(self) -> int:
        return max((c.end for _, c in self.all_clips()), default=0)

    def frame_to_sec(self, f) -> float:
        return float(Fraction(f) / self.fps)

    def sec_to_frame(self, s: float) -> int:
        return int(round(s * float(self.fps)))

    # -- serializatsiya ----------------------------------------------
    def to_dict(self) -> dict:
        return {
            "format": FORMAT, "version": VERSION, "name": self.name, "uid": self.uid,
            "settings": {f.name: getattr(self.settings, f.name) for f in fields(Settings)},
            "assets": {k: {f.name: getattr(a, f.name) for f in fields(Asset)} for k, a in self.assets.items()},
            "tracks": [dict(t.meta(), clips=[c.to_dict() for c in t.clips]) for t in self.tracks],
            "cues": [vars(c).copy() for c in self.cues],
            "markers": [vars(m).copy() for m in self.markers],
        }

    @staticmethod
    def from_dict(d: dict) -> "Project":
        from .migrate import migrate
        d = migrate(d)
        p = Project(d.get("name", "Loyiha"), Settings(**d["settings"]))
        p.uid = d.get("uid") or p.uid
        an = {f.name for f in fields(Asset)}
        p.assets = {k: Asset(**{x: y for x, y in a.items() if x in an}) for k, a in d["assets"].items()}
        p.tracks = []
        for td in d["tracks"]:
            t = Track(td["id"], td["name"], td["kind"], td.get("role", "video"),
                      locked=td.get("locked", False), muted=td.get("muted", False),
                      hidden=td.get("hidden", False))
            t.clips = [Clip.from_dict(c) for c in td["clips"]]
            t.sort()
            p.tracks.append(t)
        p.cues = [Cue(**c) for c in d.get("cues", [])]
        p.markers = [Marker(**m) for m in d.get("markers", [])]
        return p

    def clone(self) -> "Project":
        return Project.from_dict(copy.deepcopy(self.to_dict()))
