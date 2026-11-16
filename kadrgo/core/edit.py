"""Tahrir amallari. Barcha amallar Project ustida ishlaydi va invariantlarni saqlaydi:

* bir trekdagi klip bir-birini qoplamaydi (faqat perexod bo'lgan joyda: B.start == A.end - d);
* qulflangan trek/klipga tegilmaydi (AI ham);
* manba chegarasidan chiqib ketilmaydi.

Undo/redo amallarni History (history.py) o'raydi; bu yerda faqat sof mantiq.
"""
from __future__ import annotations

from typing import Iterable, Optional

from .model import Clip, Cue, Effect, Marker, Project, Track, new_id


class EditError(Exception):
    """Foydalanuvchiga ko'rsatiladigan tahrir xatosi."""


class InvariantError(EditError):
    """Amal natijasi loyiha qoidalarini buzgani uchun qaytarildi."""


def guarded(fn):
    """Amal natijasini tekshiradi: yangi invariant buzilishi chiqsa, hamma narsa AVVALGI holatga qaytariladi.
    Klip obyektlari (identity) saqlanadi, shuning uchun UI havolalari buzilmaydi."""
    import functools

    @functools.wraps(fn)
    def wrapper(project, *args, **kwargs):
        saved = {t.id: [(c, c.to_dict()) for c in t.clips] for t in project.tracks}
        before = validate(project)
        try:
            res = fn(project, *args, **kwargs)
            after = validate(project)
            new = [e for e in after if e not in before] if len(after) >= len(before) else []
            if len(after) > len(before) or new:
                raise InvariantError("Natija loyiha qoidalarini buzadi: " + (new or after)[0].split(": ", 1)[-1])
            return res
        except BaseException:
            for t in project.tracks:
                t.clips = []
                for c, d in saved.get(t.id, []):
                    n = Clip.from_dict(d)
                    c.__dict__.update(n.__dict__)
                    t.clips.append(c)
            raise
    return wrapper


PROP_LIMITS = {
    "gain_db": (-60.0, 24.0), "opacity": (0.0, 1.0), "scale": (0.1, 8.0),
    "x": (-8000, 8000), "y": (-8000, 8000), "fade_in": (0, 10**6), "fade_out": (0, 10**6),
}
PROP_ALLOWED = set(PROP_LIMITS) | {"fit", "muted", "label", "locked", "provenance"}


# ------------------------------------------------------------------ yordamchilar
def _unlocked(track: Track, clip: Optional[Clip] = None):
    if track.locked:
        raise EditError(f"{track.name} treki qulflangan")
    if clip is not None and clip.locked:
        raise EditError("Klip qulflangan")


def _neighbors(track: Track, clip: Clip):
    track.sort()
    i = track.clips.index(clip)
    prev = track.clips[i - 1] if i > 0 else None
    nxt = track.clips[i + 1] if i + 1 < len(track.clips) else None
    return prev, nxt


def _fix_transitions(track: Track):
    """Yaroqsiz perexodlarni tozalaydi va qolib ketgan qoplanishni hal qiladi.

    Perexod shartlari: oldingi klip bor, overlap aynan perexod davomiyligiga teng, ikkala klip yetarlicha uzun.
    Shart buzilsa perexod olib tashlanadi; agar klip hali qoplanib turgan bo'lsa, oldingi klipning
    (perexodda ko'rinmay qoladigan) dumi qirqiladi. Oldingi klip qulflangan bo'lsa, keyingisining boshi qirqiladi.
    """
    for _ in range(len(track.clips) * 2 + 4):
        track.sort()
        changed = False
        for i, c in enumerate(track.clips):
            prev = track.clips[i - 1] if i > 0 else None
            tr = c.transition_in
            if tr:
                d_prev_in = prev.transition_in["duration"] if (prev and prev.transition_in) else 0
                ok = (prev is not None and tr["duration"] >= 1 and prev.end - c.start == tr["duration"]
                      and prev.duration >= tr["duration"] + d_prev_in + 1 and c.duration >= tr["duration"] + 1)
                if not ok:
                    c.transition_in = None
                    changed = True
            if prev is not None and c.start < prev.end and not c.transition_in:
                ov = prev.end - c.start
                if prev.locked:
                    _cut_head(c, prev.end)
                    if c.duration < 1:
                        track.clips.remove(c)
                else:
                    prev.duration -= ov
                    prev.fade_out = min(prev.fade_out, max(prev.duration, 0))
                    if prev.duration < 1:
                        track.clips.remove(prev)
                changed = True
                break
        if not changed:
            return


