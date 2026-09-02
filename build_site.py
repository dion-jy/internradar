#!/usr/bin/env python3
"""Turn api/*.json into data.js, pre-rendered cards, and the SEO artefacts.

Three reasons this step exists:
  data.js            lets the page work over file://, where fetch() is blocked
  pre-rendered cards let the listings be read without JavaScript (crawlers, no-JS)
  ItemList + sitemap give search engines the listing set and a crawl hint

Deliberately NOT emitted: JobPosting structured data. Google expects that on a
page dedicated to a single posting with its full description; this is a list page
that links out to the originals, so claiming JobPosting here would be wrong.
"""
import html
import json
import re
from datetime import datetime, timezone

SITE = "https://dion-jy.github.io/phd-intern-board/"
# Where a listing came from. Useful for judging what might be missing, so it sits in
# the card footer rather than being colour-coded across the whole page.
TIER_LABEL = {"frontier": "Frontier lab", "research-org": "Research org",
              "bigtech": "Big tech", "startup": "Startup", "infra": "Infra & chips",
              "other": "Other"}

SOURCE_NOTE = {"tracked": "read from the lab", "blindspot": "via aggregator",
               "discovery": "via aggregator", "evergreen": "read from the lab",
               "manual": "added directly"}

jobs = json.load(open("api/jobs.json"))
discover = json.load(open("api/discover.json"))
evergreen = json.load(open("api/evergreen.json"))
manual = json.load(open("api/manual.json"))
xposts = json.load(open("api/xposts.json"))
logos = json.load(open("api/logos.json"))["logos"]
new = json.load(open("api/new.json"))
status = json.load(open("api/status.json"))

with open("data.js", "w") as f:
    for name, blob in (("JOBS_DATA", jobs), ("DISCOVER_DATA", discover),
                       ("NEW_DATA", new), ("STATUS_DATA", status),
                       ("EVERGREEN_DATA", evergreen), ("MANUAL_DATA", manual),
                       ("XPOSTS_DATA", xposts)):
        f.write("window.%s=%s;\n" % (name, json.dumps(blob, ensure_ascii=False)))

new_ids = {j["job_id"] for j in new.get("jobs", [])}
# collect.py decided the order and stamped it; concatenation order is irrelevant here.
listings = manual["jobs"] + jobs["jobs"] + evergreen["jobs"] + discover["jobs"]
listings.sort(key=lambda j: j.get("order", 1 << 30))
e = lambda s: html.escape(str(s or ""))


def where(loc):
    """Card label for a location. Boards report up to four or five places for one
    role; printing them all turns the footer into a paragraph, so the card shows two
    and counts the rest. The listing keeps the full string, which is what the region
    filter and the search box read."""
    parts = [p.strip() for p in str(loc or "").split(";") if p.strip()]
    if not parts:
        return "Location not stated"
    if len(parts) <= 2:
        return ", ".join(parts)
    return "%s +%d more" % (", ".join(parts[:2]), len(parts) - 2)


