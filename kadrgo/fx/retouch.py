"""Teri retushi (klassik, generativ EMAS): chastota ajratish + dog'larni yumshatish.

Algoritm (har kadrda, faqat yuz atrofi ROI da):
  low  = Gauss(frame, s)            rang/soya qatlami
  high = frame - low                tekstura (poralar, kiprik)
  low' = bilateral(low)             teri rangini tekislash (chekka saqlanadi)
  high'= T*tanh(high/T)             kuchli bir martalik "tikanak"lar (husnbuzar, dog') siqiladi,
                                    mayda tekstura deyarli o'zgarmaydi
  out  = low' + texture*high'
  res  = frame + (out - frame) * mask * amount

Maska = yuz kuzatuvchisi (Haar + EMA silliqlash) x teri rangi (YCrCb). Ko'z, lab, soch maskadan tashqarida.
Asl yuz shakli, ko'z va lablar generativ o'zgartirilmaydi. Metrika: teksturani saqlash foizi
(retushdan keyingi / oldingi yuqori chastota energiyasi) hisobotga yoziladi; juda past bo'lsa ogohlantiriladi.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Callable, Optional

import cv2
import numpy as np

from ..media.probe import CREATE_NO_WINDOW, FFMPEG, probe


@dataclass
class RetouchParams:
    amount: float = 0.6
    texture: float = 0.9
    spots: float = 0.5
    tone: float = 0.4
    face_only: int = 1


@dataclass
class RetouchStats:
    frames: int = 0
    frames_with_face: int = 0
    texture_retention: float = 1.0      # 1.0 = tekstura to'liq saqlangan
    warnings: list = field(default_factory=list)


class FaceTracker:
    """Haar detektori + EMA: yuz qutisi kadrdan kadrga silliq, vaqtincha yo'qolsa ham saqlanadi."""

    def __init__(self, detect_every: int = 3, max_miss: int = 15):
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self.cascade = cv2.CascadeClassifier(path)
        if self.cascade.empty():
            raise RuntimeError("Yuz detektori yuklanmadi (OpenCV haarcascade topilmadi)")
        self.tracks: list[dict] = []
        self.n = 0
        self.every = detect_every
        self.max_miss = max_miss

    def update(self, bgr: np.ndarray) -> list[tuple[float, float, float, float]]:
        self.n += 1
        if (self.n - 1) % self.every == 0:
            h, w = bgr.shape[:2]
            s = 480.0 / max(w, 1)
            small = cv2.resize(bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else bgr
            s = small.shape[1] / w
            gray = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
            faces = self.cascade.detectMultiScale(gray, 1.12, 5, minSize=(max(24, int(40 * s)),) * 2)
            used = set()
            for (x, y, fw, fh) in faces:
                box = np.array([x / s, y / s, fw / s, fh / s], dtype=np.float32)
                cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
                best, bd = None, 1e9
                for i, t in enumerate(self.tracks):
                    if i in used:
                        continue
                    tb = t["box"]
                    d = np.hypot(cx - (tb[0] + tb[2] / 2), cy - (tb[1] + tb[3] / 2))
                    if d < bd and d < 0.8 * max(tb[2], box[2]):
                        best, bd = i, d
                if best is None:
                    self.tracks.append({"box": box, "miss": 0})
                    used.add(len(self.tracks) - 1)
                else:
                    t = self.tracks[best]
                    t["box"] = 0.55 * t["box"] + 0.45 * box
                    t["miss"] = 0
                    used.add(best)
            for i, t in enumerate(self.tracks):
                if i not in used:
                    t["miss"] += self.every
            self.tracks = [t for t in self.tracks if t["miss"] <= self.max_miss]
        return [tuple(t["box"]) for t in self.tracks]


def skin_mask(bgr: np.ndarray) -> np.ndarray:
    ycc = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    m = cv2.inRange(ycc, (30, 133, 77), (250, 173, 127))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
    return cv2.GaussianBlur(m.astype(np.float32) / 255.0, (0, 0), 2.0)


def face_mask(shape, boxes) -> np.ndarray:
    h, w = shape[:2]
    m = np.zeros((h, w), np.float32)
    for (x, y, bw, bh) in boxes:
        c = (int(x + bw / 2), int(y + bh * 0.55))
        ax = (int(bw * 0.62), int(bh * 0.78))
        cv2.ellipse(m, c, ax, 0, 0, 360, 1.0, -1)
    if boxes:
        sig = max(3.0, 0.12 * float(np.mean([b[2] for b in boxes])))
        m = cv2.GaussianBlur(m, (0, 0), sig)
    return m


def _hf_energy(f: np.ndarray, mask: np.ndarray) -> float:
    g = cv2.cvtColor(f.astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)
    hp = g - cv2.GaussianBlur(g, (0, 0), 2.0)
    sel = mask > 0.5
    return float(np.sqrt(np.mean(hp[sel] ** 2))) if sel.any() else 0.0


class Retoucher:
    def __init__(self, params: RetouchParams):
        self.p = params
        self.tracker = FaceTracker() if params.face_only else None
        self.stats = RetouchStats()
        self._tex_before, self._tex_after, self._tex_n = 0.0, 0.0, 0

    def process(self, bgr: np.ndarray) -> np.ndarray:
        p = self.p
        self.stats.frames += 1
        boxes = self.tracker.update(bgr) if self.tracker else []
        if p.face_only:
            if not boxes:
                return bgr
            self.stats.frames_with_face += 1
            mask = face_mask(bgr.shape, boxes) * (0.35 + 0.65 * skin_mask(bgr))
            fw = float(np.mean([b[2] for b in boxes]))
        else:
            mask = skin_mask(bgr)
            fw = bgr.shape[1] * 0.2
            self.stats.frames_with_face += 1
        bin_ = (mask > 0.02).astype(np.uint8)
        x, y, w, h = cv2.boundingRect(bin_)
        if w < 8 or h < 8:
            return bgr
        pad = 8
        x0, y0 = max(x - pad, 0), max(y - pad, 0)
        x1, y1 = min(x + w + pad, bgr.shape[1]), min(y + h + pad, bgr.shape[0])
        roi = bgr[y0:y1, x0:x1]
        m = mask[y0:y1, x0:x1][..., None]
        f = roi.astype(np.float32)
        if p.spots > 0:
            f = self._heal_spots(roi, f, m, fw, p)
        sigma = float(np.clip(fw * 0.015, 1.5, 6.0))
        low = cv2.GaussianBlur(f, (0, 0), sigma)
        high = f - low
        # bilateral: yarim o'lchamda (low allaqachon silliq, sifat yo'qolmaydi)
        sm = cv2.resize(low, (max(low.shape[1] // 2, 2), max(low.shape[0] // 2, 2)), interpolation=cv2.INTER_AREA)
        sm = cv2.bilateralFilter(sm, 0, 12 + 38 * p.tone, sigma * 1.5)
        low_s = cv2.resize(sm, (low.shape[1], low.shape[0]), interpolation=cv2.INTER_LINEAR)
        low_f = low + (low_s - low) * float(np.clip(0.35 + 0.65 * p.tone, 0, 1))
        T = 28.0 - 22.0 * p.spots
        wsp = 0.2 + 0.8 * p.spots
        high_soft = T * np.tanh(high / T)
        high_f = (high * (1 - wsp) + high_soft * wsp) * p.texture
        out = low_f + high_f
        res = f + (out - f) * (m * p.amount)
        res = np.clip(res, 0, 255).astype(np.uint8)
        # tekstura metrikasi (har 10-kadrda)
        if self.stats.frames % 10 == 1:
            mm = m[..., 0]
            self._tex_before += _hf_energy(roi, mm)
            self._tex_after += _hf_energy(res, mm)
            self._tex_n += 1
        outf = bgr.copy()
        outf[y0:y1, x0:x1] = res
        return outf

    @staticmethod
    def _heal_spots(roi: np.ndarray, f: np.ndarray, m: np.ndarray, fw: float, p: RetouchParams) -> np.ndarray:
        """Kichik dog'/husnbuzarlarni mediana bilan tuzatadi: faqat teri maskasi ichida, faqat rangi atrofdan
        sezilarli farq qiladigan KICHIK joylar (mediana oynasidan kichik). Katta tuzilmalar (burun, og'iz) o'zgarmaydi."""
        k = int(np.clip(fw * 0.075, 9, 41)) | 1
        med = cv2.medianBlur(roi, k)
        lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB).astype(np.float32)
        lab_m = cv2.cvtColor(med, cv2.COLOR_BGR2LAB).astype(np.float32)
        d = lab - lab_m
        dist = np.sqrt(d[..., 0] ** 2 + 1.5 * d[..., 1] ** 2 + 0.7 * d[..., 2] ** 2)
        t0 = 4.0 + (1.0 - p.spots) * 12.0
        w = np.clip((dist - t0) / 8.0, 0.0, 1.0)
        w = cv2.GaussianBlur(w, (0, 0), 0.8)[..., None] * min(1.0, 0.3 + 0.7 * p.spots)
        return f + (med.astype(np.float32) - f) * w * np.clip(m * 1.5, 0, 1)

    def finish(self) -> RetouchStats:
        s = self.stats
        if self._tex_before > 1e-6:
            s.texture_retention = self._tex_after / self._tex_before
        if s.texture_retention < 0.55:
            s.warnings.append("Teri ortiqcha silliqlangan ko'rinadi: 'Kuch' yoki 'Dog' tozalash'ni kamaytiring")
        if s.frames and s.frames_with_face / s.frames < 0.3:
            s.warnings.append("Yuz kadrlarning kam qismida topildi (yon tomondan yoki kichik yuz); natija cheklangan")
        return s


def retouch_file(src: str, dst: str, start_s: float, dur_s: float, params: RetouchParams,
                 on_frame: Optional[Callable[[int], None]] = None, cancel=None) -> RetouchStats:
    """src[start_s : start_s+dur_s] ni retush qilib dst ga yozadi (ovoz asl holda ko'chiriladi)."""
    a = probe(src)
    w, h = a.width, a.height
    fps = a.fps if a.fps not in ("0/1", "") else "25/1"
    kw = {"creationflags": CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    dec = subprocess.Popen([FFMPEG, "-v", "error", "-ss", f"{start_s:.6f}", "-t", f"{dur_s:.6f}", "-i", src,
                            "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **kw)
    tmp = dst + ".part.mp4"
    enc = subprocess.Popen([FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                            "-r", fps, "-i", "-", "-ss", f"{start_s:.6f}", "-t", f"{dur_s:.6f}", "-i", src,
                            "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-crf", "12", "-preset", "fast",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", "-shortest", tmp],
                           stdin=subprocess.PIPE, stderr=subprocess.PIPE, **kw)
    r = Retoucher(params)
    size = w * h * 3
    n = 0
    try:
        while True:
            if cancel is not None and cancel.is_set():
                from ..render.exporter import Cancelled
                raise Cancelled()
            buf = dec.stdout.read(size)
            if len(buf) < size:
                break
            frame = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            enc.stdin.write(r.process(frame).tobytes())
            n += 1
            if on_frame and n % 5 == 0:
                on_frame(n)
        enc.stdin.close()
        enc.wait()
        if enc.returncode != 0:
            raise RuntimeError("Retush kodlash xatosi: " + enc.stderr.read().decode(errors="ignore")[-400:])
    except BaseException:
        for p in (dec, enc):
            try:
                p.kill()
            except Exception:
                pass
        raise
    finally:
        try:
            dec.stdout.close()
        except Exception:
            pass
    import os
    os.replace(tmp, dst)
    return r.finish()
