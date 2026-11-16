"""KADRGO yadro testlari. Haqiqiy FFmpeg render, piksel tekshiruvi, fuzz, undo, saqlash.

Ishga tushirish:  python tests/test_engine.py            (hammasi)
                  python tests/test_engine.py quick      (tezkor qism)
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kadrgo.core import edit, storage
from kadrgo.core.edit import EditError
from kadrgo.core.history import History, state_hash
from kadrgo.core.model import Project, Settings
from kadrgo.fx.catalog import EFFECTS, LOOKS, TRANSITIONS
from kadrgo.media.probe import FFMPEG, probe
from kadrgo.render import exporter
from kadrgo.render.graph import plan_chunks

TMP = Path(tempfile.mkdtemp(prefix="kadrgo_test_"))
RESULTS: list[tuple[str, bool, str]] = []


def media(name: str, color: str, dur: int = 6, freq: int = 440, size="640x360", fps=25) -> str:
    p = TMP / f"{name}.mp4"
    if not p.exists():
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s={size}:r={fps}:d={dur}",
                        "-f", "lavfi", "-i", f"sine=f={freq}:d={dur}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", str(p)], check=True)
    return str(p)


def pixel(path: str, t: float, region=None) -> list[int]:
    r = subprocess.run([FFMPEG, "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1", "-f", "rawvideo",
                        "-pix_fmt", "rgb24", "-"], capture_output=True)
    n = len(r.stdout) // 3
    a = np.frombuffer(r.stdout, np.uint8).reshape(-1, 3)
    return a.mean(axis=0).round().astype(int).tolist()


def new_project(w=640, h=360, fps="25/1") -> Project:
    p = Project("test", Settings(w, h, fps))
    return p


def add_asset(p: Project, key: str, path: str):
    a = probe(path)
    a.id = key
    p.assets[key] = a
    return a


def test(fn):
    def run():
        t0 = time.time()
        try:
            fn()
            RESULTS.append((fn.__name__, True, f"{time.time() - t0:.1f}s"))
        except Exception as e:
            RESULTS.append((fn.__name__, False, "".join(traceback.format_exception_only(type(e), e)).strip()
                            + "\n" + traceback.format_exc()[-900:]))
    run.__name__ = fn.__name__
    return run


def near(a, b, tol=14):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# ------------------------------------------------------------------ testlar
@test
def test_transition_pixels():
    p = new_project()
    add_asset(p, "red", media("red", "0xff0000"))
    add_asset(p, "blue", media("blue", "0x0000ff", freq=880))
    c1 = edit.add_clip(p, "V1", "red", 0, 0, 75)
    c2 = edit.add_clip(p, "V1", "blue", 75, 0, 75)
    edit.set_transition(p, c2.id, "fade", 25)
    assert p.duration() == 125, p.duration()
    r = exporter.export(p, str(TMP / "tr.mp4"), "draft")
    assert not r.problems, r.problems
    red, mid, blue = pixel(r.path, 1.0), pixel(r.path, 2.5), pixel(r.path, 4.0)
    assert red[0] > 200 and red[2] < 40, red
    assert blue[2] > 200 and blue[0] < 40, blue
    assert 70 < mid[0] < 190 and 70 < mid[2] < 190, mid          # aralash


@test
def test_squeeze_preserves_geometry():
    p = new_project(320, 180)
    src = TMP / "split-colors.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=red:s=320x180:r=25:d=3,drawbox=x=iw/2:y=0:w=iw/2:h=ih:color=green:t=fill",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True)
    add_asset(p, "split", str(src))
    add_asset(p, "blue", media("blue", "0x0000ff", freq=880))
    edit.add_clip(p, "V1", "split", 0, 0, 40)
    c2 = edit.add_clip(p, "V1", "blue", 40, 0, 40)
    edit.set_transition(p, c2.id, "squeezev", 12)
    output = exporter.export(p, str(TMP / "squeeze.mp4"), "draft", prefer_hw=False)
    raw = subprocess.check_output([FFMPEG, "-v", "error", "-ss", "1.36", "-i", output.path,
                                   "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    width, height = probe(output.path).width, probe(output.path).height
    row = np.frombuffer(raw, np.uint8).reshape(height, width, 3)[height // 2]
    left, red, green, right = [row[round(width*x)].tolist() for x in (.1, .4, .6, .9)]
    assert left[2] > 180 and right[2] > 180, (left, right)
    assert red[0] > 180 and red[1] < 50, red
    assert green[1] > 80 and green[0] < 50, green


@test
def test_all_transitions_render():
    p = new_project(320, 180)
    add_asset(p, "red", media("red", "0xff0000"))
    add_asset(p, "blue", media("blue", "0x0000ff", freq=880))
    bad = []
    for kind in TRANSITIONS:
        q = p.clone()
        c1 = edit.add_clip(q, "V1", "red", 0, 0, 40)
        c2 = edit.add_clip(q, "V1", "blue", 40, 0, 40)
        edit.set_transition(q, c2.id, kind, 12)
        try:
            exporter.export(q, str(TMP / "tt.mp4"), "draft")
        except Exception as e:
            bad.append(f"{kind}: {str(e)[-120:]}")
    assert not bad, bad


@test
def test_all_effects_render_defaults():
    p = new_project(320, 180)
    add_asset(p, "red", media("red", "0x806040"))
    bad = []
    for fx, d in EFFECTS.items():
        if d.bake:
            continue
        q = p.clone()
        c = edit.add_clip(q, "V1", "red", 0, 0, 25)
        edit.add_effect(q, c.id, fx, {})
        try:
            exporter.export(q, str(TMP / "fx.mp4"), "draft")
        except Exception as e:
            bad.append(f"{fx}: {str(e)[-160:]}")
    assert not bad, bad


@test
def test_all_looks_render():
    p = new_project(320, 180)
    add_asset(p, "m", media("m", "0x806040"))
    bad = []
    for look in LOOKS:
        q = p.clone()
        c = edit.add_clip(q, "V1", "m", 0, 0, 10)
        edit.add_effect(q, c.id, "look", {"look": look, "intensity": 0.7})
        try:
            exporter.export(q, str(TMP / "lk.mp4"), "draft")
        except Exception as e:
            bad.append(f"{look}: {str(e)[-160:]}")
    assert not bad, bad


@test
def test_preview_equals_export_frame():
    p = new_project()
    add_asset(p, "red", media("red", "0xff0000"))
    add_asset(p, "blue", media("blue", "0x0000ff", freq=880))
    add_asset(p, "green", media("green", "0x00ff00", freq=660))
    c1 = edit.add_clip(p, "V1", "red", 0, 0, 75)
    c2 = edit.add_clip(p, "V1", "blue", 75, 0, 75)
    c3 = edit.add_clip(p, "V1", "green", 150, 0, 75)
    edit.set_transition(p, c2.id, "fade", 25)
    edit.add_effect(p, c3.id, "grade", {"saturation": 0.5})
    r = exporter.export(p, str(TMP / "pe.mp4"), "draft")
    for f in (10, 55, 62, 70, 120, 130, 170, 195):
        png = exporter.render_frame(p, f, 1.0)
        tp = TMP / "fr.png"
        tp.write_bytes(png)
        a = pixel(str(tp), 0)
        b = pixel(r.path, f / 25.0 + 0.001)
        assert near(a, b, 22), (f, a, b)


@test
def test_chunked_export_matches_single():
    p = new_project(320, 180)
    add_asset(p, "red", media("red", "0xff0000"))
    add_asset(p, "blue", media("blue", "0x0000ff", freq=880))
    c1 = edit.add_clip(p, "V1", "red", 0, 0, 100)
    c2 = edit.add_clip(p, "V1", "blue", 100, 0, 100)
    edit.set_transition(p, c2.id, "slideleft", 20)      # 80..100 perexod
    add_asset(p, "green", media("green", "0x00ff00", freq=660))
    edit.add_clip(p, "V1", "green", 180, 0, 100)
    spans = plan_chunks(p, 90)
    for s, e in spans:                                
        assert not (80 < s < 100) and not (80 < e < 100), spans
    r1 = exporter.export(p, str(TMP / "c1.mp4"), "draft", chunk_seconds=1000)
    r2 = exporter.export(p, str(TMP / "c2.mp4"), "draft", chunk_seconds=1)
    assert r2.chunks > r1.chunks
    assert not r2.problems, r2.problems
    for t in (0.5, 3.4, 3.7, 4.5, 6.0, 8.0, 10.0):
        assert near(pixel(r1.path, t), pixel(r2.path, t), 14), t


@test
def test_audio_sync_and_length():
    p = new_project()
    add_asset(p, "red", media("red", "0xff0000", dur=4))
    c1 = edit.add_clip(p, "V1", "red", 25, 0, 50)        # 1s dan keyin boshlanadi
    r = exporter.export(p, str(TMP / "au.mp4"), "draft")
    assert not r.problems, r.problems
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", r.path, "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         capture_output=True).stdout
    x = np.frombuffer(raw, np.int16).astype(np.float32)
    first = np.argmax(np.abs(x) > 500)
    assert abs(first / 8000 - 1.0) < 0.06, first / 8000        # ovoz 1.0s da boshlanadi (+-60ms, AAC primer)
    assert abs(len(x) / 8000 - 3.0) < 0.06, len(x) / 8000


@test
def test_undo_redo_and_fuzz_invariants():
    rnd = random.Random(int(os.environ.get("KADRGO_FUZZ_SEED", "7")))
    p = new_project()
    add_asset(p, "a", media("a", "0x808080", dur=10))
    h = History(p)
    hashes = [state_hash(p)]
    ops = 0
    for _ in range(400):
        clips = [c for _, c in p.all_clips() if c.id]
        k = rnd.choice(["add", "add", "split", "trim_s", "trim_e", "move", "rdel", "del", "tr", "rmtr", "speed", "fx"])
        before = state_hash(p)
        try:
            if k == "add" or not clips:
                h.run("add", edit.add_clip, "V1", "a", rnd.randint(0, 600), rnd.randint(0, 100), rnd.randint(5, 120))
            else:
                c = rnd.choice(clips)
                if k == "split":
                    h.run("split", edit.split_clip, c.id, rnd.randint(c.start + 1, max(c.start + 1, c.end - 1)))
                elif k == "trim_s":
                    h.run("ts", edit.trim_start, c.id, rnd.randint(max(c.start - 10, 0), c.end))
                elif k == "trim_e":
                    h.run("te", edit.trim_end, c.id, rnd.randint(c.start, c.end + 20))
                elif k == "move":
                    h.run("mv", edit.move_clip, c.id, rnd.randint(0, 700))
                elif k == "rdel":
                    h.run("rd", edit.ripple_delete, c.id)
                elif k == "del":
                    h.run("del", edit.delete_clip, c.id)
                elif k == "tr":
                    h.run("tr", edit.set_transition, c.id, rnd.choice(list(TRANSITIONS)), rnd.randint(2, 30))
                elif k == "rmtr":
                    h.run("rt", edit.remove_transition, c.id)
                elif k == "speed":
                    h.run("sp", edit.set_speed, c.id, rnd.choice([0.5, 1.0, 2.0, 1.5]))
                elif k == "fx":
                    h.run("fx", edit.add_effect, c.id, rnd.choice(list(EFFECTS)), {})
            ops += 1
            hashes.append(state_hash(p))
        except EditError:
            assert state_hash(p) == before, "xato bo'lgan amal holatni o'zgartirdi: " + k
        errs = edit.validate(p)
        assert not errs, (k, errs[:3])
    assert ops > 100, ops
    # to'liq undo -> boshlang'ich; to'liq redo -> oxirgi
    final = state_hash(p)
    while h.can_undo():
        h.undo()
    assert state_hash(p) == hashes[0]
    while h.can_redo():
        h.redo()
    assert state_hash(p) == final
    assert not edit.validate(p)


@test
def test_locks_protect_clips():
    p = new_project()
    add_asset(p, "a", media("a", "0x808080", dur=10))
    c = edit.add_clip(p, "V1", "a", 0, 0, 50)
    edit.set_props(p, c.id, locked=True)
    for fn, args in ((edit.split_clip, (c.id, 10)), (edit.trim_end, (c.id, 30)), (edit.delete_clip, (c.id,)),
                     (edit.move_clip, (c.id, 100)), (edit.add_effect, (c.id, "grain"))):
        try:
            fn(p, *args)
            raise AssertionError(f"{fn.__name__} qulflangan klipga tegdi")
        except EditError:
            pass
    edit.set_props(p, c.id, locked=False)
    edit.split_clip(p, c.id, 10)


@test
def test_save_load_autosave_recovery():
    p = new_project()
    add_asset(p, "a", media("a", "0x808080", dur=10))
    c = edit.add_clip(p, "V1", "a", 0, 0, 50)
    edit.add_effect(p, c.id, "look", {"look": "wed_gold"})
    edit.add_cue(p, 5, 30, "Salom, Buxoro! O‘zbekcha G‘ijduvon")
    f = TMP / "proj.kadrgo"
    storage.save(p, f)
    q = storage.load(f)
    assert state_hash(q) == state_hash(p)
    edit.add_clip(p, "V1", "a", 100, 0, 20)
    storage.autosave(p, f)
    assert storage.has_recovery(f)
    auto_path = Path(str(f) + ".autosave")
    os.utime(auto_path, ns=(f.stat().st_atime_ns, f.stat().st_mtime_ns))
    assert storage.has_recovery(f), "Same-timestamp unsaved work must be recoverable"
    r = storage.load_recovery(f)
    assert state_hash(r) == state_hash(p)
    # buzilgan fayl -> oxirgi versiyadan tiklanadi
    storage.save(p, f)
    f.write_text("{buzilgan")
    z = storage.load(f)
    assert len(z.tracks) == 5
    assert Path(str(f) + ".versions").exists()
    storage.save(p, f)
    assert len(list(Path(str(f) + ".versions").glob("*.kadrgo"))) >= 2


@test
def test_subtitles_burn_in_unicode():
    from kadrgo.ai.subtitles import cues_to_srt, srt_to_cues
    p = new_project(640, 360)
    add_asset(p, "a", media("a", "0x202020", dur=4))
    edit.add_clip(p, "V1", "a", 0, 0, 100)
    edit.add_cue(p, 10, 80, "Bo‘lajak G‘ijduvon — Ayzora")
    srt = cues_to_srt(p)
    assert "G‘ijduvon" in srt
    cues = srt_to_cues(p, srt)
    assert cues[0].text == "Bo‘lajak G‘ijduvon — Ayzora" and cues[0].start == 10 and cues[0].end == 80
    r = exporter.export(p, str(TMP / "sub.mp4"), "draft")
    assert not r.problems, r.problems
    with_sub = pixel(r.path, 1.5)
    p.cues.clear()
    r2 = exporter.export(p, str(TMP / "nosub.mp4"), "draft")
    no_sub = pixel(r2.path, 1.5)
    assert with_sub != no_sub                                   # subtitr haqiqatan chizildi


@test
def test_speed_fit_opacity_scale_fades():
    p = new_project(640, 360)
    add_asset(p, "red", media("red", "0xff0000"))
    add_asset(p, "blue", media("blue", "0x0000ff", freq=880, size="1080x1920"))
    base = edit.add_clip(p, "V1", "red", 0, 0, 100)
    top = edit.add_clip(p, "V2", "blue", 25, 0, 50, fit="fit", opacity=0.5, scale=0.5)
    edit.set_props(p, top.id, fade_in=10, fade_out=10)
    edit.set_speed(p, base.id, 2.0)                               # 100 -> 50 kadr
    assert base.duration == 50
    r = exporter.export(p, str(TMP / "mix.mp4"), "draft")
    assert not r.problems, r.problems
    mid = pixel(r.path, 1.5)                                      # blue (yarim shaffof) qizil ustida
    assert mid[0] > 60 and mid[2] > 20, mid


@test
def test_ducking_lowers_music():
    p = new_project()
    d = media("dlg", "0x101010", dur=4, freq=300)
    m = media("mus", "0x101010", dur=4, freq=1500)
    add_asset(p, "d", d)
    add_asset(p, "m", m)
    edit.add_clip(p, "V1", "d", 25, 0, 50)                         # dialog 1s..3s
    mu = edit.add_clip(p, "A2", "m", 0, 0, 100)                    # musiqa butun vaqt
    p.settings.ducking = False
    r0 = exporter.export(p, str(TMP / "d0.mp4"), "draft")
    p.settings.ducking = True
    r1 = exporter.export(p, str(TMP / "d1.mp4"), "draft")

    def band(path, t0, t1, f0=1500):
        raw = subprocess.run([FFMPEG, "-v", "error", "-ss", str(t0), "-t", str(t1 - t0), "-i", path, "-vn", "-ac", "1",
                              "-ar", "16000", "-f", "s16le", "-"], capture_output=True).stdout
        x = np.frombuffer(raw, np.int16).astype(np.float32)
        t = np.arange(len(x)) / 16000
        return abs(np.sum(x * np.exp(-2j * np.pi * f0 * t))) / len(x)
    a0, a1 = band(r0.path, 1.5, 2.5), band(r1.path, 1.5, 2.5)
    assert a1 < a0 * 0.75, (a0, a1)                                 # dialog paytida musiqa pasaydi


@test
def test_retouch_reduces_spots_keeps_texture():
    import cv2
    from kadrgo.fx.retouch import RetouchParams, Retoucher
    rng = np.random.default_rng(1)
    h, w = 360, 360
    base = np.zeros((h, w, 3), np.float32)
    base[:] = (120, 150, 205)                                       # BGR teri rangi
    tex = cv2.GaussianBlur(rng.normal(0, 7, (h, w)).astype(np.float32), (0, 0), 1.0)
    img = base + tex[..., None]
    for (cx, cy) in ((120, 130), (230, 200), (160, 260)):           # "husnbuzar": qizil dog'lar
        cv2.circle(img, (cx, cy), 3, (95, 110, 215), -1)
    img = cv2.GaussianBlur(img, (0, 0), 1.2)
    frame = np.clip(img, 0, 255).astype(np.uint8)
    r = Retoucher(RetouchParams(amount=1.0, spots=0.8, face_only=0))
    out = r.process(frame)
    spot_before = np.abs(frame[130, 120].astype(int) - np.array([120, 150, 205])).sum()
    spot_after = np.abs(out[130, 120].astype(int) - np.array([120, 150, 205])).sum()
    assert spot_after < spot_before * 0.8, (spot_before, spot_after)
    st = r.finish()
    assert 0.45 < st.texture_retention <= 1.05, st
    assert not np.array_equal(out, frame)


@test
def test_retouch_bake_in_export():
    p = new_project(320, 180)
    add_asset(p, "a", media("skin", "0xd2a58a", dur=2))
    c = edit.add_clip(p, "V1", "a", 0, 0, 25)
    edit.add_effect(p, c.id, "retouch", {"face_only": 0, "amount": 0.8})
    os.environ["KADRGO_CACHE"] = str(TMP / "cache")
    r = exporter.export(p, str(TMP / "rt.mp4"), "draft")
    assert not r.problems, r.problems


@test
def test_local_db_and_vault():
    from kadrgo.core.db import LocalDB, analysis_key
    db = LocalDB(TMP / "t.db")
    k1 = analysis_key("h", "transcript", "whisper-small", "1", {"lang": "uz"})
    k2 = analysis_key("h", "transcript", "whisper-small", "1", {"lang": "uz"})
    assert k1 == k2
    db.put_analysis(k1, "h", "transcript", {"text": "salom"})
    assert db.get_analysis(k1) == {"text": "salom"}
    assert db.get_analysis("yo'q") is None


@test
def test_probe_edge_cases():
    try:
        probe(str(TMP / "yoq.mp4"))
        raise AssertionError("mavjud bo'lmagan fayl xato bermadi")
    except ValueError:
        pass
    bad = TMP / "bad.mp4"
    bad.write_bytes(b"bu video emas" * 100)
    try:
        probe(str(bad))
        raise AssertionError("buzilgan fayl xato bermadi")
    except ValueError:
        pass
    img = TMP / "im.png"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1",
                    str(img)], check=True)
    a = probe(str(img))
    assert a.kind == "image" and not a.has_audio


@test
def test_cancel_stops_export():
    import threading
    p = new_project(1280, 720)
    add_asset(p, "a", media("big", "0x808080", dur=30, size="1280x720"))
    edit.add_clip(p, "V1", "a", 0, 0, 750)
    edit.add_effect(p, p.track("V1").clips[0].id, "denoise", {"strength": 8})
    tok = exporter.CancelToken()
    threading.Timer(0.6, tok.cancel).start()
    t0 = time.time()
    try:
        exporter.export(p, str(TMP / "cx.mp4"), "master", cancel=tok)
        raise AssertionError("bekor qilinmadi")
    except exporter.Cancelled:
        pass
    assert time.time() - t0 < 20


@test
def test_library_scanner_real_files():
    from kadrgo.core.vault import Vault
    from kadrgo.library import scanner
    v = Vault(str(TMP / "vault"))
    ttf = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
    if os.path.exists(ttf):
        import shutil
        shutil.copy(ttf, v.library / "Fonts" / "d.ttf")
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=60:d=1", "-c:a", "pcm_s24le", "-ar", "96000",
                    str(v.library / "SFX" / "boom.wav")], check=True)
    (v.library / "SFX" / "yomon.wav").write_bytes(b"bu audio emas" * 50)
    (v.library / "LUT" / "yomon.cube").write_text("LUT_3D_SIZE 3\n0 0 0\n")
    r = scanner.scan(v)
    assert r["sfx"] == 2 and r["luts"] == 1, r
    items = {i["name"]: i for i in scanner.list_library(v.db, "sfx")}
    assert items["boom"]["status"] == "ok" and items["boom"]["meta"]["sample_rate"] == 96000
    assert items["yomon"]["status"] == "xato"                    # buzilgan fayl "ok" deb yozilmaydi
    assert scanner.list_library(v.db, "lut")[0]["status"] == "xato"
    if os.path.exists(ttf):
        f = scanner.list_library(v.db, "font")[0]
        assert f["status"] in ("ok", "qisman") and f["meta"]["glyphs"] > 100
    r2 = scanner.scan(v)                                          # ikkinchi marta: o'zgarmaganlar o'tkazib yuboriladi
    assert r2["skipped"] >= 2


@test
def test_slog3_lut_and_effect():
    from kadrgo.fx import colorspace as cs
    import numpy as np
    assert abs(float(cs.slog3_to_linear(420 / 1023)) - 0.18) < 1e-6            # Sony: 18% kulrang = kod 420
    for g in ("sgamut3cine", "sgamut3"):
        assert np.allclose(cs.gamut_matrix(g).sum(axis=1), 1.0, atol=1e-6)    # oq nuqta saqlanadi
    grey = cs.transform(np.array([[0.4106] * 3]))[0]
    assert abs(grey[0] - grey[1]) < 1e-6 and abs(grey[1] - grey[2]) < 1e-6      # kulrang neytral qoladi
    cube = TMP / "s.cube"
    cs.build_cube(cube, size=17)
    assert cs.read_cube(cube)["size"] == 17
    p = new_project(320, 180)
    add_asset(p, "m", media("slog", "0x6a7a8a"))
    c = edit.add_clip(p, "V1", "m", 0, 0, 10)
    edit.add_effect(p, c.id, "camera", {"exposure": 0.3})
    r = exporter.export(p, str(TMP / "cam.mp4"), "draft")
    assert not r.problems, r.problems


@test
def test_ai_plan_validation_and_single_undo():
    from kadrgo.ai import plan as aiplan
    p = new_project()
    add_asset(p, "a", media("a", "0x808080", dur=10))
    h = History(p)
    bad = {"track": "V1", "items": [{"asset": "yo'q", "src_in": 0, "src_out": 1}]}
    try:
        aiplan.apply_plan(h, bad)
        raise AssertionError("yaroqsiz reja qabul qilindi")
    except aiplan.PlanError:
        pass
    over = {"track": "V1", "items": [{"asset": "a", "src_in": 0, "src_out": 99}]}
    try:
        aiplan.apply_plan(h, over)
        raise AssertionError("manbadan oshgan reja qabul qilindi")
    except aiplan.PlanError:
        pass
    assert p.duration() == 0
    good = {"track": "V1", "items": [{"asset": "a", "src_in": 0, "src_out": 2, "reason": "hook"},
                                      {"asset": "a", "src_in": 3, "src_out": 5, "transition": {"kind": "fade", "duration": 0.4}}]}
    aiplan.apply_plan(h, good)
    assert len(p.track("V1").clips) == 2 and not edit.validate(p)
    h.undo()
    assert p.duration() == 0                                      # butun AI reja BITTA qadamda qaytdi


@test
def test_jump_cut_removes_silence():
    from kadrgo.ai import audio_tools
    p = new_project()
    f = TMP / "speech.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=25:d=6", "-f", "lavfi",
                    "-i", "sine=f=300:d=2", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=2", "-f", "lavfi", "-i",
                    "sine=f=300:d=2", "-filter_complex", "[1:a][2:a][3:a]concat=n=3:v=0:a=1[a]", "-map", "0:v", "-map",
                    "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(f)], check=True)
    add_asset(p, "s", str(f))
    h = History(p)
    c = h.run("add", edit.add_clip, "V1", "s", 0, 0, 150)
    n = audio_tools.jump_cut(h, c.id)
    assert n == 2, n
    assert p.duration() < 150 - 30, p.duration()                   # ~2s sukunat olib tashlandi
    assert not edit.validate(p)
    h.undo()
    assert p.duration() == 150 and len(p.track("V1").clips) == 1


@test
def test_beat_detection_on_click_track():
    from kadrgo.ai import audio_tools
    f = TMP / "clicks.wav"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='if(lt(mod(t,0.5),0.03),sin(2*PI*1000*t)*0.9,0)':d=10:s=44100", str(f)], check=True)
    r = audio_tools.detect_beats(str(f))
    assert len(r["beats"]) >= 15, r
    assert 110 <= r["bpm"] <= 130, r                                  # 0.5s oraliq = 120 BPM


ALL = [test_squeeze_preserves_geometry, test_transition_pixels, test_preview_equals_export_frame, test_chunked_export_matches_single,
       test_audio_sync_and_length, test_undo_redo_and_fuzz_invariants, test_locks_protect_clips,
       test_save_load_autosave_recovery, test_subtitles_burn_in_unicode, test_speed_fit_opacity_scale_fades,
       test_ducking_lowers_music, test_retouch_reduces_spots_keeps_texture, test_retouch_bake_in_export,
       test_local_db_and_vault, test_probe_edge_cases, test_cancel_stops_export,
       test_all_effects_render_defaults, test_all_looks_render, test_all_transitions_render,
       test_library_scanner_real_files, test_slog3_lut_and_effect, test_ai_plan_validation_and_single_undo,
       test_jump_cut_removes_silence, test_beat_detection_on_click_track]
QUICK = [test_transition_pixels, test_undo_redo_and_fuzz_invariants, test_locks_protect_clips,
         test_save_load_autosave_recovery, test_local_db_and_vault, test_probe_edge_cases]

if __name__ == "__main__":
    only = sys.argv[1:] 
    suite = QUICK if only == ["quick"] else ([f for f in ALL if f.__name__ in only] if only else ALL)
    for t in suite:
        t()
    ok = sum(1 for _, g, _ in RESULTS if g)
    for name, good, info in RESULTS:
        print(("PASS " if good else "FAIL ") + name + "  " + info)
    print(f"\n{ok}/{len(RESULTS)} test o'tdi")
    sys.exit(0 if ok == len(RESULTS) else 1)
