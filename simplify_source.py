#!/usr/bin/env python3
"""Secondary source — the structured listings JSON published by SimplifyJobs.

    https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships
        /dev/.github/scripts/listings.json

Roughly 11MB and ~14,500 entries, served straight off GitHub. This is not
scraping: the company publishes the file, and it carries `degrees`, `sponsorship`,
`active` and `date_posted` as real fields, which makes the PhD filter far more
reliable than any regex over a job title.

It plays a different role from the ATS APIs:

    blindspot   Companies that run their own applicant systems and therefore have
                no public API at all — Google, Meta, Apple, Microsoft, Amazon,
                NVIDIA, ByteDance. Building the ATS catalogue meant giving up on
                every one of them. This is how they come back.
    discovery   Companies that were never on our list to begin with.

Anything already tracked through an ATS board is dropped as a duplicate; the ATS
is the more precise source for those.
"""
import datetime
import re

import requests

URL = ("https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships"
       "/dev/.github/scripts/listings.json")
UA = {"User-Agent": "Mozilla/5.0 (compatible; PhDInternBoard/0.1)"}

# Labs with no public board, where this file is the only way we see them at all.
# Google is here rather than in the tracked set on purpose: it does have a
# Greenhouse board, but it holds ~10 roles while the actual Student Researcher
# postings live on google.com/about/careers.
BLINDSPOT = {
    "google", "googledeepmind", "deepmind", "meta", "facebook", "microsoft", "msr",
    "amazon", "aws", "amazonwebservices", "apple", "nvidia", "netflix", "qualcomm",
    "snap", "snapchat", "tesla", "bytedance", "tiktok", "ibm", "adobe", "salesforce",
    "huggingface", "groq", "skild", "skildai", "contextual", "contextualai",
}

# Category rules differ by role because the two kinds carry different risk.
#
#   discovery  We know nothing about the company, so only the strongest signal is
#              accepted. Without this, quant trading and defence flood the feed:
#              of the ~400 active PhD listings, ~50 are categorised Quant outright,
#              and firms like Citadel, DRW, Optiver, Tower Research and L3Harris
#              post plenty more under Software and Hardware.
#   blindspot  These are labs we already trust. NVIDIA files genuine research roles
#              under Hardware, so accept more and let `confidence` carry the nuance.
# A listing's tier says what kind of organisation it is -- the thing a reader
# filters on. There must be exactly one source of truth for that, and it is
# labs.yaml. Hardcoding it here put Google under "big tech" while labs.yaml had
# Google DeepMind as a frontier lab, so the same company landed in two categories
# depending on which collector found it.
ALIAS = {
    "google": "Google DeepMind", "googledeepmind": "Google DeepMind",
    "deepmind": "Google DeepMind",
    "meta": "Meta (FAIR)", "facebook": "Meta (FAIR)",
    "microsoft": "Microsoft / MSR", "msr": "Microsoft / MSR",
    "amazon": "Amazon / AWS AI", "aws": "Amazon / AWS AI",
    "amazonwebservices": "Amazon / AWS AI",
    "apple": "Apple", "nvidia": "NVIDIA", "netflix": "Netflix",
    "qualcomm": "Qualcomm", "snap": "Snap", "snapchat": "Snap", "tesla": "Tesla",
    "bytedance": "ByteDance / TikTok", "tiktok": "ByteDance / TikTok",
    "ibm": "IBM Research", "adobe": "Adobe", "salesforce": "Salesforce",
    "huggingface": "Hugging Face", "groq": "Groq",
    "skild": "Skild AI", "skildai": "Skild AI",
    "contextual": "Contextual AI", "contextualai": "Contextual AI",
}


def catalogue_entry(keys, labs):
    """The labs.yaml row for a company, matched by name or alias."""
    for k in keys:
        name = ALIAS.get(k)
        if name:
            for lab in labs:
                if lab["name"] == name:
                    return lab
    for lab in labs:
        if keys & name_keys(lab["name"]):
            return lab
    return None


CATEGORIES = {
    "discovery": {"AI/ML/Data"},
    "blindspot": {"AI/ML/Data", "Software", "Hardware"},
}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def name_keys(s):
    """Match keys for a company name, including a form with a trailing "ai"
    removed so that "Etched.ai" lines up with "Etched"."""
    n = norm(s)
    keys = {n}
    if n.endswith("ai") and len(n) > 4:
        keys.add(n[:-2])
    return keys


def fetch(labs):
    """Return (records, stats). `labs` is the labs list out of labs.yaml."""
    listings = requests.get(URL, headers=UA, timeout=180).json()

    tracked = set()
    for lab in labs:
        if lab.get("active"):
            tracked |= name_keys(lab["name"])
    tracked -= BLINDSPOT

    excluded = set()
    for lab in labs:
        if lab.get("active") is False:
            excluded |= name_keys(lab["name"])

    out = []
    stats = {"total": len(listings), "active": 0, "phd": 0, "blindspot": 0, "discovery": 0,
             "dropped_tracked": 0, "dropped_category": 0, "dropped_excluded": 0}

    for item in listings:
        if not (item.get("active") and item.get("is_visible")):
            continue
        stats["active"] += 1
        if "PhD" not in (item.get("degrees") or []):
            continue
        stats["phd"] += 1

        keys = name_keys(item.get("company_name"))
        entry = catalogue_entry(keys, labs)
        if keys & excluded:
            stats["dropped_excluded"] += 1
            continue
        if keys & BLINDSPOT:
            kind = "blindspot"
        elif keys & tracked:
            stats["dropped_tracked"] += 1
            continue
        else:
            kind = "discovery"

        category = item.get("category")
        if category not in CATEGORIES[kind]:
            stats["dropped_category"] += 1
            continue
        stats[kind] += 1

        posted = item.get("date_posted")
        out.append({
            "company": item.get("company_name"), "tier": (entry or {}).get("tier") or "other", "ats": "simplify",
            "source": "simplify", "kind": kind,
            "title": item.get("title"),
            "location": ", ".join(item.get("locations") or []),
            "url": item.get("url") or item.get("company_url"),
            "posted_at": datetime.datetime.fromtimestamp(
                posted, datetime.timezone.utc).isoformat() if posted else None,
            "department": category or "",
            "confidence": "high" if category == "AI/ML/Data" else "medium",
            "match": ["simplify-degrees-phd"], "phd": True,
            "degrees": item.get("degrees"), "sponsorship": item.get("sponsorship"),
            "terms": item.get("terms"),
            "domain": (entry or {}).get("domain") or "",
            "job_id": "simplify:%s" % item.get("id"),
        })
    return out, stats


if __name__ == "__main__":
    import collections
    import yaml
    records, stats = fetch(yaml.safe_load(open("labs.yaml"))["labs"])
    print(stats)
    counts = collections.Counter((r["kind"], r["company"]) for r in records)
    for (kind, company), n in counts.most_common(35):
        print("  %-10s %3d  %s" % (kind, n, company))
