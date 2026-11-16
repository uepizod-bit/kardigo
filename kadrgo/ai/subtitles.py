"""Subtitr: SRT <-> Cue, ASS (burn-in) generatsiyasi. O', G', ʻ va kirill matn o'zgarishsiz saqlanadi."""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Optional

from ..core.model import Cue, Project, new_id

DEFAULT_STYLE = {
    "font": "Inter", "size_pct": 4.6, "color": "FFFFFF", "outline_color": "000000", "outline": 3.0,
    "shadow": 1.0, "bold": 1, "margin_v_pct": 14.0, "margin_h_pct": 7.0, "highlight": "F6B84A",
}


def _srt_time(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_time(sec: float) -> str:
    cs = int(round(sec * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def cues_to_srt(project: Project, cues: Optional[list] = None) -> str:
    cues = project.cues if cues is None else cues
    fps = project.fps
    out = []
    for i, q in enumerate(cues, 1):
        out.append(f"{i}\n{_srt_time(float(Fraction(q.start) / fps))} --> "
                   f"{_srt_time(float(Fraction(q.end) / fps))}\n{q.text}\n")
    return "\n".join(out)


_TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


def _parse_ts(s: str) -> float:
    m = _TS.match(s.strip())
    if not m:
        raise ValueError(f"Noto'g'ri vaqt: {s}")
    h, mi, se, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(se) + int(ms.ljust(3, "0")[:3]) / 1000


def srt_to_cues(project: Project, text: str) -> list[Cue]:
    fps = float(project.fps)
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = [l for l in block.split("\n") if l.strip() != ""]
        if len(lines) < 2:
            continue
        ti = 1 if "-->" in lines[1] else 0
        if "-->" not in lines[ti]:
            continue
        a, b = lines[ti].split("-->")
        s, e = round(_parse_ts(a) * fps), round(_parse_ts(b.split()[0]) * fps)
        if e <= s:
            e = s + 1
        cues.append(Cue(new_id("q"), s, e, "\n".join(lines[ti + 1:])))
    return cues


def _esc(t: str) -> str:
    return t.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def to_ass(project: Project, cues: list, offset_frames: int = 0, style: Optional[dict] = None) -> str:
    """ASS matni. Vaqtlar offset_frames ga nisbatan (oyna boshi)."""
    st = dict(DEFAULT_STYLE)
    st["font"] = getattr(project.settings, "sub_font", st["font"]) or st["font"]
    st.update(style or {})
    W, H = project.settings.width, project.settings.height
    fps = project.fps
    size = int(H * st["size_pct"] / 100)
    mv = int(H * st["margin_v_pct"] / 100)       # platforma UI dan xavfsiz joy
    mh = int(W * st["margin_h_pct"] / 100)

    def bgr(c: str) -> str:
        c = c.lstrip("#")
        return f"&H00{c[4:6]}{c[2:4]}{c[0:2]}"

    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\n"
            f"ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,"
            "Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,"
            "MarginL,MarginR,MarginV,Encoding\n"
            f"Style: Default,{st['font']},{size},{bgr(st['color'])},{bgr(st['highlight'])},{bgr(st['outline_color'])},"
            f"&H80000000,{st['bold']},0,0,0,100,100,0,0,1,{st['outline']},{st['shadow']},2,{mh},{mh},{mv},1\n\n"
            "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    lines = []
    for q in cues:
        s = float(Fraction(max(q.start - offset_frames, 0)) / fps)
        e = float(Fraction(q.end - offset_frames) / fps)
        if e <= 0:
            continue
        lines.append(f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},Default,,0,0,0,,{_esc(q.text)}")
    return head + "\n".join(lines) + "\n"