def _asset_frames(project: Project, clip_or_asset_id) -> Optional[int]:
    a = project.assets[clip_or_asset_id]
    if a.kind == "image":
        return None
    return int(round(a.duration * float(project.fps)))


def _split_at(project: Project, track: Track, clip: Clip, at: int) -> Clip:
    """Klipni `at` da ikkiga bo'ladi; ikkinchisini qaytaradi."""
    if not (clip.start < at < clip.end):
        raise EditError("Kesish nuqtasi klip ichida emas")
    left_dur = at - clip.start
    right = clip.clone(id=new_id("c"), start=at, duration=clip.end - at,
                       src_in=clip.src_in + int(round(left_dur * clip.speed)),
                       fade_in=0, transition_in=None, label=clip.label)
    for e in right.effects:
        e.id = new_id("fx")
    clip.duration = left_dur
    clip.fade_out = 0
    track.clips.append(right)
    track.sort()
    return right


def _clear_range(project: Project, track: Track, a: int, b: int, keep: Iterable[str] = ()):
    keep = set(keep)
    for c in list(track.clips):
        if c.id in keep or c.end <= a or c.start >= b:
            continue
        _unlocked(track, c)
        if a <= c.start and c.end <= b:
            track.clips.remove(c)
        elif c.start < a and c.end > b:
            _split_at(project, track, c, b)
            _cut_tail(c, a)
        elif c.start < a:
            _cut_tail(c, a)
        else:
            _cut_head(c, b)
    _fix_transitions(track)


def _cut_tail(c: Clip, new_end: int):
    c.duration = new_end - c.start
    c.fade_out = min(c.fade_out, c.duration)


def _cut_head(c: Clip, new_start: int):
    delta = new_start - c.start
    c.src_in += int(round(delta * c.speed))
    c.duration -= delta
    c.start = new_start
    c.fade_in = min(c.fade_in, c.duration)
    c.transition_in = None


def _check_kind(project: Project, track: Track, asset_id: str):
    a = project.assets.get(asset_id)
    if a is None:
        raise EditError("Media topilmadi")
    if track.kind == "video" and not (a.has_video or a.kind == "image"):
        raise EditError("Video trekka faqat video/rasm qo'yiladi")
    if track.kind == "audio" and not a.has_audio:
        raise EditError("Audio trekka faqat ovozli media qo'yiladi")


# ------------------------------------------------------------------ klip amallari
@guarded
def add_clip(project: Project, track_id: str, asset_id: str, start: int, src_in: int = 0,
             duration: Optional[int] = None, mode: str = "overwrite", **props) -> Clip:
    track = project.track(track_id)
    _unlocked(track)
    _check_kind(project, track, asset_id)
    if start < 0:
        raise EditError("Boshlanish manfiy bo'lishi mumkin emas")
    a = project.assets[asset_id]
    total = _asset_frames(project, asset_id)
    if duration is None:
        duration = int(round(5 * float(project.fps))) if total is None else total - src_in
    if duration < 1:
        raise EditError("Klip davomiyligi kamida 1 kadr")
    if total is not None and src_in + duration > total + 1:
        raise EditError("Klip manba uzunligidan oshib ketdi")
    clip = Clip(id=new_id("c"), asset_id=asset_id, start=start, src_in=src_in, duration=duration,
                label=props.pop("label", a.path.replace("\\", "/").split("/")[-1]))
    for k, v in props.items():
        setattr(clip, k, v)
    if mode == "insert":
        for c in track.clips:
            if c.start >= start:
                _unlocked(track, c)
                c.start += duration
        # kesishgan klipni bo'lamiz
        for c in list(track.clips):
            if c.start < start < c.end:
                _unlocked(track, c)
                right = _split_at(project, track, c, start)
                right.start += duration
    else:
        _clear_range(project, track, start, start + duration)
    track.clips.append(clip)
    _fix_transitions(track)
    return clip


