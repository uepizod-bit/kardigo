"""Effekt, look va perexodlar katalogi.

Har effekt: parametr tavsifi (UI slayderlari shundan quriladi) + FFmpeg filtr quruvchi.
Preview va export bir xil quruvchidan foydalanadi, shuning uchun natija farq qilmaydi.

Quruvchi qaytaradi:
  * oddiy filtr zanjiri ("eq=contrast=1.1,vignette=0.5"), yoki
  * murakkab graf: [IN] va [OUT] belgilari + {u} noyob qo'shimcha.
Bo'sh qator = effekt hech narsa qilmaydi.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class P:
    key: str
    label: str
    lo: float = 0.0
    hi: float = 1.0
    default: float = 0.0
    step: float = 0.01
    choices: Optional[tuple] = None
    type: str = "float"          # float | str | bool


@dataclass
class Ctx:
    fps: float
    w: int
    h: int
    dur_s: float                 # klipning to'liq davomiyligi (soniya)
    t0: float = 0.0              # ko'rinayotgan oyna klip ichida qayerdan boshlanadi (soniya)
    scale: float = 1.0           # preview kichraytirish koeffitsiyenti


@dataclass
class EffectDef:
    id: str
    name: str
    category: str
    params: list
    build: Callable[[dict, Ctx], str]
    bake: bool = False           # eksportdan oldin alohida bosqichda pishiriladi (masalan retush)
    doc: str = ""


def fpath(p: str) -> str:
    """FFmpeg filtr argumenti uchun yo'lni xavfsiz qiladi (Windows C:\\ va ':' uchun)."""
    p = p.replace("\\", "/")
    p = p.replace(":", r"\:").replace("'", r"\'").replace("[", r"\[").replace("]", r"\]").replace(",", r"\,")
    return p


def _n(x: float, nd: int = 4) -> str:
    return f"{x:.{nd}f}".rstrip("0").rstrip(".") or "0"


def _blend_mix(chain: str, intensity: float) -> str:
    """chain natijasini asl bilan intensity bo'yicha aralashtiradi."""
    if intensity >= 0.999:
        return chain + ",format=yuv420p"
    return ("[IN]split[a{u}][b{u}];[b{u}]" + chain + ",format=yuv420p[g{u}];"
            "[a{u}][g{u}]blend=all_mode=normal:all_opacity=" + _n(intensity) + "[OUT]")


