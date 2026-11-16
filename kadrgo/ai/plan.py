"""AI montaj rejasi: LLM (yoki skript) JSON reja beradi, BU MODUL tekshiradi va qo'llaydi.

Qoidalar: reja shell/FFmpeg buyrug'i emas, faqat ma'lumot; har yozuv mavjud media va manba chegarasiga
mos bo'lishi shart; qulflangan trek/klipga tegilmaydi; hammasi BITTA qaytariladigan qadam.
Schema:  {"track":"V1","items":[{"asset":"<id>","src_in":0.0,"src_out":4.2,"reason":"...",
          "transition":{"kind":"fade","duration":0.4}}]}   (soniyalarda)
"""
from __future__ import annotations

import math
from ..core import edit
from ..core.history import History
from ..fx.catalog import TRANSITIONS


class PlanError(Exception):
    pass


def validate_plan(project, plan: dict) -> list[str]:
    errs = []
    if not isinstance(plan, dict) or not isinstance(plan.get("items"), list) or not plan["items"]:
        return ["Reja bo'sh yoki noto'g'ri tuzilgan"]
    if len(plan["items"])>1000:return ["Reja juda katta"]
    try:
        t = project.track(plan.get("track", "V1"))
    except KeyError:
        return ["Trek topilmadi"]
    if t.locked:
        errs.append(f"{t.id} treki qulflangan")
    for i, it in enumerate(plan["items"], 1):
        if not isinstance(it,dict):errs.append("Yozuv noto‘g‘ri");continue
        a = project.assets.get(it.get("asset"))
        if a is None:
            errs.append(f"#{i}: media yo'q"); continue
        s, e = it.get("src_in"), it.get("src_out")
        if not isinstance(s, (int, float)) or not isinstance(e, (int, float)) or isinstance(s,bool) or isinstance(e,bool) or not math.isfinite(s) or not math.isfinite(e) or s < 0 or e <= s:
            errs.append(f"#{i}: noto'g'ri vaqt"); continue
        if a.kind != "image" and e > a.duration + 0.05:
            errs.append(f"#{i}: manba oxiridan oshgan ({e:.2f} > {a.duration:.2f})")
        tr = it.get("transition")
        if tr and (tr.get("kind") not in TRANSITIONS or not 0 < float(tr.get("duration", 0)) <= 3):
            errs.append(f"#{i}: noto'g'ri perexod")
    return errs


def apply_plan(history: History, plan: dict, start_frame: int = 0) -> list:
    p = history.project
    errs = validate_plan(p, plan)
    if errs:
        raise PlanError("; ".join(errs[:5]))
    created = []
    with history.transaction("AI: montaj rejasi"):
        pos = start_frame
        for it in plan["items"]:
            s, e = p.sec_to_frame(it["src_in"]), p.sec_to_frame(it["src_out"])
            c = edit.add_clip(p, plan.get("track", "V1"), it["asset"], pos, s, max(e - s, 1),
                              provenance="ai:plan", label=it.get("reason", "")[:60] or "AI")
            tr = it.get("transition")
            if tr and created:
                edit.set_transition(p, c.id, tr["kind"], p.sec_to_frame(float(tr["duration"])))
            created.append(c)
            pos = c.end
    return created
