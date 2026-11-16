"""Lokal SQLite baza: media indeksi va tahlil keshi. Hech narsa tarmoqqa chiqmaydi."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets(
    hash TEXT PRIMARY KEY, path TEXT, info TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS analysis(
    key TEXT PRIMARY KEY, asset_hash TEXT, kind TEXT, value TEXT, created REAL);
CREATE INDEX IF NOT EXISTS idx_analysis_asset ON analysis(asset_hash);
CREATE TABLE IF NOT EXISTS recent(path TEXT PRIMARY KEY, opened REAL);
CREATE TABLE IF NOT EXISTS library(
    path TEXT PRIMARY KEY, category TEXT, name TEXT, meta TEXT, status TEXT, note TEXT,
    size INTEGER, mtime REAL, scanned REAL);
CREATE INDEX IF NOT EXISTS idx_library_cat ON library(category);
CREATE TABLE IF NOT EXISTS plugins(
    path TEXT PRIMARY KEY, name TEXT, standard TEXT, vendor TEXT, platform TEXT,
    status TEXT, note TEXT, scanned REAL);
CREATE TABLE IF NOT EXISTS project_snapshots(
    project_id TEXT PRIMARY KEY, title TEXT, state_json TEXT, sha256 TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS journal(
    tx_id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, label TEXT,
    state_json TEXT, sha256 TEXT, created REAL);
CREATE INDEX IF NOT EXISTS idx_journal_project ON journal(project_id, tx_id);
"""


def default_db_path() -> Path:
    base = Path(os.environ.get("KADRGO_HOME") or Path.home() / ".kadrgo")
    base.mkdir(parents=True, exist_ok=True)
    return base / "kadrgo.db"


def analysis_key(asset_hash: str, kind: str, model: str, version: str, params: Optional[dict] = None) -> str:
    """Kesh kaliti: asset + tahlil turi + model + qoida versiyasi + parametrlar.
    Subtitr uslubi o'zgarsa kalit o'zgarmaydi, shuning uchun video qayta tahlil qilinmaydi."""
    raw = json.dumps([asset_hash, kind, model, version, params or {}], sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()


class LocalDB:
    def __init__(self, path: Optional[str | Path] = None):
        self.path = str(path or default_db_path())
        self.con = sqlite3.connect(self.path, check_same_thread=False)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self.con.execute("PRAGMA foreign_keys=ON")
        self.con.executescript(SCHEMA)
        self.con.commit()

    def close(self):
        self.con.close()

    # -- assetlar ----------------------------------------------------
    def put_asset(self, asset_hash: str, path: str, info: dict):
        self.con.execute("INSERT OR REPLACE INTO assets VALUES(?,?,?,?)",
                         (asset_hash, path, json.dumps(info), time.time()))
        self.con.commit()

    def find_by_hash(self, asset_hash: str) -> Optional[dict]:
        r = self.con.execute("SELECT path, info FROM assets WHERE hash=?", (asset_hash,)).fetchone()
        return {"path": r[0], **json.loads(r[1])} if r else None

    # -- tahlil keshi --------------------------------------------------
    def get_analysis(self, key: str) -> Optional[Any]:
        r = self.con.execute("SELECT value FROM analysis WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else None

    def put_analysis(self, key: str, asset_hash: str, kind: str, value: Any):
        self.con.execute("INSERT OR REPLACE INTO analysis VALUES(?,?,?,?,?)",
                         (key, asset_hash, kind, json.dumps(value), time.time()))
        self.con.commit()

    # -- tekshiriladigan loyiha snapshoti + jurnal (o'z-o'zini tiklash) -----
    @staticmethod
    def _sha(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def snapshot_project(self, project_id: str, title: str, state: dict, label: str = "autosave",
                         keep: int = 50) -> str:
        """Loyiha holatini SHA-256 bilan saqlaydi va jurnalga yozadi (bitta tranzaksiyada)."""
        text = json.dumps(state, ensure_ascii=False, sort_keys=True)
        sha = self._sha(text)
        now = time.time()
        with self.con:
            self.con.execute("INSERT OR REPLACE INTO project_snapshots VALUES(?,?,?,?,?)",
                             (project_id, title, text, sha, now))
            self.con.execute("INSERT INTO journal(project_id,label,state_json,sha256,created) VALUES(?,?,?,?,?)",
                             (project_id, label, text, sha, now))
            self.con.execute(
                "DELETE FROM journal WHERE project_id=? AND tx_id NOT IN "
                "(SELECT tx_id FROM journal WHERE project_id=? ORDER BY tx_id DESC LIMIT ?)",
                (project_id, project_id, keep))
        return sha

    def load_project_verified(self, project_id: str) -> Optional[dict]:
        """Checksum mos kelsa o'sha holat; kelmasa jurnaldagi eng yangi SOG'LOM yozuv. Hech biri bo'lmasa xato."""
        r = self.con.execute("SELECT state_json, sha256 FROM project_snapshots WHERE project_id=?",
                             (project_id,)).fetchone()
        if r is None:
            return None
        if self._sha(r[0]) == r[1]:
            return json.loads(r[0])
        for text, sha in self.con.execute(
                "SELECT state_json, sha256 FROM journal WHERE project_id=? ORDER BY tx_id DESC", (project_id,)):
            if self._sha(text) == sha:
                return json.loads(text)
        raise ValueError("Loyiha checksumi mos kelmadi va sog'lom jurnal yozuvi topilmadi")

    def integrity(self) -> str:
        return self.con.execute("PRAGMA integrity_check").fetchone()[0]

    def stats(self) -> dict:
        q = lambda sql: self.con.execute(sql).fetchone()[0]
        return {"integrity": self.integrity(), "library_items": q("SELECT COUNT(*) FROM library"),
                "plugins": q("SELECT COUNT(*) FROM plugins"), "snapshots": q("SELECT COUNT(*) FROM project_snapshots"),
                "journal": q("SELECT COUNT(*) FROM journal"),
                "size_kb": round(os.path.getsize(self.path) / 1024, 1) if os.path.exists(self.path) else 0}

    # -- so'nggi loyihalar -------------------------------------------
    def add_recent(self, path: str):
        self.con.execute("INSERT OR REPLACE INTO recent VALUES(?,?)", (path, time.time()))
        self.con.commit()

    def recent(self, limit: int = 10) -> list[str]:
        return [r[0] for r in self.con.execute(
            "SELECT path FROM recent ORDER BY opened DESC LIMIT ?", (limit,))]
