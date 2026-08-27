#!/usr/bin/env python3
"""Step 1 — probe candidate job-board slugs against three public ATS APIs.

Existence is decided by response *shape* — type, fields, HTTP status — never by
how many items came back. The failure responses differ per vendor:

    Greenhouse   HTTP 404, or a body of {"status": 404}
    Ashby        HTTP 200 with the plain text "Not Found"
    Lever        HTTP 200 with {"ok": false, "error": "Document not found"}

The Lever one is the trap: that failure body is a dict, so len() returns 2 and a
naive "did we get any items?" check reports two openings for a slug that does not
exist. mistral-ai, together-ai, cohere and adept were all recorded as live boards
that way before this was caught.
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; PhDInternBoard/0.1)"}
WD_HEADERS = {"Content-Type": "application/json", "Accept": "application/json",
              "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
TIMEOUT = 20


def probe_greenhouse(slug):
    url = "https://boards-api.greenhouse.io/v1/boards/%s/jobs" % slug
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
    except Exception as exc:
        return {"ok": False, "reason": "exc:%s" % type(exc).__name__}
    if r.status_code != 200:
        return {"ok": False, "reason": "http:%d" % r.status_code}
    try:
        body = r.json()
    except ValueError:
        return {"ok": False, "reason": "nonjson"}
    if not isinstance(body, dict) or not isinstance(body.get("jobs"), list):
        return {"ok": False, "reason": "shape:%s" % str(body)[:60]}
    return {"ok": True, "count": len(body["jobs"])}


def probe_ashby(slug):
    url = "https://api.ashbyhq.com/posting-api/job-board/%s" % slug
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
    except Exception as exc:
        return {"ok": False, "reason": "exc:%s" % type(exc).__name__}
    if r.status_code != 200:
        return {"ok": False, "reason": "http:%d" % r.status_code}
    if not r.text.strip().startswith("{"):
        return {"ok": False, "reason": "notfound"}
    try:
        body = r.json()
    except ValueError:
        return {"ok": False, "reason": "nonjson"}
    if not isinstance(body, dict) or not isinstance(body.get("jobs"), list):
        return {"ok": False, "reason": "shape:%s" % str(body)[:60]}
    return {"ok": True, "count": len(body["jobs"])}


def probe_lever(slug):
    url = "https://api.lever.co/v0/postings/%s?mode=json" % slug
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
    except Exception as exc:
        return {"ok": False, "reason": "exc:%s" % type(exc).__name__}
    if r.status_code != 200:
        return {"ok": False, "reason": "http:%d" % r.status_code}
    try:
        body = r.json()
    except ValueError:
        return {"ok": False, "reason": "nonjson"}
    # Success is a list. Anything else is the failure envelope described above.
    if not isinstance(body, list):
        return {"ok": False, "reason": "dict:%s" % str(body)[:60]}
    return {"ok": True, "count": len(body)}


def probe_workday(slug):
    """Workday, unlike the other three, is addressed by three parts rather than one:
    slug is "host/tenant/site". The endpoint is a POST and answers 422 when the
    tenant or site is wrong, which is a clean signal -- unlike Lever, there is no
    success-shaped failure body to guard against. total is the count for the search
    term, not the board, so it is reported as such."""
    try:
        host, tenant, site = slug.split("/", 2)
    except ValueError:
        return {"ok": False, "reason": "slug must be host/tenant/site"}
    url = "https://%s/wday/cxs/%s/%s/jobs" % (host, tenant, site)
    try:
        r = requests.post(url, headers=WD_HEADERS, timeout=TIMEOUT,
                          json={"appliedFacets": {}, "limit": 5, "offset": 0,
                                "searchText": "intern"})
    except Exception as exc:
        return {"ok": False, "reason": "exc:%s" % type(exc).__name__}
    if r.status_code != 200:
        return {"ok": False, "reason": "http:%d" % r.status_code}
    try:
        body = r.json()
    except ValueError:
        return {"ok": False, "reason": "nonjson"}
    if not isinstance(body, dict) or not isinstance(body.get("jobPostings"), list):
        return {"ok": False, "reason": "shape:%s" % str(body)[:60]}
    return {"ok": True, "count": body.get("total", 0)}


PROBES = {"greenhouse": probe_greenhouse, "ashby": probe_ashby,
          "lever": probe_lever, "workday": probe_workday}


def run(task):
    name, ats, slug = task
    return {"name": name, "ats": ats, "slug": slug, **PROBES[ats](slug)}


def main(path):
    candidates = json.load(open(path))
    tasks = [
        (c["name"], ats, slug)
        for c in candidates
        for slug in c["slugs"]
        for ats in c.get("ats", ["greenhouse", "ashby", "lever"])
        # workday is never probed by default: its slug is a three-part address that
        # has to be read off the careers page, not guessed like the other three.
    ]
    print("# %d probes over %d companies" % (len(tasks), len(candidates)), file=sys.stderr)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run, tasks))
    json.dump(results, open("probe_results.json", "w"), indent=1)

    hits = [r for r in results if r["ok"]]
    for h in sorted(hits, key=lambda x: (x["name"], -x["count"])):
        print("HIT  %-26s %-11s %-24s %d" % (h["name"], h["ats"], h["slug"], h["count"]))

    print("\n# %d hits / %d probes" % (len(hits), len(results)), file=sys.stderr)
    missed = sorted({c["name"] for c in candidates} - {h["name"] for h in hits})
    print("\n# MISS (%d): %s" % (len(missed), ", ".join(missed)), file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