@guarded
def delete_clip(project: Project, clip_id: str):
    """Lift: klip olinadi, bo'shliq qoladi."""
    track, c = project.find(clip_id)
    _unlocked(track, c)
    track.clips.remove(c)
    _fix_transitions(track)


@guarded
def ripple_delete(project: Project, clip_id: str):
    track, c = project.find(clip_id)
    _unlocked(track, c)
    later = [x for x in track.clips if x.start >= c.end and x is not c]
    for x in later:
        _unlocked(track, x)
    d = c.duration
    track.clips.remove(c)
    for x in later:
        x.start -= d
    _fix_transitions(track)


@guarded
def split_clip(project: Project, clip_id: str, at: int) -> Clip:
    track, c = project.find(clip_id)
    _unlocked(track, c)
    _, nxt = _neighbors(track, c)
    d_in = c.transition_in["duration"] if c.transition_in else 0
    d_next = nxt.transition_in["duration"] if (nxt and nxt.transition_in) else 0
    if c.start < at < c.end and (at - c.start < d_in + 1 or c.end - at < d_next + 1):
        raise EditError("Perexod ichida klipni bo'lib bo'lmaydi")
    return _split_at(project, track, c, at)


@guarded
def move_clip(project: Project, clip_id: str, new_start: int, new_track_id: Optional[str] = None):
    track, c = project.find(clip_id)
    _unlocked(track, c)
    dest = project.track(new_track_id) if new_track_id else track
    _unlocked(dest)
    if dest.kind != track.kind:
        raise EditError("Video klipni audio trekka ko'chirib bo'lmaydi")
    _check_kind(project, dest, c.asset_id)
    if new_start < 0:
        raise EditError("Boshlanish manfiy bo'lishi mumkin emas")
    prev, nxt = _neighbors(track, c)
    if c.transition_in or (nxt is not None and nxt.transition_in):
        raise EditError("Perexodli klipni ko'chirishdan oldin perexodni olib tashlang")
    track.clips.remove(c)
    c.start = new_start
    _clear_range(project, dest, c.start, c.end)
    dest.clips.append(c)
    _fix_transitions(track)
    _fix_transitions(dest)


@guarded
def trim_start(project: Project, clip_id: str, new_start: int):
    track, c = project.find(clip_id)
    _unlocked(track, c)
    if c.transition_in:
        raise EditError("Perexodli klip boshini qirqishdan oldin perexodni olib tashlang")
    if not (0 <= new_start < c.end):
        raise EditError("Noto'g'ri qirqish nuqtasi")
    delta = new_start - c.start
    new_src = c.src_in + int(round(delta * c.speed))
    if new_src < 0:
        raise EditError("Manba boshidan oldinga chiqib bo'lmaydi")
    prev, _ = _neighbors(track, c)
    if prev is not None and new_start < prev.end:
        raise EditError("Oldingi klip bilan to'qnashadi")
    c.src_in, c.duration, c.start = new_src, c.duration - delta, new_start
    c.fade_in = min(c.fade_in, c.duration)