# ------------------------------------------------------------------ 24 original look
LOOKS: dict[str, tuple[str, str, str]] = {
    # id: (guruh, nomi, filtr zanjiri)
    "clean_bright": ("Clean", "Yorqin toza", "eq=brightness=0.04:contrast=1.06:saturation=1.08,unsharp=5:5:0.4"),
    "clean_soft": ("Clean", "Yumshoq toza", "eq=contrast=0.95:saturation=0.95:brightness=0.03,gblur=sigma=0.6"),
    "clean_pop": ("Clean", "Jonli rang", "eq=contrast=1.12:saturation=1.25,vibrance=intensity=0.3"),
    "clean_matte": ("Clean", "Mat", "curves=all='0/0.06 0.5/0.5 1/0.94',eq=saturation=0.92"),
    "clean_cool": ("Clean", "Sovuq toza", "colorbalance=rm=-0.04:bm=0.07:rh=-0.03:bh=0.05,eq=contrast=1.05:saturation=1.05"),
    "clean_warm": ("Clean", "Iliq toza", "colorbalance=rm=0.06:bm=-0.06:rh=0.04:bh=-0.04,eq=contrast=1.04:saturation=1.08"),
    "wed_cream": ("Wedding", "Qaymoq", "curves=all='0/0.05 0.5/0.52 1/0.97',colorbalance=rm=0.04:gm=0.01:bm=-0.04:rh=0.03:bh=-0.02,eq=saturation=0.9:brightness=0.03"),
    "wed_gold": ("Wedding", "Oltin", "colorbalance=rs=0.03:bs=-0.03:rm=0.07:bm=-0.08:rh=0.08:bh=-0.06,eq=contrast=1.06:saturation=1.1"),
    "wed_airy": ("Wedding", "Yengil havo", "eq=brightness=0.07:contrast=0.92:saturation=0.88,curves=all='0/0.08 1/1'"),
    "wed_rose": ("Wedding", "Atirgul", "colorbalance=rm=0.05:bm=0.03:gm=-0.03:rh=0.03:bh=0.02,eq=saturation=1.05:brightness=0.03"),
    "wed_ivory": ("Wedding", "Fil suyagi", "eq=saturation=0.78:brightness=0.04:contrast=1.02,colorbalance=rm=0.02:bm=-0.03"),
    "wed_sunset": ("Wedding", "Quyosh botishi", "colorbalance=rs=0.04:bs=0.05:rm=0.09:bm=-0.07:rh=0.1:bh=-0.08:gh=0.02,eq=contrast=1.1:saturation=1.15"),
    "drama_teal_orange": ("Drama", "Teal-orange", "colorbalance=rs=-0.08:gs=0.02:bs=0.12:rm=-0.02:bm=0.03:rh=0.12:bh=-0.1,eq=contrast=1.15:saturation=1.1"),
    "drama_noir": ("Drama", "Noir", "eq=saturation=0:contrast=1.3:brightness=-0.03,curves=all='0/0 0.3/0.2 0.7/0.8 1/1'"),
    "drama_desat": ("Drama", "Siyqa rang", "eq=saturation=0.55:contrast=1.2:brightness=-0.02"),
    "drama_cold": ("Drama", "Sovuq drama", "colorbalance=rs=-0.04:bs=0.1:rm=-0.04:bm=0.09:rh=-0.02:bh=0.05,eq=contrast=1.14:saturation=0.9:brightness=-0.02"),
    "drama_warm_shadow": ("Drama", "Iliq soya", "colorbalance=rs=0.08:gs=0.02:bs=-0.02:rm=0.04,eq=contrast=1.18:saturation=1.05:brightness=-0.03"),
    "drama_bleach": ("Drama", "Bleach", "eq=saturation=0.6:contrast=1.35,curves=all='0/0 0.25/0.18 0.75/0.82 1/1'"),
    "music_neon": ("Music", "Neon", "eq=saturation=1.6:contrast=1.2,colorbalance=rs=0.05:bs=0.1:gh=-0.05:rh=0.05:bh=0.08"),
    "music_vhs": ("Music", "VHS", "eq=saturation=1.25:contrast=0.95,noise=alls=9:allf=t,colorbalance=rm=0.03:bm=-0.02,rgbashift=rh=-2:bh=2"),
    "music_sunset": ("Music", "Zarhal quyosh", "colorbalance=rs=0.05:bs=0.08:rm=0.1:bm=-0.05:rh=0.12:gh=0.04:bh=-0.06,eq=saturation=1.3:contrast=1.1"),
    "music_purple": ("Music", "Binafsha", "colorbalance=rs=0.08:bs=0.15:rm=0.04:bm=0.1:rh=0.05:bh=0.06,eq=saturation=1.2:contrast=1.15"),
    "music_contrast": ("Music", "Kuchli kontrast", "eq=contrast=1.35:saturation=1.2:brightness=-0.04,unsharp=5:5:0.6"),
    "music_vintage": ("Music", "Vintage", "curves=all='0/0.08 0.5/0.5 1/0.9',colorbalance=rm=0.05:bm=-0.05:gh=0.02,eq=saturation=0.8,noise=alls=6:allf=t"),
}


