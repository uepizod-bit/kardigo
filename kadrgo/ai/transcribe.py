"""Lokal transkripsiya (ixtiyoriy): faster-whisper o'rnatilgan bo'lsa ishlaydi. Internet faqat modelni birinchi
marta yuklashda kerak; matn kompyuterdan chiqmaydi. O'zbekcha sifati real materialda tekshirilishi shart."""
from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Optional

from ..core import edit
from ..core.history import History
from ..media.probe import FFMPEG, run


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def transcribe_asset(history: History, asset_id: str, offset_frame: int = 0, language: Optional[str] = "uz",
                     model_size: str = "small") -> int:
    if not available():
        raise RuntimeError("faster-whisper o'rnatilmagan:  pip install faster-whisper")
    from faster_whisper import WhisperModel
    p = history.project
    a = p.assets[asset_id]
    tmp = os.path.join(tempfile.mkdtemp(), "a.wav")
    run([FFMPEG, "-v", "error", "-y", "-i", a.path, "-vn", "-ac", "1", "-ar", "16000", tmp])
    model = WhisperModel(model_size, device="auto", compute_type="auto")
    segs, _ = model.transcribe(tmp, language=language, vad_filter=True, word_timestamps=False)
    n = 0
    with history.transaction("AI: transkripsiya"):
        for s in segs:
            text = s.text.strip()
            if text:
                edit.add_cue(p, offset_frame + p.sec_to_frame(s.start), max(offset_frame + p.sec_to_frame(s.end),
                             offset_frame + p.sec_to_frame(s.start) + 1), text,
                             confidence=float(max(min(1 + (s.avg_logprob or -1) / 2, 1), 0)))
                n += 1
    return n
