"""Vault: foydalanuvchi o'zi yig'adigan lokal baza (SFX, shrift, LUT, plagin) joylashadigan papka.

Dastur BU papkani skanerlaydi, tekshiradi va indekslaydi (library/scanner.py). Hech narsa internetdan
yuklanmaydi va avtomatik "qo'shib qo'yilmaydi": nima bo'lsa, o'sha ko'rsatiladi.

Joylashuv:
  KADRGO_VAULT_DIR muhit o'zgaruvchisi, bo'lmasa
  Windows:  D:\\KadrgoStudio_Vault (D: diski bo'lsa), aks holda  C:\\Users\\<siz>\\KadrgoStudio_Vault
  macOS:    ~/Library/Application Support/KadrgoStudio
  Linux:    ~/.kadrgo_studio_vault

Ichida:
  Library/SFX  Library/Music  Library/Fonts  Library/LUT  Library/Plugins   <- siz fayllarni shu yerga tashlaysiz
  Projects/    Cache/    KadrgoVault.kadrdb
"""
from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Optional

from .db import LocalDB

SUBDIRS = ["Library/SFX", "Library/Music", "Library/Fonts", "Library/LUT", "Library/Plugins", "Projects", "Cache"]


def resolve_root(override: Optional[str] = None) -> Path:
    env = override or os.environ.get("KADRGO_VAULT_DIR")
    if env:
        return Path(env)
    sysname = platform.system()
    if sysname == "Windows":
        return Path("D:/KadrgoStudio_Vault") if Path("D:/").exists() else Path.home() / "KadrgoStudio_Vault"
    if sysname == "Darwin":
        return Path.home() / "Library" / "Application Support" / "KadrgoStudio"
    return Path.home() / ".kadrgo_studio_vault"


class Vault:
    def __init__(self, root: Optional[str] = None):
        self.root = resolve_root(root)
        for d in SUBDIRS:
            (self.root / d).mkdir(parents=True, exist_ok=True)
        self.library = self.root / "Library"
        self.projects = self.root / "Projects"
        self.cache = self.root / "Cache"
        self.db = LocalDB(self.root / "KadrgoVault.kadrdb")
        # media keshi va subtitr shriftlari shu papkadan ishlaydi
        os.environ.setdefault("KADRGO_CACHE", str(self.cache))
        os.environ["KADRGO_FONTS"] = str(self.library / "Fonts")

    def plugin_search_paths(self) -> dict[str, list[str]]:
        s = platform.system()
        own = str(self.library / "Plugins")
        if s == "Windows":
            return {"ofx": [r"C:\Program Files\Common Files\OFX\Plugins", own],
                    "vst3": [r"C:\Program Files\Common Files\VST3", own], "au": []}
        if s == "Darwin":
            return {"ofx": ["/Library/OFX/Plugins", own],
                    "vst3": ["/Library/Audio/Plug-Ins/VST3", str(Path.home() / "Library/Audio/Plug-Ins/VST3"), own],
                    "au": ["/Library/Audio/Plug-Ins/Components", str(Path.home() / "Library/Audio/Plug-Ins/Components")]}
        return {"ofx": ["/usr/OFX/Plugins", own], "vst3": ["/usr/lib/vst3", str(Path.home() / ".vst3"), own], "au": []}

    def close(self):
        self.db.close()