@guarded
def trim_end(project: Project, clip_id: str, new_end: int):
    track, c = project.find(clip_id)
    _unlocked(track, c)
    if new_end <= c.start:
        raise EditError("Klip kamida 1 kadr bo'lishi kerak")
    _, nxt = _neighbors(track, c)
    if nxt is not None and nxt.transition_in:
        raise EditError("Perexod oldidan qirqishdan oldin perexodni olib tashlang")
    if nxt is not None and new_end > nxt.start:
        raise EditError("Keyingi klip bilan to'qnashadi")
    total = _asset_frames(project, c.asset_id)
    if total is not None and c.src_in + (new_end - c.start) * c.speed > total + 1:
        raise EditError("Manba tugadi")
    c.duration = new_end - c.start
    c.fade_out = min(c.fade_out, c.duration)


@guarded
def set_speed(project: Project, clip_id: str, speed: float, ripple: bool = True):
    if not (0.1 <= speed <= 16):
        raise EditError("Tezlik 0.1x..16x oralig'ida bo'lishi kerak")
    track, c = project.find(clip_id)
    _unlocked(track, c)
    _, nxt = _neighbors(track, c)
    if nxt is not None and nxt.transition_in:
        raise EditError("Perexodli klip tezligini o'zgartirishdan oldin perexodni olib tashlang")
    new_dur = max(1, int(round(c.src_frames / speed)))
    delta = new_dur - c.duration
    later = [x for x in track.clips if x.start >= c.end and x is not c]
    if delta > 0 and not ripple and later and c.start + new_dur > later[0].start:
        raise EditError("Keyingi klip bilan to'qnashadi")
    if ripple:
        for x in later:
            _unlocked(track, x)
            x.start += delta
    c.speed, c.duration = speed, new_dur
    c.fade_in, c.fade_out = min(c.fade_in, new_dur), min(c.fade_out, new_dur)


def set_props(project: Project, clip_id: str, **props):
    track, c = project.find(clip_id)
    if set(props) != {"locked"}:
        _unlocked(track, c)
    for k, v in props.items():
        if k not in PROP_ALLOWED:
            raise EditError(f"Noma'lum xususiyat: {k}")
        if k in PROP_LIMITS:
            lo, hi = PROP_LIMITS[k]
            v = min(max(v, lo), hi)
        if k in ("fade_in", "fade_out"):
            v = min(int(v), c.duration)
        if k == "fit" and v not in ("fit", "fill", "blur"):
            raise EditError("fit: fit | fill | blur")
        setattr(c, k, v)


# ------------------------------------------------------------------ perexodlar
@guarded
def set_transition(project: Project, clip_id: str, kind: str, duration: int):
    """B klipning boshiga perexod: A bilan `duration` kadr qoplanadi (timeline qisqaradi)."""
    from ..fx.catalog import TRANSITIONS
    if kind not in TRANSITIONS:
        raise EditError(f"Noma'lum perexod: {kind}")
    track, b = project.find(clip_id)
    _unlocked(track, b)
    if b.transition_in:
        remove_transition(project, clip_id)
    prev, nxt = _neighbors(track, b)
    if prev is None or prev.end != b.start:
        raise EditError("Perexod uchun ikki klip yonma-yon bo'lishi kerak")
    d_prev_in = prev.transition_in["duration"] if prev.transition_in else 0
    d_next = nxt.transition_in["duration"] if (nxt and nxt.transition_in) else 0
    limit = min(prev.duration - d_prev_in, b.duration - d_next) - 1
    duration = min(int(duration), limit)
    if duration < 1:
        raise EditError("Klip perexod uchun juda qisqa")
    later = track.clips[track.clips.index(b):]
    for x in later:
        _unlocked(track, x)
        x.start -= duration
    b.transition_in = {"kind": kind, "duration": duration}
    track.sort()


@guarded
def remove_transition(project: Project, clip_id: str):
    track, b = project.find(clip_id)
    _unlocked(track, b)
    tr = b.transition_in
    if not tr:
        return
    track.sort()
    later = track.clips[track.clips.index(b):]
    for x in later:
        _unlocked(track, x)
        x.start += tr["duration"]
    b.transition_in = None
    track.sort()


