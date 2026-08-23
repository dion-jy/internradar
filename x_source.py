#!/usr/bin/env python3
"""Turn an X post link into a manual.yaml entry.

    python x_source.py https://x.com/msraurjp/status/2090645729052418108 ...

Small research labs and big-tech research groups routinely announce an internship
in an X post and nowhere machine-readable. There is no automated route to those:
the v2 API needs a paid tier to search, Nitter is dead, and the timeline
endpoints rate-limit immediately. One thing does still work unauthenticated --
X's own embed endpoint for a *single known post*:

    https://cdn.syndication.twimg.com/tweet-result?id={id}&lang=en

So the post cannot be discovered automatically, but once a person has the link,
the text, author, date and outbound links can be read without retyping them.

This is deliberately a one-off helper rather than part of collect.py. The
endpoint is undocumented and could disappear; the daily job must not depend on
it. Run this, check what it printed, paste it into manual.yaml.
"""
import base64
import json
import re
import sys

import requests
import yaml

UA = {"User-Agent": "Mozilla/5.0 (compatible; PhDInternBoard/0.1)"}
ENDPOINT = "https://cdn.syndication.twimg.com/tweet-result?id=%s&lang=en&token=a"


# Used only when drafting a manual.yaml entry, where a single apply URL is needed.
# A post often mentions the company homepage next to the actual posting, and taking
# the first link picked "http://nvidia.com" over the Workday job link on one of
# these. The strip itself shows every link, in the order the post had them.
APPLY_HINT = re.compile(
    r"myworkdayjobs|greenhouse|ashbyhq|jobs\.lever|smartrecruiters|workable|icims|eightfold"
    r"|/job[s]?/|/career|/apply|/opening|/positions?/|/vacanc", re.I)


def rank_links(links):
    def score(u):
        s = 0
        if APPLY_HINT.search(u):
            s -= 4
        path = re.sub(r"^https?://[^/]+", "", u).strip("/")
        if not path:            # a bare domain is a mention, not a posting
            s += 3
        s += 1 if len(path) < 8 else 0
        return s
    return sorted(links, key=score)


def post_id(url_or_id):
    m = re.search(r"/status/(\d+)", url_or_id)
    if m:
        return m.group(1)
    if url_or_id.strip().isdigit():
        return url_or_id.strip()
    raise ValueError("cannot find a post id in %r" % url_or_id)


def fetch(url_or_id):
    pid = post_id(url_or_id)
    r = requests.get(ENDPOINT % pid, headers=UA, timeout=25)
    if r.status_code != 200 or not r.text.strip().startswith("{"):
        raise RuntimeError("HTTP %s for post %s" % (r.status_code, pid))
    d = r.json()
    user = d.get("user") or {}
    links = [u.get("expanded_url") for u in (d.get("entities") or {}).get("urls", [])
             if u.get("expanded_url")]

    # Show the post as written. The only trimming is display_text_range, which is
    # X's own marker for where the visible text ends (trailing media and quote-tweet
    # links sit outside it) -- the same cut X itself makes when rendering a post.
    # Nothing else is touched: line breaks, emoji and t.co links all stay.
    text = d.get("text") or ""
    rng = d.get("display_text_range")
    if isinstance(rng, list) and len(rng) == 2:
        text = text[rng[0]:rng[1]]
    return {
        "id": pid,
        "author": user.get("screen_name"),
        "author_name": user.get("name"),
        "posted": (d.get("created_at") or "")[:10],
        "text": text,
        "links": links,
        "post_url": "https://x.com/%s/status/%s" % (user.get("screen_name"), pid),
        "avatar_url": user.get("profile_image_url_https") or "",
    }


def avatar_data_uri(url):
    """Inline the avatar so the published page still makes zero external requests.
    These are ~2KB JPEGs, small enough that embedding beats a network round trip."""
    if not url:
        return ""
    try:
        r = requests.get(url, headers=UA, timeout=20)
        if r.status_code != 200 or len(r.content) > 60000:
            return ""
        mime = r.headers.get("content-type", "image/jpeg").split(";")[0]
        return "data:%s;base64,%s" % (mime, base64.b64encode(r.content).decode())
    except Exception:
        return ""


def load_feed(path="xposts.yaml", cache="data/xposts_cache.json"):
    """Fetch every post listed in xposts.yaml.

    The syndication endpoint is undocumented, so a failure must not take the daily
    run down with it: whatever was fetched last time is reused, and only genuinely
    new links can fail outright.
    """
    try:
        doc = yaml.safe_load(open(path)) or {}
    except FileNotFoundError:
        return [], {"listed": 0, "fetched": 0, "from_cache": 0, "failed": 0}
    listed = doc.get("posts") or []

    try:
        cached = {p["id"]: p for p in json.load(open(cache))["posts"]}
    except (FileNotFoundError, KeyError, ValueError):
        cached = {}

    out, stats = [], {"listed": len(listed), "fetched": 0, "from_cache": 0, "failed": 0}
    for entry in listed:
        url = entry.get("url") if isinstance(entry, dict) else entry
        if not url:
            continue
        try:
            pid = post_id(url)
        except ValueError:
            stats["failed"] += 1
            continue
        try:
            p = fetch(url)
            p["avatar"] = avatar_data_uri(p.pop("avatar_url", ""))
            stats["fetched"] += 1
        except Exception as exc:
            if pid in cached:
                p = cached[pid]
                stats["from_cache"] += 1
            else:
                print("  xposts: %s failed and is not cached -- %s" % (url, exc))
                stats["failed"] += 1
                continue
        if isinstance(entry, dict) and entry.get("note"):
            p["note"] = entry["note"]
        out.append(p)

    out.sort(key=lambda p: p.get("posted") or "", reverse=True)
    json.dump({"posts": out}, open(cache, "w"), ensure_ascii=False)
    return out, stats


def as_yaml(p):
    """A draft entry. The company and title are guesses from the post text -- read
    them before pasting."""
    ranked = rank_links(p["links"])
    apply_url = ranked[0] if ranked else p["post_url"]
    first_line = p["text"].split("\n")[0].strip()
    title = re.sub(r"^\[[^\]]*\]\s*", "", first_line)[:90] or "Research internship"
    note = " ".join(p["text"].split())
    if len(note) > 260:
        note = note[:257] + "..."
    out = [
        "  - company: %s" % (p["author_name"] or p["author"]),
        "    title: %s" % title,
        "    url: %s" % apply_url,
        "    via: x",
        "    tier: bigtech        # frontier | research-org | bigtech | startup | infra",
        "    posted: %s" % p["posted"],
        "    phd: true",
        "    note: >-",
        "      %s" % note,
        "      Announced at %s" % p["post_url"],
    ]
    return "\n".join(out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    for arg in sys.argv[1:]:
        try:
            p = fetch(arg)
        except Exception as exc:
            print("# FAILED %s -- %s" % (arg, exc))
            continue
        print("# @%s, %s" % (p["author"], p["posted"]))
        for line in p["text"].split("\n"):
            print("#   %s" % line)
        for l in p["links"]:
            print("#   link: %s" % l)
        print(as_yaml(p))
        print()
