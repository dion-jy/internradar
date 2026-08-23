#!/usr/bin/env python3
"""Rebuild labs.yaml from the confirmed catalogue.

Job counts are read out of the probe results rather than typed by hand, so the
file can never drift from what was actually observed.
"""
import json

import yaml

VERIFIED_AT = "2026-08-23"

counts = {}
for path in ("probe_r1.json", "probe_r2.json", "probe_r3.json"):
    for row in json.load(open(path)):
        if row["ok"]:
            counts[(row["ats"], row["slug"])] = row["count"]

existing = yaml.safe_load(open("labs.yaml"))["labs"]
for lab in existing:
    if lab["ats"] != "none":
        key = (lab["ats"], lab["slug"])
        if key in counts:
            lab["job_count"] = counts[key]
            lab["verified_at"] = VERIFIED_AT

with open("labs.yaml", "w") as f:
    f.write("# PhD Intern Board — lab catalogue\n"
            "# Verified %s. A slug is only recorded once the board responded with the right\n"
            "# shape AND the owning company name matched what we expected. `ats: none` entries are\n"
            "# kept deliberately so the same dead ends are not retried every run.\n"
            "# `active: false` means the board is real but deliberately left out of collection.\n"
            % VERIFIED_AT)
    yaml.safe_dump({"labs": existing}, f, allow_unicode=True, sort_keys=False, width=200)

active = [l for l in existing if l.get("active")]
print("%d confirmed / %d unresolved — %d total, %d live postings"
      % (sum(1 for l in existing if l["ats"] != "none"),
         sum(1 for l in existing if l["ats"] == "none"),
         len(existing), sum(l["job_count"] for l in active)))
