#!/usr/bin/env python3
"""Openings that never reach a job board, listed in manual.yaml.

Exists because of the one gap automated collection cannot close. Small research
labs — Sakana AI, AMI Labs and the like — announce internships in an X post, a
mailing list or a page on their own site, and never file them anywhere
machine-readable. Every automated route to X is closed: the v2 API needs a paid
tier to search, the syndication endpoint rate-limits immediately, and Nitter is
dead. So a person adds these, and they are trusted without filtering.
"""
import hashlib
import re

import yaml

PATH = "manual.yaml"
# Shown as the card's source label, so a listing says where it actually came from
# rather than describing the process that put it here.
VIA_LABEL = {"x": "X post", "email": "Mailing list", "referral": "Referral",
             "lab-page": "Lab website", "conference": "Conference", "other": "Own site"}
VALID_TIERS = {"frontier", "research-org", "bigtech", "startup", "infra"}


def load(path=PATH):
    try:
        doc = yaml.safe_load(open(path)) or {}
    except FileNotFoundError:
        return []
    entries = doc.get("openings") or []

    out = []
    for i, e in enumerate(entries):
        missing = [k for k in ("company", "title", "url") if not e.get(k)]
        if missing:
            print("  manual.yaml entry %d skipped — missing %s" % (i + 1, ", ".join(missing)))
            continue

        tier = e.get("tier") or "frontier"
        if tier not in VALID_TIERS:
            print("  manual.yaml %s — unknown tier %r, using 'frontier'" % (e["company"], tier))
            tier = "frontier"

        via = (e.get("via") or "other").lower()
        posted = e.get("posted")
        # Accept a bare date or a full timestamp; yaml already gives us a date object
        # for `2026-08-20`, so normalise both to an ISO string.
        posted_at = None
        if posted:
            posted_at = str(posted)
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", posted_at):
                posted_at += "T00:00:00+00:00"

        # A standing role with no deadline and no posting date belongs with the
        # other always-open channels, not among the dated listings. Sakana AI's
        # research roles say "we are occasionally hiring" and carry no date at all.
        always_open = bool(e.get("always_open"))

        note = e.get("note") or ""
        if e.get("deadline"):
            note = ("deadline %s. %s" % (e["deadline"], note)).strip()

        out.append({
            "company": e["company"], "tier": tier, "ats": "manual",
            "source": "manual", "kind": "evergreen" if always_open else "manual",
            "title": e["title"], "location": e.get("location") or "",
            "url": e["url"], "posted_at": posted_at,
            "department": "",
            "source_label": VIA_LABEL.get(via, "Off-board"),
            "confidence": "high", "match": ["off-board", "via-%s" % via],
            "phd": bool(e.get("phd")), "note": note,
            "job_id": "manual:%s" % hashlib.sha1(
                ("%s|%s|%s" % (e["company"], e["title"], e["url"])).encode()).hexdigest()[:16],
        })
    return out


if __name__ == "__main__":
    for j in load():
        print("%-24s %-52s %s" % (j["company"], j["title"][:52], j["department"]))
    print("%d off-board openings" % len(load()))