def posted_ago(iso):
    """Mirror of the client-side relative date, so pre-rendered cards read the
    same as the ones JavaScript draws."""
    if not iso:
        return ""
    try:
        then = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if then.tzinfo is None:          # a reader that emitted a bare date
        then = then.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - then).days
    if days <= 0:
        return "today"
    if days == 1:
        return "1 day ago"
    if days < 30:
        return "%d days ago" % days
    if days < 365:
        return "%d months ago" % (days // 30)
    return "%d years ago" % (days // 365)


def chip(text, cls=""):
    return '<span class="chip%s">%s</span>' % ((" " + cls) if cls else "", e(text))


def logo_class(company):
    return "lg-" + re.sub(r"[^a-z0-9]", "", (company or "").lower())


def mark(j):
    """A real favicon when one was found at build time, otherwise the company
    initial. The image lives in a stylesheet rule so each logo is embedded once
    rather than once per listing, and it is never a remote request."""
    company = j.get("company") or "?"
    if logos.get(company):
        return '<span class="logo %s" aria-hidden="true"></span>' % logo_class(company)
    letters = re.sub(r"[^A-Za-z0-9]", "", company)
    return '<span class="mono" aria-hidden="true">%s</span>' % e((letters[:1] or "?").upper())


def card(j):
    kind = j.get("kind") or "tracked"
    # A no-deadline listing has no meaningful date; "2 years ago" would read as stale.
    when = "" if kind == "evergreen" else posted_ago(j.get("posted_at"))
    top = "".join([
        chip("NEW", "new") if j["job_id"] in new_ids else "",
        chip("PhD") if j.get("phd") else "",
        chip("no deadline") if kind == "evergreen" else "",
        ('<time class="when" datetime="%s">%s</time>' % (e(j.get("posted_at")), e(when)))
        if when else "",
    ])
    foot = "".join([
        '<span class="where">%s</span>' % e(where(j.get("location"))),
        '<span class="tier tier-%s">%s</span>'
        % (e(j.get("tier") or "other"),
           e(TIER_LABEL.get(j.get("tier"), j.get("tier") or "Other"))),
        '<span class="prov">%s</span>'
        % e(j.get("source_label") or SOURCE_NOTE.get(kind, kind)),
    ])
    note = ('<p class="note-line">%s</p>' % e(j["note"])) if j.get("note") else ""
    return ('<li class="job"><div class="top">%s</div><p class="org">%s%s</p>'
            '<a class="role" href="%s" target="_blank" rel="noopener">%s</a>'
            '<div class="foot">%s</div>%s</li>'
            % (top, mark(j), e(j["company"]), e(j["url"]), e(j["title"]), foot, note))


def linkify(text):
    """Escape the post text, then make its t.co links clickable. The text itself is
    never rewritten -- the post is shown exactly as it was written."""
    out = e(text)
    return re.sub(r"https://t\.co/\w+",
                  lambda m: '<a href="%s" target="_blank" rel="noopener">%s</a>'
                            % (m.group(0), m.group(0)), out)


def post_card(p):
    links = p.get("links") or []
    avatar = ('<img src="%s" alt="" width="36" height="36">' % e(p["avatar"])) if p.get("avatar") \
        else '<img alt="" width="36" height="36">'
    return (
        '<article class="post"><div class="post-top">%s'
        '<div class="post-who"><div class="post-name">%s</div>'
        '<div class="post-meta">@%s · %s</div></div></div>'
        '<div class="post-body">%s</div>%s'
        '<div class="post-foot"><a href="%s" target="_blank" rel="noopener">View on X</a>%s</div>'
        "</article>"
    ) % (avatar, e(p.get("author_name") or p.get("author")), e(p.get("author")),
         e(posted_ago(p.get("posted") + "T00:00:00+00:00" if p.get("posted") else None)),
         linkify(p.get("text")),
         ('<div class="post-links">%s</div>' % "".join(
             '<a class="post-link" href="%s" target="_blank" rel="noopener">%s</a>'
             % (e(l), e(re.sub(r"^https?://", "", l)[:46])) for l in links)) if links else "",
         e(p.get("post_url")),
         ("<span>%s</span>" % e(p["note"])) if p.get("note") else "")


item_list = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    "name": "AI research internship openings",
    "numberOfItems": len(listings),
    "itemListOrder": "https://schema.org/ItemListOrderDescending",
    "itemListElement": [
        {"@type": "ListItem", "position": i + 1,
         "name": "%s — %s" % (j["company"], j["title"]), "url": j["url"]}
        for i, j in enumerate(listings)
    ],
}

src = open("index.html").read()

logo_css = "".join(".%s{background-image:url(%s)}" % (logo_class(c), u)
                   for c, u in sorted(logos.items()) if u)
src = re.sub(r"(/\* LOGO_CSS_START \*/).*?(/\* LOGO_CSS_END \*/)",
             lambda m: m.group(1) + logo_css + m.group(2), src, flags=re.S)
src = re.sub(r"(<!-- STATIC_ROWS_START -->).*?(<!-- STATIC_ROWS_END -->)",
             lambda m: m.group(1) + "\n" + "\n".join(card(j) for j in listings) + "\n" + m.group(2),
             src, flags=re.S)
if xposts.get("posts"):
    src = src.replace('<section class="feed" id="feed" hidden',
                      '<section class="feed" id="feed"', 1)
    src = re.sub(r"(<!-- XPOSTS_START -->).*?(<!-- XPOSTS_END -->)",
                 lambda m: m.group(1) + "\n" + "\n".join(post_card(p) for p in xposts["posts"])
                           + "\n" + m.group(2), src, flags=re.S)
    src = re.sub(r'(<span class="count" id="feedCount">)[^<]*(</span>)',
                 lambda m: m.group(1) + "%d post%s" % (len(xposts["posts"]),
                                                        "s" if len(xposts["posts"]) > 1 else "")
                           + m.group(2), src, count=1)

src = re.sub(r"(<!-- ITEMLIST_START -->).*?(<!-- ITEMLIST_END -->)",
             lambda m: m.group(1) + '\n<script type="application/ld+json">'
                       + json.dumps(item_list, ensure_ascii=False) + "</script>\n" + m.group(2),
             src, flags=re.S)

desc = ("%d AI research internships open right now — research intern, student researcher, PhD "
        "intern and AI residency roles at %d labs, big tech and startups. Updated daily."
        % (len(listings), status["scanned_labs"]))
src = re.sub(r'(<meta name="description" content=")[^"]*(")',
             lambda m: m.group(1) + html.escape(desc) + m.group(2), src)
src = re.sub(r'(<meta property="og:description" content=")[^"]*(")',
             lambda m: m.group(1) + html.escape(desc) + m.group(2), src)
open("index.html", "w").write(src)

# --- feed.xml ----------------------------------------------------------------
# Atom rather than a mailing list, and first rather than instead.
#
# A static site cannot collect an address or send a message -- there is no server to
# do either. A feed needs neither: it costs one file, asks nobody for consent, stores
# nothing about anybody, and every mailing-list service worth using (Buttondown,
# Mailchimp, MailerLite) can read a feed and send from it. So this is the piece that
# has to exist before email is even a question, and it is useful on its own to anyone
# who reads feeds.
#
# <updated> tracks the newest listing, not the run clock, for the same reason the
# sitemap does: a timestamp that changes every run makes every run look like news.
feed_items = [j for j in listings if j.get("posted_at")]
feed_items.sort(key=lambda j: str(j.get("posted_at")), reverse=True)
feed_items = feed_items[:60]
feed_updated = (str(feed_items[0]["posted_at"]) if feed_items
                else datetime.now(timezone.utc).isoformat())


def atom_entry(j):
    loc = where(j.get("location"))
    tier = TIER_LABEL.get(j.get("tier"), j.get("tier") or "")
    bits = [x for x in (loc, tier, "PhD" if j.get("phd") else "") if x]
    return (
        "  <entry>\n"
        "    <title>%s &#8212; %s</title>\n"
        "    <link rel=\"alternate\" href=\"%s\"/>\n"
        "    <id>urn:phd-intern-board:%s</id>\n"
        "    <updated>%s</updated>\n"
        "    <summary>%s</summary>\n"
        "  </entry>\n"
    ) % (e(j.get("company")), e(j.get("title")), e(j.get("url")),
         e(j.get("job_id")), e(j.get("posted_at")), e(" \u00b7 ".join(bits)))


open("feed.xml", "w").write(
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<feed xmlns="http://www.w3.org/2005/Atom">\n'
    "  <title>PhD Intern Board</title>\n"
    "  <subtitle>AI research internships, updated every day</subtitle>\n"
    '  <link rel="alternate" href="%s"/>\n'
    '  <link rel="self" href="%sfeed.xml"/>\n'
    "  <id>%s</id>\n"
    "  <updated>%s</updated>\n"
    "%s"
    "</feed>\n"
    % (SITE, SITE, SITE, feed_updated, "".join(atom_entry(j) for j in feed_items)))
print("wrote feed.xml, %d entries, updated %s" % (len(feed_items), feed_updated[:10]))

# sitemap.xml and robots.txt are generated here and are on the workflow's commit
# list, so what gets published always matches what was built.
#
# <lastmod> deliberately tracks the newest listing rather than today's date. Using
# the run date would rewrite this file on every run, which would make the "commit
# only if something changed" check fire every single day and bury real updates in
# daily no-op commits. The newest posting date changes only when the content does,
# which is also what lastmod is actually supposed to mean.
newest = max((str(j.get("posted_at") or "")[:10] for j in listings if j.get("posted_at")),
             default=datetime.now(timezone.utc).date().isoformat())

open("sitemap.xml", "w").write(
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    "  <url><loc>%s</loc><lastmod>%s</lastmod>"
    "<changefreq>daily</changefreq><priority>1.0</priority></url>\n"
    "</urlset>\n" % (SITE, newest))

open("robots.txt", "w").write(
    "User-agent: *\nAllow: /\n\nSitemap: %ssitemap.xml\n" % SITE)

print("wrote data.js, %d pre-rendered cards, ItemList with %d items, "
      "sitemap lastmod %s" % (len(listings), len(listings), newest))