# ------------------------------------------------------------------ effektlar
def add_effect(project: Project, clip_id: str, fx: str, params: Optional[dict] = None,
               index: Optional[int] = None) -> Effect:
    from ..fx.catalog import EFFECTS, normalize_params
    if fx not in EFFECTS:
        raise EditError(f"Noma'lum effekt: {fx}")
    track, c = project.find(clip_id)
    _unlocked(track, c)
    e = Effect(fx=fx, params=normalize_params(fx, params or {}))
    if index is None:
        c.effects.append(e)
    else:
        c.effects.insert(index, e)
    return e


def update_effect(project: Project, clip_id: str, effect_id: str, **params):
    from ..fx.catalog import normalize_params
    track, c = project.find(clip_id)
    _unlocked(track, c)
    for e in c.effects:
        if e.id == effect_id:
            merged = dict(e.params)
            merged.update(params)
            e.params = normalize_params(e.fx, merged)
            return
    raise EditError("Effekt topilmadi")


def toggle_effect(project: Project, clip_id: str, effect_id: str, enabled: bool):
    track, c = project.find(clip_id)
    _unlocked(track, c)
    for e in c.effects:
        if e.id == effect_id:
            e.enabled = enabled
            return
    raise EditError("Effekt topilmadi")


def remove_effect(project: Project, clip_id: str, effect_id: str):
    track, c = project.find(clip_id)
    _unlocked(track, c)
    c.effects = [e for e in c.effects if e.id != effect_id]


def move_effect(project: Project, clip_id: str, effect_id: str, new_index: int):
    track, c = project.find(clip_id)
    _unlocked(track, c)
    e = next((x for x in c.effects if x.id == effect_id), None)
    if e is None:
        raise EditError("Effekt topilmadi")
    c.effects.remove(e)
    c.effects.insert(max(0, min(new_index, len(c.effects))), e)


# ------------------------------------------------------------------ AI yordamchi amal
@guarded
def replace_with_segments(project: Project, clip_id: str, segments: list[tuple[int, int]]) -> list[Clip]:
    """Klipni manbaning berilgan qismlariga (src kadrlari) almashtiradi va bo'shliqni yopadi.

    Jump-cut / sukunatni olib tashlash uchun. Tezlik 1x bo'lishi shart.
    """
    track, c = project.find(clip_id)
    _unlocked(track, c)
    if c.speed != 1.0 or c.transition_in:
        raise EditError("Faqat 1x tezlikdagi, perexodsiz klip bo'linadi")
    lo, hi = c.src_in, c.src_in + c.duration
    segs = []
    for a, b in segments:
        a, b = max(a, lo), min(b, hi)
        if b - a >= 1:
            segs.append((a, b))
    if not segs:
        raise EditError("Saqlanadigan qism topilmadi")
    later = [x for x in track.clips if x.start >= c.end and x is not c]
    for x in later:
        _unlocked(track, x)
    nxt = later[0] if later else None
    if nxt is not None and nxt.transition_in:
        raise EditError("Keyingi klipda perexod bor")
    track.clips.remove(c)
    out, pos = [], c.start
    for i, (a, b) in enumerate(segs):
        n = c.clone(id=new_id("c"), start=pos, src_in=a, duration=b - a, transition_in=None,
                    fade_in=c.fade_in if i == 0 else 0,
                    fade_out=c.fade_out if i == len(segs) - 1 else 0,
                    provenance=c.provenance or "ai:jump-cut")
        for e in n.effects:
            e.id = new_id("fx")
        out.append(n)
        pos += b - a
    new_total = pos - c.start
    shift = new_total - c.duration
    for x in later:
        x.start += shift
    track.clips.extend(out)
    _fix_transitions(track)
    return out