# ------------------------------------------------------------------ effekt quruvchilar
def _grade(p: dict, c: Ctx) -> str:
    parts = [f"eq=contrast={_n(p['contrast'])}:brightness={_n(p['exposure'] * 0.2)}"
             f":saturation={_n(p['saturation'])}:gamma={_n(p['gamma'])}"]
    w, t, s = p["warmth"], p["tint"], p["split_tone"]
    cb = []
    if w:
        cb += [f"rm={_n(0.12 * w)}", f"bm={_n(-0.12 * w)}", f"rh={_n(0.06 * w)}", f"bh={_n(-0.06 * w)}"]
    if t:
        cb += [f"gm={_n(-0.1 * t)}"]
    if s:
        cb += [f"rs={_n(-0.1 * s)}", f"gs={_n(0.03 * s)}", f"bs={_n(0.12 * s)}",
               f"rh={_n(0.12 * s)}", f"gh={_n(0.03 * s)}", f"bh={_n(-0.1 * s)}"]
    if cb:
        # takroriy kalitlar (rh, bh) ni birlashtiramiz
        d: dict[str, float] = {}
        for item in cb:
            k, v = item.split("=")
            d[k] = d.get(k, 0.0) + float(v)
        parts.append("colorbalance=" + ":".join(f"{k}={_n(max(-1, min(1, v)))}" for k, v in d.items()))
    return ",".join(parts)


def _curves(p: dict, c: Ctx) -> str:
    s, lift, roll = p["s_curve"], p["black_lift"], p["highlight_roll"]
    y0 = lift
    y1 = 0.25 - 0.09 * s + lift * 0.75
    y2 = 0.75 + 0.09 * s - roll * 0.25
    y3 = 1.0 - roll
    pts = f"0/{_n(y0)} 0.25/{_n(y1)} 0.75/{_n(y2)} 1/{_n(y3)}"
    return f"curves=all='{pts}'"


def _look(p: dict, c: Ctx) -> str:
    if p["intensity"] <= 0:
        return ""
    return _blend_mix(LOOKS[p["look"]][2], p["intensity"])


def _lut(p: dict, c: Ctx) -> str:
    if not p["file"] or p["intensity"] <= 0:
        return ""
    return _blend_mix(f"lut3d=file='{fpath(p['file'])}':interp=tetrahedral", p["intensity"])


def _vignette(p: dict, c: Ctx) -> str:
    if p["strength"] <= 0:
        return ""
    return f"vignette=angle={_n(0.15 + p['strength'] * 0.9)}:mode=backward:eval=init"


def _grain(p: dict, c: Ctx) -> str:
    if p["amount"] <= 0:
        return ""
    return f"noise=alls={_n(p['amount'], 1)}:allf=t"


def _screen_glow(src_chain: str, strength: float) -> str:
    return ("[IN]split[a{u}][b{u}];[b{u}]" + src_chain + ",format=yuv420p[g{u}];"
            "[a{u}][g{u}]blend=all_mode=screen:all_opacity=" + _n(strength) + "[OUT]")


def _glow(p: dict, c: Ctx) -> str:
    if p["strength"] <= 0:
        return ""
    th = int(p["threshold"] * 255)
    sig = max(1.0, p["radius"] * c.scale)
    chain = (f"lutrgb=r='if(gt(val,{th}),val,0)':g='if(gt(val,{th}),val,0)':b='if(gt(val,{th}),val,0)',"
             f"gblur=sigma={_n(sig, 1)}")
    return _screen_glow(chain, p["strength"])


def _halation(p: dict, c: Ctx) -> str:
    if p["strength"] <= 0:
        return ""
    th = int(p["threshold"] * 255)
    sig = max(1.0, p["radius"] * c.scale)
    chain = (f"lutrgb=r='if(gt(val,{th}),val,0)':g='if(gt(val,{th}),val*0.35,0)':b='if(gt(val,{th}),val*0.08,0)',"
             f"gblur=sigma={_n(sig, 1)}")
    return _screen_glow(chain, p["strength"])


def _sharpen(p: dict, c: Ctx) -> str:
    if p["amount"] <= 0:
        return ""
    return f"unsharp=luma_msize_x=5:luma_msize_y=5:luma_amount={_n(p['amount'])}:chroma_amount=0"


def _denoise(p: dict, c: Ctx) -> str:
    s = p["strength"]
    if s <= 0:
        return ""
    return (f"hqdn3d=luma_spatial={_n(s)}:chroma_spatial={_n(s * 0.75)}"
            f":luma_tmp={_n(s * 1.5)}:chroma_tmp={_n(s * 1.2)}")


