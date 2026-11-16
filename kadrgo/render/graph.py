"""Timeline -> FFmpeg filtr grafi.

Preview va export BIR XIL kod yo'lidan o'tadi (farq faqat scale va kodek sozlamalarida).

Asosiy g'oya:
* Perexod bilan bog'langan klip zanjiri = "guruh" (xfade). Guruhlar bir-biriga bog'liq emas.
* Har guruh alohida oqim, kanvasga overlay qilinadi. Shu tufayli istalgan oyna [a, b)
  mustaqil render qilinadi (preview va bo'lak-bo'lak export uchun).
* Bitta klip guruhi oyna chegarasida kesiladi (clamp): uzun klipning o'rtasini preview qilish
  boshidan dekodlashni talab qilmaydi. Effekt vaqti (t0) klip ichidagi o'rniga qarab siljiydi.
* Audio: ovoz o'z grafida, sample aniqligida (adelay ...S), shinalar (dialog/musiqa/sfx),
  musiqa dialog ostida ducking (sidechaincompress), limiter.
* LLM yoki foydalanuvchi matni hech qachon shell buyrug'iga aylanmaydi: graf faqat
  validatsiyalangan model maydonlaridan quriladi.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Optional

from ..core.model import Clip, Project, Track
from ..fx.catalog import EFFECTS, Ctx, TRANSITIONS, fpath, normalize_params
from ..media.probe import AUDIO_EXT


@dataclass
class View:
    clip: Clip
    start: int
    src_in: int
    duration: int

    @property
    def end(self) -> int:
        return self.start + self.duration


@dataclass
class Group:
    track: Track
    views: list

    @property
    def start(self) -> int:
        return self.views[0].start

    @property
    def end(self) -> int:
        return max(v.end for v in self.views)


@dataclass
class Graph:
    inputs: list = field(default_factory=list)       # FFmpeg argument ro'yxati (har kirish uchun)
    script: str = ""
    label: str = ""
    nin: int = 0


@dataclass
class AVPlan:
    a: int                      # so'ralgan oyna boshi (kadr)
    b: int                      # oyna oxiri (kadr)
    a_eff: int                  # haqiqiy render boshi (a dan oldin bo'lishi mumkin)
    frames: int                 # chiqish kadrlari (b - a)
    samples: int                # chiqish audio sample'lari
    video: Graph
    audio: Graph
    width: int
    height: int
    fps: Fraction
    sample_rate: int


def even(x: float) -> int:
    return max(2, int(round(x / 2.0)) * 2)


# ------------------------------------------------------------------ guruhlar
def _clamp_view(c: Clip, a: int, b: int) -> View:
    s, e = max(c.start, a), min(c.end, b)
    if s > c.start:
        # fade mintaqasi ichida boshini kesmaymiz (fade vaqti manfiy bo'lib qoladi)
        if (c.fade_in and s - c.start < c.fade_in) or (c.fade_out and s > c.end - c.fade_out):
            s = c.start
    src_in = c.src_in + int(round((s - c.start) * c.speed))
    return View(c, s, src_in, e - s)


def collect_groups(project: Project, a: int, b: int, kinds: tuple[str, ...] = ("video", "audio")) -> list[Group]:
    groups: list[Group] = []
    for t in project.tracks:
        if t.kind not in kinds or t.hidden:
            continue
        t.sort()
        chain: list[Clip] = []
        full: list[list[Clip]] = []
        for c in t.clips:
            if c.transition_in and chain:
                chain.append(c)
            else:
                if chain:
                    full.append(chain)
                chain = [c]
        if chain:
            full.append(chain)
        for ch in full:
            gs, ge = ch[0].start, max(c.end for c in ch)
            if ge <= a or gs >= b:
                continue
            if len(ch) == 1:
                views = [_clamp_view(ch[0], a, b)]
            else:
                views = [View(c, c.start, c.src_in, c.duration) for c in ch]
            groups.append(Group(t, views))
    return groups


def safe_boundaries(project: Project, lo: int, hi: int) -> list[int]:
    """Bo'lak chegarasi bo'la oladigan kadrlar: perexod zanjiri ichida emas."""
    bad = []
    for t in project.tracks:
        t.sort()
        for c in t.clips:
            if c.transition_in:
                # perexodli zanjir uzluksiz: oldingi klipning boshidan shu klip oxirigacha
                pass
    spans = []
    for g in collect_groups(project, lo, hi):
        if len(g.views) > 1:
            spans.append((g.start, g.end))
    return spans  # type: ignore[return-value]


def plan_chunks(project: Project, chunk_frames: int) -> list[tuple[int, int]]:
    total = project.duration()
    if total <= 0:
        return []
    spans = [(g.start, g.end) for g in collect_groups(project, 0, total) if len(g.views) > 1]

    def inside(x: int) -> Optional[tuple[int, int]]:
        for s, e in spans:
            if s < x < e:
                return (s, e)
        return None

    cuts = [0]
    x = chunk_frames
    while x < total:
        sp = inside(x)
        if sp:
            x = sp[1]
        if x >= total:
            break
        if x > cuts[-1]:
            cuts.append(x)
        x += chunk_frames
    cuts.append(total)
    return list(zip(cuts[:-1], cuts[1:]))


# ------------------------------------------------------------------ yordamchilar
class Lines:
    def __init__(self):
        self.lines: list[str] = []
        self.n = 0

    def new(self, prefix: str = "v") -> str:
        self.n += 1
        return f"{prefix}{self.n}"

    def chain(self, src: str, fragments: list[str]) -> str:
        cur = src
        for frag in fragments:
            if not frag:
                continue
            out = self.new()
            if "[IN]" in frag:
                u = self.new("u")
                self.lines.append(frag.replace("[IN]", f"[{cur}]").replace("[OUT]", f"[{out}]").replace("{u}", u))
            else:
                self.lines.append(f"[{cur}]{frag}[{out}]")
            cur = out
        return cur

    def add(self, s: str):
        self.lines.append(s)

    def script(self) -> str:
        return ";\n".join(self.lines)


def _sec(frames, fps: Fraction) -> str:
    return f"{float(Fraction(frames) / fps):.6f}"


def _fit_fragment(mode: str, W: int, H: int) -> str:
    if mode == "fill":
        return (f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1")
    if mode == "blur":
        return ("[IN]split[a{u}][b{u}];"
                f"[a{{u}}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=40[bg{{u}}];"
                f"[b{{u}}]scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos[fg{{u}}];"
                "[bg{u}][fg{u}]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2,setsar=1[OUT]")
    return (f"scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")


def effect_fragments(clip: Clip, ctx: Ctx) -> list[str]:
    out = []
    for e in clip.effects:
        if not e.enabled or e.fx not in EFFECTS:
            continue
        d = EFFECTS[e.fx]
        out.append(d.build(normalize_params(e.fx, e.params), ctx))
    return out


def _atempo_chain(speed: float) -> list[str]:
    out, s = [], speed
    while s > 2.0:
        out.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        out.append("atempo=0.5")
        s /= 0.5
    if abs(s - 1.0) > 1e-9:
        out.append(f"atempo={s:.6f}")
    return out


def _input_args(project: Project, v: View, bake: dict, kind: str) -> list[str]:
    asset = project.assets[v.clip.asset_id]
    path, base = asset.path, v.clip.src_in
    if v.clip.id in bake:
        path = bake[v.clip.id]
    else:
        base = 0
    fps = project.fps
    src_sec = _sec(v.src_in - (v.clip.src_in if v.clip.id in bake else base), fps)
    if v.clip.id in bake:
        src_sec = _sec(v.src_in - v.clip.src_in, fps)
    length = _sec(int(round(v.duration * v.clip.speed)) + 2, fps)      # +2 kadr zaxira
    if asset.kind == "image":
        return ["-loop", "1", "-framerate", f"{fps.numerator}/{fps.denominator}", "-t", _sec(v.duration + 2, fps),
                "-i", path]
    return ["-ss", src_sec, "-t", length, "-i", path]


# ------------------------------------------------------------------ video graf
def build_video(project: Project, groups: list[Group], a_eff: int, b: int, scale: float,
                bake: dict, burn_subs_file: Optional[str] = None, trim_head: int = 0) -> Graph:
    st = project.settings
    fps = project.fps
    W, H = even(st.width * scale), even(st.height * scale)
    fr = f"{fps.numerator}/{fps.denominator}"
    g = Graph()
    L = Lines()
    dur_frames = b - a_eff
    L.add(f"color=c=black:s={W}x{H}:r={fr}:d={_sec(dur_frames, fps)},format=yuv420p[base]")
    cur = "base"
    vgroups = [x for x in groups if x.track.kind == "video"]
    # pastki trek birinchi, yuqorisi ustidan
    order = {t.id: i for i, t in enumerate(reversed(project.tracks))}
    vgroups.sort(key=lambda x: (order[x.track.id], x.start))
    eps = 0.25 / float(fps)

    for grp in vgroups:
        first = grp.views[0].clip
        acc, acc_len = None, 0
        for i, v in enumerate(grp.views):
            c = v.clip
            asset = project.assets[c.asset_id]
            idx = g.nin
            g.inputs += _input_args(project, v, bake, "video")
            g.nin += 1
            ctx = Ctx(fps=float(fps), w=W, h=H, dur_s=float(Fraction(c.duration) / fps),
                      t0=float(Fraction(v.start - c.start) / fps), scale=scale)
            frags = [f"setpts=(PTS-STARTPTS)/{c.speed:.6f}" if c.speed != 1 else "setpts=PTS-STARTPTS",
                     f"fps=fps={fr}", _fit_fragment(c.fit, W, H)]
            frags += effect_fragments(c, ctx)
            # xfade kernels sample all planes at full resolution. Explicit 4:4:4
            # avoids chroma out-of-bounds access in newer builds accepting 4:2:0.
            frags.append("format=yuv444p" if len(grp.views) > 1 else "format=yuv420p")
            single = len(grp.views) == 1
            # fade (video)
            fin = c.fade_in
            fout = c.fade_out
            tr = c.transition_in
            alpha = single
            if fin:
                frags.append(("format=yuva420p," if alpha else "") +
                             f"fade=t=in:st=0:d={_sec(fin, fps)}" + (":alpha=1" if alpha else ""))
            if fout:
                st_out = Fraction(c.end - fout - v.start) / fps
                frags.append(("format=yuva420p," if alpha and not fin else "") +
                             f"fade=t=out:st={float(st_out):.6f}:d={_sec(fout, fps)}" + (":alpha=1" if alpha else ""))
            if single and c.scale != 1.0:
                frags.append(f"scale=trunc(iw*{c.scale:.4f}/2)*2:trunc(ih*{c.scale:.4f}/2)*2:flags=lanczos")
            if single and c.opacity < 0.999:
                frags.append(f"format=yuva420p,colorchannelmixer=aa={c.opacity:.4f}")
            if i == 0:
                src_label = f"{idx}:v"
                out = L.chain(src_label, frags)
                acc, acc_len = out, v.duration
            else:
                out = L.chain(f"{idx}:v", frags)
                d = tr["duration"]
                kind = tr["kind"] if tr["kind"] in TRANSITIONS else "fade"
                nxt = L.new()
                off = Fraction(acc_len - d) / fps
                transition = f"transition={kind}"
                if kind == "squeezev":
                    # The Win64 built-in squeezev kernel crashes in FFmpeg 9.0.2.
                    # Equivalent full-resolution sampling avoids that native kernel.
                    z = "(0.5+(X/W-0.5)/max(P,0.000001))"
                    x = f"clip({z}*(W-1),0,W-1)"
                    sample = f"if(eq(PLANE,0),a0({x},Y),if(eq(PLANE,1),a1({x},Y),a2({x},Y)))"
                    expr = f"if(gt(P,0),if(between({z},0,1),{sample},B),B)"
                    transition = f"transition=custom:expr='{expr}'"
                L.add(f"[{acc}][{out}]xfade={transition}:duration={_sec(d, fps)}:offset={float(off):.6f}[{nxt}]")
                acc, acc_len = nxt, acc_len + v.duration - d
        s_t = Fraction(grp.start - a_eff) / fps
        e_t = s_t + Fraction(acc_len) / fps
        L.add(f"[{acc}]setpts=PTS-STARTPTS+{float(s_t):.6f}/TB[g{L.n}s]")
        gl = f"g{L.n}s"
        nxt = L.new()
        x = f"(main_w-overlay_w)/2+{int(round(first.x * scale))}"
        y = f"(main_h-overlay_h)/2+{int(round(first.y * scale))}"
        L.add(f"[{cur}][{gl}]overlay=x='{x}':y='{y}':eof_action=pass:format=auto:"
              f"enable='gte(t,{float(s_t) - eps:.6f})*lt(t,{float(e_t) - eps:.6f})'[{nxt}]")
        cur = nxt

    tail = []
    if burn_subs_file:
        fontsdir = os.environ.get("KADRGO_FONTS")
        tail.append(f"subtitles=filename='{fpath(burn_subs_file)}'" +
                    (f":fontsdir='{fpath(fontsdir)}'" if fontsdir else ""))
    if trim_head:
        tail.append(f"trim=start={_sec(trim_head, fps)},setpts=PTS-STARTPTS")
    tail.append("scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=colorspace=bt709:range=limited")
    cur = L.chain(cur, tail)
    g.script, g.label = L.script(), cur
    return g


# ------------------------------------------------------------------ audio graf
def build_audio(project: Project, groups: list[Group], a: int, a_eff: int, b: int, bake: dict) -> tuple[Graph, int]:
    st = project.settings
    fps, sr = project.fps, st.sample_rate
    fr = f"{fps.numerator}/{fps.denominator}"

    def smp(frame: int) -> int:
        return int(round(Fraction(frame) * sr / fps))

    n_out = smp(b) - smp(a)
    g = Graph()
    L = Lines()
    buses: dict[str, list[str]] = {"dialog": [], "music": [], "sfx": []}
    for grp in groups:
        trk = grp.track
        if trk.muted:
            continue
        role = trk.role if trk.kind == "audio" else "dialog"
        role = role if role in buses else "dialog"
        for i, v in enumerate(grp.views):
            c = v.clip
            asset = project.assets[c.asset_id]
            if not asset.has_audio or c.muted:
                continue
            idx = g.nin
            g.inputs += _input_args(project, v, bake, "audio")
            g.nin += 1
            frags = ["asetpts=PTS-STARTPTS"] + _atempo_chain(c.speed)
            frags += [f"aresample={sr}", "aformat=sample_fmts=fltp:channel_layouts=stereo"]
            if c.gain_db:
                frags.append(f"volume={c.gain_db:.2f}dB")
            fin, fout = c.fade_in, c.fade_out
            tr = c.transition_in
            if tr:
                fin = max(fin, tr["duration"])
            nxt = grp.views[i + 1].clip if i + 1 < len(grp.views) else None
            if nxt is not None and nxt.transition_in:
                fout = max(fout, nxt.transition_in["duration"])
            if fin:
                frags.append(f"afade=t=in:st=0:d={_sec(fin, fps)}")
            if fout:
                st_out = Fraction(c.end - fout - v.start) / fps
                frags.append(f"afade=t=out:st={float(st_out):.6f}:d={_sec(fout, fps)}")
            delay = smp(v.start) - smp(a_eff)
            frags.append(f"atrim=end={_sec(v.duration, fps)},asetpts=PTS-STARTPTS")
            if delay > 0:
                frags.append(f"adelay={delay}S|{delay}S:all=1")
            out = L.chain(f"{idx}:a", frags)
            buses[role].append(out)

    def mix(name: str) -> Optional[str]:
        ss = buses[name]
        if not ss:
            return None
        if len(ss) == 1:
            return ss[0]
        o = L.new("m")
        L.add("".join(f"[{s}]" for s in ss) + f"amix=inputs={len(ss)}:normalize=0:duration=longest:dropout_transition=0[{o}]")
        return o

    dlg, mus, sfx = mix("dialog"), mix("music"), mix("sfx")
    parts = []
    if dlg and mus and st.ducking:
        d1, d2, md = L.new("d"), L.new("d"), L.new("m")
        L.add(f"[{dlg}]asplit=2[{d1}][{d2}]")
        L.add(f"[{mus}][{d2}]sidechaincompress=threshold=0.04:ratio=8:attack=15:release=300:makeup=1[{md}]")
        parts += [d1, md]
    else:
        parts += [x for x in (dlg, mus) if x]
    if sfx:
        parts.append(sfx)
    total = smp(b) - smp(a_eff)
    if not parts:
        L.add(f"anullsrc=r={sr}:cl=stereo,atrim=end_sample={total + 8}[sil]")
        cur = "sil"
    elif len(parts) == 1:
        cur = parts[0]
    else:
        cur = L.new("m")
        L.add("".join(f"[{p}]" for p in parts) + f"amix=inputs={len(parts)}:normalize=0:duration=longest:dropout_transition=0[{cur}]")
    head = smp(a) - smp(a_eff)
    tail = [f"apad=whole_len={total}", f"atrim=end_sample={total}", "asetpts=PTS-STARTPTS"]
    if head:
        tail.append(f"atrim=start_sample={head},asetpts=PTS-STARTPTS")
    tail += ["alimiter=limit=0.97:level=0", f"aresample={sr}", "aformat=sample_fmts=flt:channel_layouts=stereo"]
    cur = L.chain(cur, tail)
    g.script, g.label = L.script(), cur
    return g, n_out


# ------------------------------------------------------------------ yig'ma reja
def cues_ass(project: Project, a_eff: int, b: int, style: Optional[dict] = None) -> Optional[str]:
    """Oyna uchun ASS subtitr matni (vaqt a_eff ga nisbatan). Subtitr yo'q bo'lsa None."""
    from ..ai.subtitles import to_ass
    cues = [q for q in project.cues if q.end > a_eff and q.start < b]
    if not cues:
        return None
    return to_ass(project, cues, a_eff, style)


def plan_window(project: Project, a: int, b: int, scale: float = 1.0, bake: Optional[dict] = None,
                subs_path: Optional[str] = None) -> AVPlan:
    """[a, b) oynasi uchun video va audio graf rejasi."""
    bake = bake or {}
    b = max(b, a + 1)
    groups = collect_groups(project, a, b)
    a_eff = min([a] + [g.start for g in groups])
    vgroups = [g for g in groups if g.track.kind == "video"]
    agroups = [g for g in groups]
    # video va audio uchun yagona a_eff (audio guruhlari ham hisobga olinadi)
    video = build_video(project, vgroups, a_eff, b, scale, bake, subs_path, trim_head=a - a_eff)
    audio, n = build_audio(project, agroups, a, a_eff, b, bake)
    st = project.settings
    return AVPlan(a, b, a_eff, b - a, n, video, audio, even(st.width * scale), even(st.height * scale),
                  project.fps, st.sample_rate)