# ------------------------------------------------------------------ treklar, subtitr, marker
def add_track(project: Project, kind: str, role: Optional[str] = None, name: Optional[str] = None) -> Track:
    if kind not in ("video", "audio"):
        raise EditError("Trek turi video yoki audio")
    n = sum(1 for t in project.tracks if t.kind == kind) + 1
    while any(t.id == (("V" if kind == "video" else "A") + str(n)) for t in project.tracks):
        n += 1
    tid = ("V" if kind == "video" else "A") + str(n)
    role = role or ("video" if kind == "video" else "sfx")
    t = Track(tid, name or f"{tid}", kind, role)
    if kind == "video":
        project.tracks.insert(0, t)         # yuqoridagi treklar tepada
    else:
        project.tracks.append(t)
    return t


def set_track_flag(project: Project, track_id: str, **flags):
    t = project.track(track_id)
    for k, v in flags.items():
        if k not in ("locked", "muted", "hidden", "name"):
            raise EditError(f"Noma'lum trek xususiyati: {k}")
        setattr(t, k, v)


def add_cue(project: Project, start: int, end: int, text: str, style: str = "default",
            confidence: float = 1.0) -> Cue:
    if end <= start:
        raise EditError("Subtitr oxiri boshidan keyin bo'lishi kerak")
    c = Cue(new_id("q"), start, end, text, style, confidence)
    project.cues.append(c)
    project.cues.sort(key=lambda q: q.start)
    return c


def update_cue(project: Project, cue_id: str, **changes):
    for q in project.cues:
        if q.id == cue_id:
            for k, v in changes.items():
                setattr(q, k, v)
            project.cues.sort(key=lambda z: z.start)
            return
    raise EditError("Subtitr topilmadi")


def remove_cue(project: Project, cue_id: str):
    project.cues = [q for q in project.cues if q.id != cue_id]


def set_markers(project: Project, markers: list[Marker], kind: Optional[str] = None):
    """kind berilsa, faqat shu turdagi markerlar almashtiriladi (masalan 'beat')."""
    keep = [m for m in project.markers if kind is not None and m.kind != kind]
    project.markers = sorted(keep + list(markers), key=lambda m: m.frame)


# ------------------------------------------------------------------ tekshiruv
def validate(project: Project) -> list[str]:
    """Loyiha yaxlitligini tekshiradi. Bo'sh ro'yxat = hammasi joyida."""
    errs: list[str] = []
    fps = float(project.fps)
    for t in project.tracks:
        t.sort()
        max_end, prev = 0, None
        for c in t.clips:
            where = f"{t.id}/{c.label or c.id}"
            a = project.assets.get(c.asset_id)
            if a is None:
                errs.append(f"{where}: media yo'q")
                continue
            if c.duration < 1 or c.start < 0 or c.src_in < 0:
                errs.append(f"{where}: noto'g'ri vaqt")
            if a.kind != "image":
                total = a.duration * fps
                if c.src_in + c.duration * c.speed > total + 1.5:
                    errs.append(f"{where}: manba uzunligidan oshgan")
            if t.kind == "video" and not (a.has_video or a.kind == "image"):
                errs.append(f"{where}: video trekda videosiz media")
            if t.kind == "audio" and not a.has_audio:
                errs.append(f"{where}: audio trekda ovozsiz media")
            if c.fade_in + c.fade_out > c.duration + 1e-9 and c.fade_in + c.fade_out > c.duration:
                errs.append(f"{where}: fade klipdan uzun")
            tr = c.transition_in
            if prev is not None and c.start < max_end:
                ok = bool(tr) and prev.end == max_end and prev.end - c.start == tr["duration"]
                if not ok:
                    errs.append(f"{where}: klip qoplanishi (perexodsiz)")
            if tr:
                if prev is None:
                    errs.append(f"{where}: perexodning oldingi klipi yo'q")
                else:
                    din = prev.transition_in["duration"] if prev.transition_in else 0
                    if prev.duration < din + tr["duration"] + 1 or c.duration < tr["duration"] + 1:
                        errs.append(f"{where}: perexod klipdan uzun")
            max_end = max(max_end, c.end)
            prev = c
    for q in project.cues:
        if q.end <= q.start:
            errs.append(f"subtitr {q.id}: noto'g'ri vaqt")
    return errs
