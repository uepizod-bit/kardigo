"""Kamera profili (input transform): S-Log3 -> Rec.709 uchun haqiqiy 3D LUT generatsiyasi.

Zanjir:  S-Log3 kod qiymati -> chiziqli sahna yorug'ligi -> gamut (S-Gamut3[.Cine] -> Rec.709, primarlardan
hisoblanadi) -> ekspozitsiya -> yumshoq highlight shoulder -> Rec.709 uzatish funksiyasi.

S-Log3 formulasi Sony texnik hujjatiga mos (18% kulrang = kod 420/1023). Gamut matritsalari xromatiklik
koordinatalaridan hisoblanadi (qo'lda kiritilgan raqamlar emas). Natija .cube fayli: lut3d filtri bilan
preview va export da bir xil ishlaydi.

Eslatma: bu *boshlang'ich nuqta* (neytral, ehtiyotkor), badiiy look emas. Sony A7 III da S-Log3 yoki
S-Log2 / HLG / standart profil qaysi tanlanganini foydalanuvchi belgilaydi; metadata yetmasa taxmin qilinmaydi.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import numpy as np

from ..media.probe import cache_dir

WHITE_D65 = (0.3127, 0.3290)
PRIMARIES = {
    "rec709": ((0.640, 0.330), (0.300, 0.600), (0.150, 0.060)),
    "sgamut3cine": ((0.766, 0.275), (0.225, 0.800), (0.089, -0.087)),
    "sgamut3": ((0.730, 0.280), (0.140, 0.855), (0.100, -0.050)),
}


def _xy_to_XYZ(xy):
    x, y = xy
    return np.array([x / y, 1.0, (1 - x - y) / y])


def rgb_to_xyz_matrix(prim, white=WHITE_D65) -> np.ndarray:
    r, g, b = (_xy_to_XYZ(p) for p in prim)
    M = np.stack([r, g, b], axis=1)
    S = np.linalg.solve(M, _xy_to_XYZ(white))
    return M * S


def gamut_matrix(src: str, dst: str = "rec709") -> np.ndarray:
    return np.linalg.inv(rgb_to_xyz_matrix(PRIMARIES[dst])) @ rgb_to_xyz_matrix(PRIMARIES[src])


def slog3_to_linear(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    hi = 10.0 ** ((x * 1023.0 - 420.0) / 261.5) * (0.18 + 0.01) - 0.01
    lo = (x * 1023.0 - 95.0) * 0.01125000 / (171.2102946929 - 95.0)
    return np.where(x >= 171.2102946929 / 1023.0, hi, lo)


def rec709_oetf(L: np.ndarray) -> np.ndarray:
    L = np.clip(L, 0.0, None)
    return np.where(L < 0.018, 4.5 * L, 1.099 * np.power(L, 0.45) - 0.099)


def shoulder(x: np.ndarray, knee: float = 0.75, white: float = 1.6) -> np.ndarray:
    """Chiziqli 0..knee o'zgarishsiz, undan yuqorisi yumshoq siqiladi (highlight qirqilmaydi)."""
    x = np.clip(x, 0.0, None)
    t = np.clip((x - knee) / (white - knee), 0.0, None)
    comp = knee + (1.0 - knee) * (1.0 - np.exp(-t * 1.6)) / (1.0 - np.exp(-1.6)) * 1.0
    out = np.where(x <= knee, x, comp)
    return np.clip(out, 0.0, 1.0)


def transform(rgb: np.ndarray, gamut: str = "sgamut3cine", exposure: float = 0.0, contrast: float = 1.0) -> np.ndarray:
    """rgb: (...,3) S-Log3 kodlari [0..1] -> Rec.709 display [0..1]."""
    lin = slog3_to_linear(rgb)
    lin = lin @ gamut_matrix(gamut).T
    lin = lin * (2.0 ** exposure)
    if contrast != 1.0:
        lin = 0.18 * np.power(np.clip(lin, 1e-6, None) / 0.18, contrast)
    return rec709_oetf(shoulder(lin))


def build_cube(path: str | Path, gamut: str = "sgamut3cine", exposure: float = 0.0, contrast: float = 1.0,
               size: int = 33) -> Path:
    g = np.linspace(0.0, 1.0, size)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")           # R eng tez o'zgaradi (.cube qoidasi)
    grid = np.stack([r, gg, b], axis=-1).reshape(-1, 3)
    out = np.clip(transform(grid, gamut, exposure, contrast), 0.0, 1.0)
    lines = [f'TITLE "KADRGO S-Log3 {gamut} ev={exposure:+.2f}"', f"LUT_3D_SIZE {size}", "DOMAIN_MIN 0 0 0",
             "DOMAIN_MAX 1 1 1"]
    lines += [f"{a:.6f} {b_:.6f} {c:.6f}" for a, b_, c in out]
    path = Path(path)
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return path


def cube_for(gamut: str, exposure: float, contrast: float = 1.0) -> str:
    """Keshlangan .cube fayl yo'li (parametrlarga qarab)."""
    key = hashlib.sha1(f"{gamut}|{exposure:.3f}|{contrast:.3f}|v1".encode()).hexdigest()[:12]
    p = cache_dir() / f"slog3_{gamut}_{key}.cube"
    if not p.exists():
        build_cube(p, gamut, exposure, contrast)
    return str(p)


def read_cube(path: str | Path) -> dict:
    """.cube faylni tekshiradi: o'lcham, qatorlar soni, diapazon. Xato bo'lsa ValueError."""
    size, n, dim = 0, 0, 3
    lo, hi = 1e9, -1e9
    for line in Path(path).read_text(errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("TITLE"):
            continue
        if s.startswith("LUT_3D_SIZE"):
            size, dim = int(s.split()[1]), 3
        elif s.startswith("LUT_1D_SIZE"):
            size, dim = int(s.split()[1]), 1
        elif s[0] in "-+.0123456789":
            parts = s.split()
            if len(parts) != 3:
                raise ValueError("Noto'g'ri LUT qatori")
            v = [float(x) for x in parts]
            lo, hi = min(lo, *v), max(hi, *v)
            n += 1
    expect = size ** 3 if dim == 3 else size
    if size < 2 or n != expect:
        raise ValueError(f"LUT hajmi mos emas: kutilgan {expect}, topilgan {n}")
    return {"size": size, "dim": dim, "min": lo, "max": hi}
