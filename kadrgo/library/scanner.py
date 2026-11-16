"""Kutubxona skaneri: foydalanuvchi yig'gan fayllarni HAQIQATAN tekshiradi va indekslaydi.

* SFX/musiqa: ffprobe (davomiylik, sample rate, bit chuqurligi, kanallar), litsenziya fayli bor-yo'qligi
* Shriftlar: cmap orqali O', G', ʻ (U+02BB), kirill (Ў Ғ Қ Ҳ) va turkcha harflar qamrovi, litsenziya matni, embedding huquqi
* LUT: .cube sarlavha va qatorlar soni
* Plaginlar: OFX / VST3 / AU topiladi. "Ishlaydi" DEMAYDI: ijro host moduli va sinov talab qiladi

Natija: har yozuvda status (ok / qisman / xato) va sabab izohi. "Tekshirilgan" deb faqat tekshirilganini yozamiz.
"""
from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from ..core.db import LocalDB
from ..core.vault import Vault
from ..media.probe import FFPROBE, run

AUDIO_EXT = {".wav", ".aif", ".aiff", ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".aac"}
FONT_EXT = {".ttf", ".otf", ".ttc", ".otc"}
LUT_EXT = {".cube"}
LICENSE_NAMES = {"license", "license.txt", "licence.txt", "readme.txt", "license.md", "ofl.txt", "eula.txt"}

LATIN = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
UZ_APOS = {"\u02bb": "ʻ (U+02BB)", "\u02bc": "ʼ (U+02BC)", "\u2018": "‘ (U+2018)", "\u2019": "’ (U+2019)", "'": "' (U+0027)"}
CYRILLIC = set("АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдежзийклмнопрстуфхцчшщъыьэюя") | set("ЎўҒғҚқҲҳЁё")
TURKISH = set("çÇğĞıİöÖşŞüÜ")

VENDORS = [("sapphire", "Boris FX"), ("continuum", "Boris FX"), ("mocha", "Boris FX"), ("borisfx", "Boris FX"),
           ("neat", "Neat Video"), ("dehancer", "Dehancer"), ("filmconvert", "FilmConvert"),
           ("twixtor", "RE:Vision Effects"), ("revisionfx", "RE:Vision Effects"), ("magicbullet", "Maxon"),
           ("magic bullet", "Maxon"), ("red giant", "Maxon"), ("maxon", "Maxon"), ("izotope", "iZotope"),
           ("fabfilter", "FabFilter"), ("newblue", "NewBlue"), ("waves", "Waves"), ("soundtoys", "Soundtoys"),
           ("valhalla", "Valhalla DSP"), ("digital anarchy", "Digital Anarchy"), ("beauty box", "Digital Anarchy"),
           ("blackmagic", "Blackmagic"), ("lut utility", "Blackmagic")]


def _vendor(name: str, parent: str = "") -> str:
    low = (name + " " + parent).lower()
    for k, v in VENDORS:
        if k in low:
            return v
    return "Noma'lum"


# ------------------------------------------------------------------ SFX / musiqa
def check_audio(path: Path) -> tuple[dict, str, str]:
    r = run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    if r.returncode != 0:
        return {}, "xato", "Faylni o'qib bo'lmadi"
    info = json.loads(r.stdout or b"{}")
    a = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    if a is None:
        return {}, "xato", "Audio oqimi yo'q"
    dur = float(info.get("format", {}).get("duration") or a.get("duration") or 0)
    bits = int(a.get("bits_per_raw_sample") or a.get("bits_per_sample") or 0)
    meta = {"duration": round(dur, 3), "sample_rate": int(a.get("sample_rate", 0) or 0),
            "channels": int(a.get("channels", 0) or 0), "codec": a.get("codec_name"), "bits": bits}
    note = ""
    status = "ok"
    if dur < 0.02:
        status, note = "xato", "Juda qisqa yoki bo'sh"
    elif meta["sample_rate"] < 44100:
        status, note = "qisman", f"Past sample rate ({meta['sample_rate']} Hz)"
    return meta, status, note


def _tags_from_path(p: Path, root: Path) -> list[str]:
    try:
        rel = p.relative_to(root)
    except ValueError:
        rel = p
    toks = re.split(r"[\\/ _\-.]+", str(rel.with_suffix("")).lower())
    return sorted({t for t in toks if len(t) > 2 and not t.isdigit()})[:12]


