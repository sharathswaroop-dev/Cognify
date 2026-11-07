"""Say what kind of knowledge each retrieved record is, so an answer can be weighed instead of trusted blindly.

A proven repair (it worked and did not come back) is not the same as a colleague's note, a document, or a suspected cause. Chat answers carry these
labels, and a correction someone has made is shown ahead of the answer it corrects. Pure functions over the tags we already retain."""
from __future__ import annotations

TIER_ORDER = ("correction", "verified", "unproven", "note", "doc", "context")
TIER_NAME = {"correction": "correction", "verified": "proven repair", "unproven": "unproven repair", "note": "colleague note", "doc": "document", "context": "background record"}


def classify(tags: list[str]) -> dict:
    t = set(tags or [])
    level = next((x.split(":", 1)[1] for x in t if x.startswith("evidence:")), "")
    if "kind:correction" in t:
        return {"label": "Correction", "tier": "correction"}
    if "kind:note" in t:
        return {"label": "Colleague's note", "tier": "note"}
    if "kind:doc" in t:
        return {"label": "Document", "tier": "doc"}
    if "kind:visit" in t:
        if level in ("stable_30d", "stable_90d"):
            return {"label": "Proven repair", "tier": "verified"}
        return {"label": "Suspected cause" if level == "suspected" else "Fixed at the visit, not yet proven", "tier": "unproven"}
    if "kind:followup" in t:
        return {"label": "Follow-up check", "tier": "context"}
    if "kind:site" in t:
        return {"label": "Site profile", "tier": "context"}
    if "kind:alarm" in t:
        return {"label": "Alarm log", "tier": "context"}
    if "kind:belief" in t:
        return {"label": "Corrected belief", "tier": "correction"}
    return {"label": "Record", "tier": "context"}


def basis(sources: list[dict]) -> dict:
    """How well supported an answer is, from the kinds of records it was drawn from. Strong needs at least two proven repairs."""
    counts = {k: 0 for k in TIER_ORDER}
    for s in sources:
        counts[s.get("tier", "context")] += 1
    parts = [f"{counts[k]} {TIER_NAME[k]}{'' if counts[k] == 1 else 's'}" for k in TIER_ORDER if counts[k] and k != "context"]
    if counts["verified"] >= 2:
        level = "strong"
    elif counts["verified"] or counts["note"] or counts["doc"] or counts["correction"]:
        level = "partial"
    else:
        level = "weak"
    note = {"strong": "Backed by proven repairs.", "partial": "Backed by notes, documents or only one proven repair: check before relying on it.",
            "weak": "Nothing proven behind this. Treat it as a lead, not an answer."}[level]
    return {"level": level, "counts": counts, "summary": ", ".join(parts) or "background records only", "note": note}