def _blur(p: dict, c: Ctx) -> str:
    s = p["sigma"] * c.scale
    return f"gblur=sigma={_n(s, 2)}" if s > 0 else ""


def _chromatic(p: dict, c: Ctx) -> str:
    s = int(round(p["shift"] * c.scale))
    return f"rgbashift=rh={-s}:bh={s},format=yuv420p" if s else ""


def _shake(p: dict, c: Ctx) -> str:
    zoom = 1.12
    W, H = c.w, c.h
    bw, bh = int(W * zoom) // 2 * 2, int(H * zoom) // 2 * 2
    a = p["amount"] * c.scale
    f = p["speed"]
    t = f"(t+{_n(c.t0, 4)})"
    return (f"scale={bw}:{bh},crop={W}:{H}:x='({bw}-{W})/2+{_n(a, 2)}*sin(2*PI*{_n(f, 2)}*{t})'"
            f":y='({bh}-{H})/2+{_n(a, 2)}*cos(2*PI*{_n(f * 0.83, 3)}*{t})'")


def _zoom(p: dict, c: Ctx) -> str:
    z0, z1 = p["from"], p["to"]
    if abs(z1 - z0) < 1e-6 and abs(z0 - 1) < 1e-6:
        return ""
    W, H = c.w, c.h
    D = max(c.dur_s, 1e-3)
    prog = f"clip((t+{_n(c.t0, 4)})/{_n(D, 4)},0,1)"
    if p["ease"]:
        prog = f"(3*pow({prog},2)-2*pow({prog},3))"
    zexp = f"({_n(z0)}+({_n(z1)}-{_n(z0)})*{prog})"
    # eval=frame: har kadrda masshtab; yuqori sifat uchun lanczos
    return (f"scale=w='trunc({W}*{zexp}/2)*2':h='trunc({H}*{zexp}/2)*2':eval=frame:flags=lanczos,"
            f"crop={W}:{H}")


def _letterbox(p: dict, c: Ctx) -> str:
    r = p["ratio"]
    return (f"drawbox=x=0:y=0:w=iw:h='max(0,(ih-iw/{_n(r)})/2)':color=black:t=fill,"
            f"drawbox=x=0:y='ih-max(0,(ih-iw/{_n(r)})/2)':w=iw:h='max(0,(ih-iw/{_n(r)})/2)':color=black:t=fill")


def _camera(p: dict, c: Ctx) -> str:
    from .colorspace import cube_for
    return f"lut3d=file='{fpath(cube_for(p['gamut'], p['exposure'], p['contrast']))}':interp=tetrahedral"


def _retouch(p: dict, c: Ctx) -> str:
    return ""        # eksport oldidan bake bosqichida bajariladi (fx/retouch.py)


def _p(key, label, lo, hi, default, step=0.01, **kw) -> P:
    return P(key, label, lo, hi, default, step, **kw)