# ------------------------------------------------------------------ shriftlar
def check_font(path: Path) -> list[tuple[str, dict, str, str]]:
    """Har shrift (TTC bo'lsa har yuz) uchun (nom, meta, status, izoh)."""
    try:
        from fontTools.ttLib import TTCollection, TTFont
    except ImportError:
        return [(path.stem, {}, "qisman", "fonttools o'rnatilmagan: pip install fonttools")]
    out = []
    try:
        fonts = list(TTCollection(str(path), lazy=True).fonts) if path.suffix.lower() in (".ttc", ".otc") \
            else [TTFont(str(path), lazy=True)]
    except Exception as e:
        return [(path.stem, {}, "xato", f"Shrift fayli buzilgan: {e}")]
    for f in fonts:
        try:
            nm = f["name"]
            fam = (nm.getDebugName(16) or nm.getDebugName(1) or path.stem)
            sty = (nm.getDebugName(17) or nm.getDebugName(2) or "")
            lic = nm.getDebugName(13) or ""
            lic_url = nm.getDebugName(14) or ""
            cmap = f.getBestCmap() or {}
            have = {chr(c) for c in cmap}
            miss_latin = sorted(LATIN - have)
            apos_ok = [UZ_APOS[c] for c in UZ_APOS if c in have]
            has_modifier = "\u02bb" in have
            cyr_uz = sorted((set("ЎўҒғҚқҲҳ") | set("АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")) - have)
            tr_miss = sorted(TURKISH - have)
            fs_type = getattr(f["OS/2"], "fsType", 0) if "OS/2" in f else 0
            is_ofl = ("open font license" in lic.lower()) or ("scripts.sil.org/ofl" in lic_url.lower()) \
                or ("openfontlicense" in lic_url.lower())
            meta = {"family": fam, "style": sty, "license": lic[:200], "license_url": lic_url[:200],
                    "ofl": is_ofl, "embedding": "cheklangan" if fs_type & 0x0002 else "ruxsat",
                    "uz_latin_missing": miss_latin, "uz_apostrophes": apos_ok, "has_u02bb": has_modifier,
                    "uz_cyrillic_missing": cyr_uz, "turkish_missing": tr_miss, "glyphs": len(cmap)}
            status, notes = "ok", []
            if miss_latin or not apos_ok:
                status = "qisman"
                if miss_latin:
                    notes.append("Lotin harflari yetishmaydi: " + "".join(miss_latin[:10]))
                if not apos_ok:
                    notes.append("O'zbekcha apostrof belgilari yo'q")
            elif not has_modifier:
                notes.append("ʻ (U+02BB) yo'q; ‘ ’ yoki ' ishlatiladi")
            if not cyr_uz:
                notes.append("O'zbek kirill to'liq")
            if tr_miss:
                notes.append("Turkcha: yetishmaydi " + "".join(tr_miss))
            if fs_type & 0x0002:
                status = "qisman" if status == "ok" else status
                notes.append("Embedding cheklangan (tarqatishda huquqni tekshiring)")
            if not lic:
                notes.append("Litsenziya matni shriftda yo'q")
            out.append((f"{fam} {sty}".strip(), meta, status, "; ".join(notes)))
        except Exception as e:
            out.append((path.stem, {}, "xato", f"O'qib bo'lmadi: {e}"))
    return out


# ------------------------------------------------------------------ LUT
def check_lut(path: Path) -> tuple[dict, str, str]:
    from ..fx.colorspace import read_cube
    try:
        return read_cube(path), "ok", ""
    except Exception as e:
        return {}, "xato", str(e)


# ------------------------------------------------------------------ plaginlar
def find_plugins(paths: dict[str, list[str]]) -> list[dict]:
    found = []
    for std, dirs in paths.items():
        for d in dirs:
            base = Path(d)
            if not base.exists():
                continue
            for root, dnames, fnames in os.walk(base):
                rp = Path(root)
                if std == "ofx":
                    for n in list(dnames):
                        if n.lower().endswith(".ofx.bundle"):
                            found.append((std, rp / n))
                            dnames.remove(n)
                    for n in fnames:
                        if n.lower().endswith(".ofx"):
                            found.append((std, rp / n))
                elif std == "vst3":
                    for n in list(dnames):
                        if n.lower().endswith(".vst3"):
                            found.append((std, rp / n))
                            dnames.remove(n)
                    for n in fnames:
                        if n.lower().endswith(".vst3"):
                            found.append((std, rp / n))
                elif std == "au":
                    for n in list(dnames):
                        if n.lower().endswith(".component"):
                            found.append((std, rp / n))
                            dnames.remove(n)
    out = []
    for std, p in found:
        name = re.sub(r"\.(ofx\.bundle|ofx|vst3|component)$", "", p.name, flags=re.I)
        out.append({"path": str(p), "name": name, "standard": {"ofx": "OpenFX", "vst3": "VST3", "au": "AudioUnit"}[std],
                    "vendor": _vendor(name, p.parent.name), "platform": os.name})
    return out


