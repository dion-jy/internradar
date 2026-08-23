#!/usr/bin/env python3
"""Company logos, fetched once and inlined.

Favicons are pulled at build time and stored as data URIs so the published page
still makes zero external requests. Results are cached in data/logos.json and
committed, so a daily run refetches nothing and a company whose site is down keeps
the logo it already had.

Google's favicon service is used because it normalises size and returns ~1KB PNGs;
DuckDuckGo's equivalent works too but averages ten times larger. Clearbit's logo
API, the obvious choice a year ago, is gone.

A domain that has no icon of its own gets served a generic globe. Those are
detected by content hash -- one identical image appearing under many unrelated
domains is not a logo -- and dropped, so the card falls back to a lettermark.
"""
import base64
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor

import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; PhDInternBoard/0.1)"}
ENDPOINT = "https://www.google.com/s2/favicons?domain=%s&sz=64"
CACHE = "data/logos.json"

# Hosts that belong to an applicant-tracking system rather than the employer.
ATS_HOST = re.compile(
    r"greenhouse|ashbyhq|lever\.co|myworkdayjobs|myworkdaysite|workday|smartrecruiters|icims"
    r"|eightfold|avature|oraclecloud|workable|rippling|simplify\.jobs|jobvite|successfactors"
    r"|taleo|bamboohr|breezy|teamtailor|paylocity|dayforcehcm", re.I)


def domain_from_url(url):
    m = re.match(r"https?://([^/]+)", url or "")
    if not m:
        return ""
    host = m.group(1).lower()
    if ATS_HOST.search(host):
        return ""
    return re.sub(r"^(www|jobs|careers|apply|boards|job-boards|talent|work)\.", "", host)


def _fetch(domain):
    try:
        r = requests.get(ENDPOINT % domain, headers=UA, timeout=20)
    except Exception:
        return domain, None
    if r.status_code != 200 or len(r.content) < 100 or len(r.content) > 40000:
        return domain, None
    return domain, r.content


def collect(listings, cache_path=CACHE):
    """-> {company: data-uri}. Only fetches domains that are not already cached."""
    try:
        cache = json.load(open(cache_path))
    except (FileNotFoundError, ValueError):
        cache = {}

    wanted = {}
    for j in listings:
        name = j.get("company")
        if not name or name in wanted:
            continue
        dom = j.get("domain") or domain_from_url(j.get("url"))
        if dom:
            wanted[name] = dom

    todo = sorted({d for d in wanted.values() if d not in cache})
    if todo:
        with ThreadPoolExecutor(max_workers=8) as pool:
            fetched = list(pool.map(_fetch, todo))
        blobs = {d: c for d, c in fetched if c}
        # a generic placeholder shows up byte-identical under many domains
        counts = {}
        for c in blobs.values():
            h = hashlib.sha1(c).hexdigest()
            counts[h] = counts.get(h, 0) + 1
        generic = {h for h, n in counts.items() if n >= 4}
        for d, _ in fetched:
            c = blobs.get(d)
            if c and hashlib.sha1(c).hexdigest() not in generic:
                cache[d] = "data:image/png;base64," + base64.b64encode(c).decode()
            else:
                cache[d] = ""
        json.dump(cache, open(cache_path, "w"))
        print("  logos: fetched %d, %d had none of their own"
              % (len(todo), sum(1 for d in todo if not cache.get(d))))

    return {name: cache.get(dom, "") for name, dom in wanted.items() if cache.get(dom)}
