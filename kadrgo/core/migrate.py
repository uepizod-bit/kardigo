"""Loyiha formati migratsiyasi. Eski versiyalar yangisiga o'tkaziladi, hech qachon buzilmaydi."""
from .model import FORMAT, VERSION


class ProjectFormatError(Exception):
    pass


def migrate(d: dict) -> dict:
    if d.get("format") != FORMAT:
        raise ProjectFormatError("Bu KADRGO loyiha fayli emas")
    v = int(d.get("version", 0))
    if v > VERSION:
        raise ProjectFormatError(f"Loyiha yangiroq versiyada ({v}); dasturni yangilang")
    # v0 -> v1: kelajakdagi o'zgarishlar shu yerga qo'shiladi
    d["version"] = VERSION
    return d
