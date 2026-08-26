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

# The repo name carries the season, so this URL dies on a predictable schedule.
# Two failure modes, and the quiet one is worse:
#   * the repo is gone      -> the fetch raises and lands in status.json errors
#   * the repo is archived  -> HTTP 200 forever, serving a frozen snapshot, with
#                              nothing anywhere to say the data stopped moving
# So the season is resolved at run time rather than hardcoded, and freshness is
# measured from the feed itself.
URL_TEMPLATE = ("https://raw.githubusercontent.com/SimplifyJobs/%s-Internships"
                "/dev/.github/scripts/listings.json")
# Derived from the clock so the rollover needs no code change: the current
# cycle, the next one, and the previous one as a fallback.
def seasons(today=None):
    y = (today or datetime.datetime.now(datetime.timezone.utc)).year
    return ("Summer%d" % (y + 1), "Summer%d" % (y + 2), "Summer%d" % y)
STALE_AFTER_DAYS = 21

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


def STRONG():
    """collect.py's research-role pattern. Imported lazily because collect imports
    this module, so a module-level import back into it would be circular. Sharing
    the pattern rather than copying it is deliberate: a second copy is how the tier
    field ended up disagreeing with labs.yaml."""
    import collect
    return collect.STRONG


def BLOCK():
    import collect
    return collect.BLOCK


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


def load_listings():
    """Return (listings, season, url). Tries each known season and keeps the one
    with the most live postings, so a new cycle is picked up without a code change
    and an archived cycle loses to the active one."""
    best = None
    tried = []
    for season in seasons():
        url = URL_TEMPLATE % season
        try:
            r = requests.get(url, headers=UA, timeout=180)
        except Exception as exc:
            tried.append("%s: %s" % (season, type(exc).__name__))
            continue
        if r.status_code != 200:
            tried.append("%s: HTTP %d" % (season, r.status_code))
            continue
        try:
            data = r.json()
        except ValueError:
            tried.append("%s: not JSON" % season)
            continue
        if not isinstance(data, list):
            tried.append("%s: not a list" % season)
            continue
        live = sum(1 for x in data if x.get("active"))
        tried.append("%s: %d live" % (season, live))
        if best is None or live > best[0]:
            best = (live, data, season, url)
    if best is None:
        raise RuntimeError("no SimplifyJobs season responded (%s)" % "; ".join(tried))
    return best[1], best[2], best[3], tried


def fetch(labs):
    """Return (records, stats). `labs` is the labs list out of labs.yaml."""
    listings, season, url, tried = load_listings()

    tracked = set()
    for lab in labs:
        if lab.get("active"):
            tracked |= name_keys(lab["name"])
    tracked -= BLINDSPOT

    excluded = set()
    for lab in labs:
        if lab.get("active") is False:
            excluded |= name_keys(lab["name"])

    # How fresh is the feed? An archived repo keeps answering 200 with a snapshot
    # that never moves, which no error path would ever catch.
    newest = max((x.get("date_updated") or 0 for x in listings), default=0)
    age_days = None
    if newest:
        age_days = int((datetime.datetime.now(datetime.timezone.utc)
                        - datetime.datetime.fromtimestamp(newest, datetime.timezone.utc)).days)

    out = []
    stats = {"season": season, "url": url, "tried": tried,
             "newest_entry_age_days": age_days,
             "stale": bool(age_days is not None and age_days > STALE_AFTER_DAYS),
             "total": len(listings), "active": 0, "phd": 0, "blindspot": 0, "discovery": 0,
             "dropped_tracked": 0, "dropped_category": 0, "dropped_excluded": 0,
             "by_title": 0}

    for item in listings:
        if not (item.get("active") and item.get("is_visible")):
            continue
        stats["active"] += 1

        keys = name_keys(item.get("company_name"))
        entry = catalogue_entry(keys, labs)

        # The degrees field is the gate, because a title alone cannot carry 2000
        # active postings. But the field is optional and frequently just absent:
        # Meta's "Research Scientist Intern - State Estimation for Dexterous
        # Manipulation" and "Anthropic Fellows Program" both arrive with degrees
        # empty. So a title that already names a research position -- judged by the
        # same STRONG pattern the ATS path uses, not a second copy of it -- is
        # accepted instead, and only for a company already in labs.yaml. Both halves
        # are needed: drop STRONG and the gate is gone, drop the catalogue check and
        # the opening floods in university research-assistant and quant-desk
        # postings, which carry no degree label either.
        title = item.get("title") or ""
        by_degree = "PhD" in (item.get("degrees") or [])
        by_title = bool(entry) and bool(STRONG().search(title)) and not BLOCK().search(title)
        if not (by_degree or by_title):
            continue
        stats["phd"] += 1
        if not by_degree:
            stats["by_title"] += 1
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
            "match": ["simplify-degrees-phd"] if by_degree else ["simplify-research-title"],
            "phd": by_degree,
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