# ------------------------------------------------------------------ asosiy skan
def scan(vault: Vault, extra_dirs: Optional[list[str]] = None, progress: Optional[Callable[[str], None]] = None,
         force: bool = False) -> dict:
    """Vault/Library (va extra_dirs) ni skanerlaydi, bazaga yozadi. Hisobot qaytaradi."""
    db: LocalDB = vault.db
    roots = [vault.library] + [Path(d) for d in (extra_dirs or [])]
    now = time.time()
    report = {"sfx": 0, "music": 0, "fonts": 0, "luts": 0, "plugins": 0, "skipped": 0, "problems": [], "removed": 0}
    seen: set[str] = set()
    known = {r[0]: (r[1], r[2]) for r in db.con.execute("SELECT path,size,mtime FROM library")}
    jobs = []
    for root in roots:
        if not root.exists():
            continue
        has_license = {str(p.parent) for p in root.rglob("*") if p.is_file() and p.name.lower() in LICENSE_NAMES}
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            cat = None
            if ext in AUDIO_EXT:
                top = p.relative_to(root).parts[0].lower() if p != root and len(p.relative_to(root).parts) > 1 else ""
                cat = "music" if top == "music" else "sfx"
            elif ext in FONT_EXT:
                cat = "font"
            elif ext in LUT_EXT:
                cat = "lut"
            if cat:
                jobs.append((cat, p, root, str(p.parent) in has_license))
    seen = {str(j[1]) for j in jobs}

    def work(job):
        cat, p, root, lic = job
        st = p.stat()
        if not force and known.get(str(p)) == (st.st_size, st.st_mtime):
            return ("skip", cat, p, None)
        if cat in ("sfx", "music"):
            meta, status, note = check_audio(p)
            meta["tags"] = _tags_from_path(p, root)
            meta["license_file"] = lic
            return ("ok", cat, p, [(p.stem, meta, status, note)])
        if cat == "font":
            return ("ok", cat, p, check_font(p))
        meta, status, note = check_lut(p)
        return ("ok", cat, p, [(p.stem, meta, status, note)])

    with ThreadPoolExecutor(max_workers=4) as ex:
        for kind, cat, p, items in ex.map(work, jobs):
            if kind == "skip":
                report["skipped"] += 1
                continue
            st = p.stat()
            for i, (name, meta, status, note) in enumerate(items):
                key = str(p) if i == 0 else f"{p}#{i}"
                db.con.execute("INSERT OR REPLACE INTO library VALUES(?,?,?,?,?,?,?,?,?)",
                               (key, cat, name, json.dumps(meta, ensure_ascii=False), status, note,
                                st.st_size, st.st_mtime, now))
                report[{"sfx": "sfx", "music": "music", "font": "fonts", "lut": "luts"}[cat]] += 1
                if status != "ok":
                    report["problems"].append(f"[{status}] {p.name}: {note}")
            if progress:
                progress(p.name)
    # o'chirilgan fayllar
    for path in list(known):
        if path not in seen and not os.path.exists(path):
            db.con.execute("DELETE FROM library WHERE path=?", (path,))
            report["removed"] += 1
    # plaginlar
    db.con.execute("DELETE FROM plugins")
    for pl in find_plugins(vault.plugin_search_paths()):
        db.con.execute("INSERT OR REPLACE INTO plugins VALUES(?,?,?,?,?,?,?,?)",
                       (pl["path"], pl["name"], pl["standard"], pl["vendor"], pl["platform"], "topildi",
                        "Moslik tekshirilmagan; ijro uchun plagin host moduli kerak", now))
        report["plugins"] += 1
    db.con.commit()
    return report


def list_library(db: LocalDB, category: Optional[str] = None, query: str = "", only_ok: bool = False) -> list[dict]:
    sql, args = "SELECT path,category,name,meta,status,note FROM library WHERE 1=1", []
    if category:
        sql += " AND category=?"
        args.append(category)
    if only_ok:
        sql += " AND status='ok'"
    if query:
        sql += " AND (LOWER(name) LIKE ? OR LOWER(meta) LIKE ?)"
        args += [f"%{query.lower()}%"] * 2
    sql += " ORDER BY name COLLATE NOCASE"
    return [{"path": r[0].split("#")[0], "category": r[1], "name": r[2], "meta": json.loads(r[3] or "{}"),
             "status": r[4], "note": r[5]} for r in db.con.execute(sql, args)]


def list_plugins(db: LocalDB) -> list[dict]:
    return [dict(zip(("path", "name", "standard", "vendor", "platform", "status", "note"), r))
            for r in db.con.execute("SELECT path,name,standard,vendor,platform,status,note FROM plugins "
                                    "ORDER BY vendor,name")]