_EFFECTS = [
    EffectDef("grade", "Rang sozlash", "Rang", [
        _p("exposure", "Ekspozitsiya", -1, 1, 0), _p("contrast", "Kontrast", 0.5, 2, 1),
        _p("saturation", "To'yinganlik", 0, 3, 1), _p("gamma", "Gamma", 0.5, 2, 1),
        _p("warmth", "Iliqlik", -1, 1, 0), _p("tint", "Tint", -1, 1, 0),
        _p("split_tone", "Teal-orange", 0, 1, 0)], _grade),
    EffectDef("curves", "Egri chiziq", "Rang", [
        _p("s_curve", "S-egri", 0, 1, 0.3), _p("black_lift", "Qora ko'tarish", 0, 0.15, 0, 0.005),
        _p("highlight_roll", "Yorug' yumshatish", 0, 0.2, 0, 0.005)], _curves),
    EffectDef("look", "Look (24 original)", "Rang", [
        _p("look", "Look", 0, 0, 0, choices=tuple(LOOKS), type="str"),
        _p("intensity", "Kuch", 0, 1, 0.8)], _look),
    EffectDef("camera", "Kamera profili: S-Log3 -> Rec.709", "Rang", [
        _p("gamut", "Gamut", 0, 0, 0, choices=("sgamut3cine", "sgamut3"), type="str"),
        _p("exposure", "Ekspozitsiya (EV)", -3, 3, 0, 0.05), _p("contrast", "Kontrast", 0.8, 1.4, 1)], _camera,
        doc="Sony A7 III S-Log3 materiali uchun boshlang'ich neytral transform. Profil qo'lda tanlanadi."),
    EffectDef("lut", "LUT (.cube)", "Rang", [
        _p("file", "Fayl", 0, 0, 0, type="str"), _p("intensity", "Kuch", 0, 1, 1)], _lut),
    EffectDef("glow", "Glow", "Kino", [
        _p("strength", "Kuch", 0, 1, 0.4), _p("radius", "Radius", 2, 80, 18, 1),
        _p("threshold", "Chegara", 0.2, 0.95, 0.6)], _glow),
    EffectDef("halation", "Halation (film)", "Kino", [
        _p("strength", "Kuch", 0, 1, 0.5), _p("radius", "Radius", 5, 100, 30, 1),
        _p("threshold", "Chegara", 0.4, 0.98, 0.8)], _halation),
    EffectDef("grain", "Film grain", "Kino", [_p("amount", "Miqdor", 0, 40, 8, 0.5)], _grain),
    EffectDef("vignette", "Vinyetka", "Kino", [_p("strength", "Kuch", 0, 1, 0.5)], _vignette),
    EffectDef("letterbox", "Kino chiziqlari", "Kino", [_p("ratio", "Nisbat", 1.78, 2.76, 2.39)], _letterbox),
    EffectDef("sharpen", "O'tkirlik", "Sifat", [_p("amount", "Kuch", 0, 2, 0.8)], _sharpen),
    EffectDef("denoise", "Shovqin kamaytirish", "Sifat", [_p("strength", "Kuch", 0, 10, 3, 0.1)], _denoise),
    EffectDef("blur", "Xiralashtirish", "Sifat", [_p("sigma", "Sigma", 0, 60, 6, 0.5)], _blur),
    EffectDef("chromatic", "Xromatik siljish", "Harakat", [_p("shift", "Piksel", 0, 20, 3, 1)], _chromatic),
    EffectDef("shake", "Kamera titrashi", "Harakat", [
        _p("amount", "Amplituda", 0, 80, 12, 1), _p("speed", "Chastota (Hz)", 0.5, 20, 6, 0.1)], _shake),
    EffectDef("zoom", "Zoom / Ken Burns", "Harakat", [
        _p("from", "Boshlang'ich", 1, 4, 1), _p("to", "Oxirgi", 1, 4, 1.2),
        _p("ease", "Yumshoq", 0, 1, 1, 1, type="bool")], _zoom),
    EffectDef("retouch", "Retush (yuz/teri)", "Retush", [
        _p("amount", "Kuch", 0, 1, 0.6), _p("texture", "Tekstura saqlash", 0.5, 1.2, 0.9),
        _p("spots", "Dog' tozalash", 0, 1, 0.5), _p("tone", "Teri ohangi", 0, 1, 0.4),
        _p("face_only", "Faqat yuz", 0, 1, 1, 1, type="bool")], _retouch, bake=True,
        doc="Klassik (generativ emas) teri retushi: chastota ajratish + dog' yumshatish. Asl yuz shakli o'zgarmaydi."),
]

EFFECTS: dict[str, EffectDef] = {e.id: e for e in _EFFECTS}


def normalize_params(fx: str, params: dict) -> dict:
    """Parametrlarni to'ldiradi va chegaraga keltiradi; noma'lum kalitlarni tashlaydi."""
    d = EFFECTS[fx]
    out = {}
    for sp in d.params:
        v = params.get(sp.key, sp.choices[0] if sp.choices else sp.default)
        if sp.type == "str":
            if sp.choices:
                v = v if v in sp.choices else sp.choices[0]
            else:
                v = str(v or "")
        elif sp.type == "bool":
            v = 1 if v else 0
        else:
            v = min(max(float(v), sp.lo), sp.hi)
        out[sp.key] = v
    return out


