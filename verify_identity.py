#!/usr/bin/env python3
"""Step 1b — confirm that a responding slug actually belongs to the company we meant.

A slug can return a perfectly valid board that belongs to somebody else. Real cases
caught by this pass:

    greenhouse/figure  ->  Figure Lending, a fintech   (we wanted greenhouse/figureai)
    ashby/runway       ->  cfo.ai                      (Runway ML has no public board)
    greenhouse/cais    ->  CAIS, an investments platform, not the Center for AI Safety
    lever/sesame       ->  a healthcare company        (we wanted ashby/sesame)

Where the owning company name comes from:
    Greenhouse   /v1/boards/{slug} returns {"name": ...}
    Ashby        the <title> of jobs.ashbyhq.com/{slug}
    Lever        inferred from the hosted URL, plus a look at the actual role titles
"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; PhDInternBoard/0.1)"}
TIMEOUT = 20


def identify(hit):
    ats, slug = hit["ats"], hit["slug"]
    label, titles = "?", []
    try:
        if ats == "greenhouse":
            meta = requests.get("https://boards-api.greenhouse.io/v1/boards/%s" % slug,
                                headers=UA, timeout=TIMEOUT)
            if meta.status_code == 200:
                label = meta.json().get("name", "?")
            body = requests.get("https://boards-api.greenhouse.io/v1/boards/%s/jobs" % slug,
                                headers=UA, timeout=TIMEOUT).json()
            titles = [j["title"] for j in body["jobs"][:3]]
        elif ats == "ashby":
            page = requests.get("https://jobs.ashbyhq.com/%s" % slug, headers=UA, timeout=TIMEOUT)
            m = re.search(r"<title>(.*?)</title>", page.text, re.S | re.I)
            label = m.group(1).strip()[:70] if m else "?"
            body = requests.get("https://api.ashbyhq.com/posting-api/job-board/%s" % slug,
                                headers=UA, timeout=TIMEOUT).json()
            titles = [j["title"] for j in body["jobs"][:3]]
        else:
            body = requests.get("https://api.lever.co/v0/postings/%s?mode=json" % slug,
                                headers=UA, timeout=TIMEOUT).json()
            titles = [j["text"] for j in body[:3]]
            label = body[0].get("hostedUrl", "?").split("/")[3] if body else "(empty board)"
    except Exception as exc:
        label = "ERR %s" % type(exc).__name__
    return {**hit, "label": label, "titles": titles}


def main(path):
    hits = [h for h in json.load(open(path)) if h["ok"]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(identify, hits))
    json.dump(results, open("identity.json", "w"), indent=1, ensure_ascii=False)

    for r in sorted(results, key=lambda x: x["name"]):
        print("%-28s %-10s %-22s n=%-4d :: %s"
              % (r["name"], r["ats"], r["slug"], r["count"], r["label"]))
        if r["titles"]:
            print("%-28s   %s" % ("", " | ".join(t[:45] for t in r["titles"])))


if __name__ == "__main__":
    main(sys.argv[1])