# ------------------------------------------------------------------ perexodlar
# id -> (guruh, nomi). id FFmpeg xfade nomi bilan bir xil.
TRANSITIONS: dict[str, tuple[str, str]] = {
    "fade": ("Klassik", "Silliq o'tish"), "fadeblack": ("Klassik", "Qora orqali"),
    "fadewhite": ("Klassik", "Oq flesh"), "fadegrays": ("Klassik", "Kulrang orqali"),
    "dissolve": ("Klassik", "Eritish"), "fadefast": ("Klassik", "Tez so'nish"),
    "fadeslow": ("Klassik", "Sekin so'nish"),
    "slideleft": ("Surish", "Chapga surish"), "slideright": ("Surish", "O'ngga surish"),
    "slideup": ("Surish", "Tepaga surish"), "slidedown": ("Surish", "Pastga surish"),
    "smoothleft": ("Surish", "Yumshoq chap"), "smoothright": ("Surish", "Yumshoq o'ng"),
    "smoothup": ("Surish", "Yumshoq tepa"), "smoothdown": ("Surish", "Yumshoq past"),
    "coverleft": ("Surish", "Yopish chap"), "coverright": ("Surish", "Yopish o'ng"),
    "coverup": ("Surish", "Yopish tepa"), "coverdown": ("Surish", "Yopish past"),
    "revealleft": ("Surish", "Ochish chap"), "revealright": ("Surish", "Ochish o'ng"),
    "revealup": ("Surish", "Ochish tepa"), "revealdown": ("Surish", "Ochish past"),
    "wipeleft": ("Parda", "Parda chap"), "wiperight": ("Parda", "Parda o'ng"),
    "wipeup": ("Parda", "Parda tepa"), "wipedown": ("Parda", "Parda past"),
    "wipetl": ("Parda", "Burchakdan TL"), "wipetr": ("Parda", "Burchakdan TR"),
    "wipebl": ("Parda", "Burchakdan BL"), "wipebr": ("Parda", "Burchakdan BR"),
    "circleopen": ("Shakl", "Doira ochilishi"), "circleclose": ("Shakl", "Doira yopilishi"),
    "circlecrop": ("Shakl", "Doira kesish"), "rectcrop": ("Shakl", "To'rtburchak"),
    "vertopen": ("Shakl", "Vertikal ochilish"), "vertclose": ("Shakl", "Vertikal yopilish"),
    "horzopen": ("Shakl", "Gorizontal ochilish"), "horzclose": ("Shakl", "Gorizontal yopilish"),
    "diagtl": ("Shakl", "Diagonal TL"), "diagtr": ("Shakl", "Diagonal TR"),
    "diagbl": ("Shakl", "Diagonal BL"), "diagbr": ("Shakl", "Diagonal BR"),
    "radial": ("Dinamik", "Radial"), "distance": ("Dinamik", "Masofa"),
    "pixelize": ("Dinamik", "Piksellar"), "zoomin": ("Dinamik", "Zoom"),
    "hblur": ("Dinamik", "Gorizontal xiralik"), "squeezeh": ("Dinamik", "Siqish gor."),
    "squeezev": ("Dinamik", "Siqish vert."), "hlslice": ("Dinamik", "Bo'laklar chap"),
    "hrslice": ("Dinamik", "Bo'laklar o'ng"), "vuslice": ("Dinamik", "Bo'laklar tepa"),
    "vdslice": ("Dinamik", "Bo'laklar past"), "hlwind": ("Dinamik", "Shamol chap"),
    "hrwind": ("Dinamik", "Shamol o'ng"), "vuwind": ("Dinamik", "Shamol tepa"),
    "vdwind": ("Dinamik", "Shamol past"),
}
