#!/usr/bin/env python3
"""Fetch, normalise, filter and diff — the daily job.

Two sources with different jobs to do:

    ATS APIs   precision. Every lab in labs.yaml, checked directly at the source.
    Simplify   coverage. Fills the big-tech blind spot and finds companies we
               never listed. See simplify_source.py.

Output is four static JSON files under api/ plus a seen-set under data/, so the
diff survives between GitHub Actions runs.
"""
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests
import yaml

import logo_source
import manual_source
import simplify_source
import x_source

UA = {"User-Agent": "Mozilla/5.0 (compatible; PhDInternBoard/0.1; +https://github.com/dion-jy/phd-intern-board)"}
TIMEOUT = 40
NOW = datetime.now(timezone.utc).isoformat()

# --- matching ------------------------------------------------------------
# Titles that are unambiguously a research internship on their own.
STRONG = re.compile(r"""
 research\s+(intern|internship|scientist\s+intern|engineer\s+intern|co-?op|resident|residency)
|(intern|internship)[^a-z]{0,12}(phd|ph\.d)
|(phd|ph\.d)[^a-z]{0,20}(intern|internship)
|student\s+research(er)?
|(ai|ml|research)\s+residency
|residency\s+program
|fellows?\s+program
|fellowship
|visiting\s+(researcher|scientist|scholar)
|doctoral\s+(intern|researcher)
|summer\s+research
|pre-?doctoral
|young\s+investigator
|research\s+(fellow|scholar|assistant|associate\s+intern)
|graduate\s+research(er)?
|post-?\s?doc(toral)?
""", re.I | re.X)

# Named early-career programmes. A fellowship, residency or scholarship IS the
# research-track role — there is no separate word like "research" to look for, so
# requiring one drops real openings: Scale AI's "STEM Fellow" and "SWE Fellow",
# Tenstorrent's "CPU Verification Fellow". BLOCK still applies, which is what keeps
# out Scale AI's Finance Fellow and Legal Fellow.
PROGRAM_FORM = re.compile(
    r"\b(fellow|fellows|fellowship|fellowships|residency|resident|scholar|scholarship)\b", re.I)

# Korean and Japanese titles. Added 2026-08-26 with the Seoul and Tokyo boards:
# LG AI Research posts "NLP 연구인턴" and "NLP 개발인턴" with no English anywhere in
# the title, and the English-only patterns dropped both. Word boundaries are
# deliberately absent -- \b does not fire between CJK characters -- and that is safe
# here because these are content words, not the substring trap that "Internal" and
# "International" spring on the English side.
# Non-research roles that carry an intern word. Mirrors the English BLOCK list.
BLOCK_CJK = re.compile(
    "영업|마케팅|인사|재무|회계|법무|총무|채용|홍보|디자인|번역|통역"
    "|営業|マーケティング|人事|経理|法務|採用|広報|翻訳", re.U)

# Word-boundary matching is mandatory here. A substring search for "intern" also
# matches "Internal Controls", "International Tax" and "Internal Communications".
INTERN = re.compile(
    r"\b(intern|interns|internship|internships|co-?op|residency|resident|fellow|fellows|fellowship)\b",
    re.I)

RESEARCH = re.compile(r"""\b(
 research|researcher|scientist|scientific|machine\s+learning|ml|deep\s+learning|ai|
 artificial\s+intelligence|nlp|computer\s+vision|robotics|reinforcement\s+learning|rl|
 foundation\s+model|llm|perception|generative|algorithms?|inference|pre-?training|post-?training|
 speech|audio|vision|language\s+model|autonom\w*|diffusion
)\b""", re.I | re.X)

# Non-research roles that would otherwise match on "AI" or "research" alone.
BLOCK = re.compile(
    r"\b(tutor|annotator|annotation|recruit|recruiter|sourcer|sales|account\s+executive|"
    r"marketing|legal|finance|accounting|talent|gtm|people\s+ops)\b", re.I)

PHD = re.compile(r"\b(ph\.?\s?d|doctoral|doctorate)\b", re.I)

# Always-open application channels. Small research labs frequently post no
# internship at all and hire through a standing "general application" or
# "expression of interest" instead, which makes these the only real entry point
# for exactly the labs this board exists to cover. They carry no internship
# signal and no date worth trusting, so they are collected as their own kind
# rather than mixed into the dated postings.
EVERGREEN = re.compile(r"""
 general\s+(application|interest|inquiry|submission)
|open\s+application|spontaneous\s+application|speculative\s+application
|expression\s+of\s+interest
|future\s+(opportunit|role|opening)
|talent\s+(pool|network|community|pipeline)
|don'?t\s+see\s+(your|a)\s+role|role\s+not\s+listed
|rolling\s+(basis|admission|application)|year-?round
|^open\s+role
""", re.I | re.X)

# An always-open channel is only useful here if it can plausibly lead to a
# research role. These are the ones that cannot.
EVERGREEN_BLOCK = re.compile(
    r"\b(finance|accounting|legal|sales|marketing|recruit\w*|hackathon|"
    r"leadership|manager|director|associate|operations|assistant)\b", re.I)

# Body-text rescue for a title too plain to judge. "PhD and research both appear
# somewhere in the description" is far too weak a test: Etched's chip internships
# say "Bachelor's, Master's, or PhD degree in electrical engineering" and carry the
# boilerplate "we do not have boundaries between engineering and research", which
# pulled in nine hardware roles. So require a phrase that names a research position.
# Note "residency" is only ever matched with a qualifier — on its own it hits
# "data residency" in infrastructure job descriptions.
RESEARCH_ROLE = re.compile(r"""
 research\s+(intern|internship|scientist|engineer|project|resident|residency|fellow)
|student\s+research(er)?
|(ai|ml|machine\s+learning|research)\s+residency
|publish(ing|ed)?\s+(a\s+)?(paper|research)|publications?\s+(at|in)\s
|(currently\s+)?(enrolled\s+in|pursuing|working\s+towards)\s+(a\s+)?ph\.?\s?d
|ph\.?\s?d\s+(student|candidate)
""", re.I | re.X)


# The audience is international PhD applicants, so a posting has to be one they can
# actually read. Judging that by the title alone is not enough and the data says so:
# LG AI Research posts "Research Internship - Physical AI" with a title that is 100%
# Latin and a body that is 66% Korean. The requirements, the eligibility and the
# application instructions all live in the body, so the body is what decides.
CJK_CHARS = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")
LATIN_CHARS = re.compile(r"[A-Za-z]")


def cjk_ratio(text):
    """Share of letters that are CJK. 0.0 for pure English, ~0.6 for a Korean JD."""
    if not text:
        return 0.0
    c = len(CJK_CHARS.findall(text))
    l = len(LATIN_CHARS.findall(text))
    return c / (c + l) if (c + l) else 0.0


# A Korean or Japanese company name, a city, a team label in the original script --
# all normal inside an otherwise English posting. A body written in Korean is not.
TITLE_MAX_CJK = 0.30
BODY_MAX_CJK = 0.20

# One ratio over the whole body is not enough, because nearly every posting opens
# with an English "about the company" blurb and that blurb dilutes what follows.
# FuriosaAI's research internship scores 0.33 overall, which reads as bilingual, but
# reading it shows the English is entirely boilerplate: Research Focus, Minimum
# Qualifications and Preferred Qualifications are Korean, with English surviving only
# as embedded technical nouns (LLM, PyTorch, post-training). A longer blurb would
# have pushed that same posting under the threshold. So segments are counted as well:
# if a third of the sentences are CJK, the parts that decide eligibility are CJK.
SEGMENT_MAX_CJK_SHARE = 0.30
SEGMENT_IS_CJK = 0.25


def cjk_segment_share(desc):
    """Share of sentence-length segments that are CJK-dominant. Short fragments are
    skipped: a stray address or a team name in the original script is not evidence."""
    segs = [s for s in re.split(r"[.!?\n\u3002\uff01\uff1f]+", desc) if len(s.strip()) >= 25]
    if not segs:
        return 0.0
    return sum(1 for s in segs if cjk_ratio(s) > SEGMENT_IS_CJK) / len(segs)


def english_enough(title, desc):
    body = desc[:6000]
    return (cjk_ratio(title) <= TITLE_MAX_CJK
            and cjk_ratio(body) <= BODY_MAX_CJK
            and cjk_segment_share(body) <= SEGMENT_MAX_CJK_SHARE)


# Region, derived from the location string. Two things the first attempt got wrong
# and that the data caught immediately:
#
#   "Cambridge, MA"        -> UK      because a bare city name is not a country
#   "Pensacola, FL, Vienna, VA" -> Europe   same reason, Vienna is also in Virginia
#
# So ambiguous cities are matched only with their country attached, and anything
# that stays ambiguous is left to the state-abbreviation rules. The second fix is
# that a listing gets a *list* of regions, not one: "London, UK, Santa Clara, CA"
# is genuinely both, and collapsing it to whichever rule ran first hid the role
# from one of the two filters that should have shown it.
REGION_RULES = [
    ("Asia", r"seoul|korea|tokyo|osaka|kyoto|japan|taipei|taiwan|singapore|beijing|"
             r"shanghai|shenzhen|hangzhou|china|hong kong|bangalore|bengaluru|hyderabad|"
             r"mumbai|new delhi|india|jakarta|indonesia|manila|philippines|bangkok|"
             r"thailand|kuala lumpur|malaysia|vietnam|hanoi|tel aviv|israel"),
    ("UK", r"united kingdom|\buk\b|\bu\.k\.|england|scotland|\bwales\b|"
           r"\blondon\b|edinburgh|glasgow|manchester|bristol|\boxford\b|"
           r"cambridge,?\s*(uk|united kingdom|england)"),
    ("Europe", r"\bfrance\b|germany|deutschland|netherlands|switzerland|\bsweden\b|"
               r"denmark|norway|finland|ireland|\bspain\b|portugal|\bitaly\b|poland|"
               r"czech|austria|belgium|greece|romania|hungary|estonia|serbia|croatia|"
               r"bulgaria|slovakia|slovenia|lithuania|latvia|luxembourg|iceland|"
               r"\beurope\b|\bemea\b|"
               r"\bparis\b|\bberlin\b|munich|m\u00fcnchen|hamburg|cologne|frankfurt|"
               r"stuttgart|freiburg|amsterdam|rotterdam|eindhoven|\bzurich\b|z\u00fcrich|"
               r"geneva|lausanne|basel|stockholm|gothenburg|copenhagen|\boslo\b|"
               r"helsinki|\bdublin\b|\bmadrid\b|barcelona|lisbon|\bmilan\b|\bturin\b|"
               r"warsaw|krakow|\bprague\b|brussels|belgrade|tallinn|vilnius|"
               r"vienna,?\s*austria|\bwien\b|athens,?\s*greece|rome,?\s*italy"),
    ("Canada", r"\bcanada\b|toronto|vancouver|montr[e\u00e9]al|ottawa|waterloo|calgary|"
               r"edmonton|\bquebec|winnipeg|halifax"),
    ("US", r"united states|\busa\b|\bu\.s\.|\bus\b|california|new york|\bnyc\b|"
           r"seattle|boston|texas|austin|chicago|denver|atlanta|miami|"
           r"ann arbor|pittsburgh|philadelphia|baltimore|\bberkeley\b|"
           r"san francisco|\bsf\b|palo alto|mountain view|sunnyvale|santa clara|"
           r"san jose|menlo park|cupertino|redmond|bellevue|los angeles|san diego|"
           r"\bca\b|\bny\b|\bwa\b|\bma\b|\btx\b|\bil\b|\bco\b|\bga\b|\bfl\b|\bmi\b|"
           r"\bpa\b|\bva\b|\bnc\b|\baz\b|\bor\b|\but\b|\bmn\b|\bwi\b|\boh\b|\bmd\b|"
           r"\bnj\b|\bct\b|\bmo\b|\btn\b|\bin\b|\bnv\b|\bks\b|\bia\b|\bal\b|\bsc\b"),
]
REGION_RULES = [(name, re.compile(pat, re.I)) for name, pat in REGION_RULES]
REMOTE = re.compile(r"\bremote\b|\banywhere\b|work from home|\bhybrid\b", re.I)


def regions_of(location):
    """Every region a listing is open in, most-specific rule order preserved.

    Returns a list because a multi-site posting belongs in more than one filter.
    Remote is additive rather than exclusive -- "Remote - London" is both.
    """
    loc = (location or "").strip()
    if not loc:
        return ["Unspecified"]
    out = [name for name, pat in REGION_RULES if pat.search(loc)]
    if REMOTE.search(loc):
        out.append("Remote")
    return out or ["Other"]


def classify(title, desc, employment_type, commitment, department):
    """Return (keep, confidence, reasons).

    Structured signals come first: Ashby exposes employmentType and Lever exposes
    categories.commitment, both of which say "Intern" outright. That beats any
    regex over the title. Greenhouse has no equivalent field.
    """
    reasons = []
    if BLOCK.search(title) or BLOCK_CJK.search(title):
        return False, None, ["blocked"]
    if not english_enough(title, desc or ""):
        return False, None, ["not-english"]

    structured = (employment_type or "").lower() == "intern" \
        or (commitment or "").lower() in ("intern", "internship")
    if structured:
        reasons.append("ats-intern-flag")

    if STRONG.search(title):
        reasons.append("title-strong")
        return True, "high", reasons

    has_intern = structured or bool(INTERN.search(title)) \
        or "intern" in (department or "").lower()
    if not has_intern:
        return False, None, reasons

    if RESEARCH.search(title):
        reasons.append("title-research")
        return True, "high" if structured else "medium", reasons

    # A named programme form carries the research track on its own. Kept at medium
    # because nothing in the title confirms the subject area.
    if PROGRAM_FORM.search(title):
        reasons.append("program-form")
        return True, "medium", reasons

    if desc and RESEARCH_ROLE.search(desc):
        reasons.append("body-research-role")
        return True, "medium", reasons

    return False, None, reasons


# --- one parser per ATS --------------------------------------------------
def strip_html(s):
    return re.sub(r"<[^>]+>", " ", html.unescape(s or "")).replace("\xa0", " ")


def fetch_greenhouse(lab):
    url = "https://boards-api.greenhouse.io/v1/boards/%s/jobs?content=true" % lab["slug"]
    body = requests.get(url, headers=UA, timeout=TIMEOUT).json()
    if not isinstance(body, dict) or not isinstance(body.get("jobs"), list):
        raise ValueError("bad shape: %s" % str(body)[:80])
    return [{
        "job_id": "greenhouse:%s:%s" % (lab["slug"], j["id"]),
        "title": (j.get("title") or "").strip(),
        "location": (j.get("location") or {}).get("name", ""),
        "url": j.get("absolute_url", ""),
        "posted_at": j.get("first_published") or j.get("updated_at"),
        "desc": strip_html(j.get("content", ""))[:6000],
        "department": ", ".join(d.get("name", "") for d in (j.get("departments") or [])),
        "employment_type": None,
        "commitment": None,
    } for j in body["jobs"]]


def fetch_ashby(lab):
    url = "https://api.ashbyhq.com/posting-api/job-board/%s" % lab["slug"]
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    if not r.text.strip().startswith("{"):
        raise ValueError("Not Found")
    body = r.json()
    if not isinstance(body.get("jobs"), list):
        raise ValueError("bad shape: %s" % str(body)[:80])
    return [{
        "job_id": "ashby:%s:%s" % (lab["slug"], j["id"]),
        "title": (j.get("title") or "").strip(),
        "location": j.get("location") or "",
        "url": j.get("jobUrl") or j.get("applyUrl", ""),
        "posted_at": j.get("publishedAt"),
        "desc": (j.get("descriptionPlain") or "")[:6000],
        "department": j.get("department") or j.get("team") or "",
        "employment_type": j.get("employmentType"),
        "commitment": None,
    } for j in body["jobs"] if j.get("isListed") is not False]


def fetch_lever(lab):
    url = "https://api.lever.co/v0/postings/%s?mode=json" % lab["slug"]
    body = requests.get(url, headers=UA, timeout=TIMEOUT).json()
    # A dict here is the failure envelope, not an empty board. Never count length.
    if not isinstance(body, list):
        raise ValueError("not a list: %s" % str(body)[:80])
    out = []
    for j in body:
        cat = j.get("categories") or {}
        created = j.get("createdAt")
        out.append({
            "job_id": "lever:%s:%s" % (lab["slug"], j["id"]),
            "title": (j.get("text") or "").strip(),
            "location": cat.get("location") or "",
            "url": j.get("hostedUrl") or j.get("applyUrl", ""),
            "posted_at": datetime.fromtimestamp(created / 1000, timezone.utc).isoformat()
                         if created else None,
            "desc": (j.get("descriptionPlain") or "")[:6000],
            "department": cat.get("department") or "",
            "employment_type": None,
            "commitment": cat.get("commitment"),
        })
    return out


FETCH = {"greenhouse": fetch_greenhouse, "ashby": fetch_ashby, "lever": fetch_lever}


def fetch_one(lab):
    try:
        return lab, FETCH[lab["ats"]](lab), None
    except Exception as exc:
        return lab, None, "%s: %s" % (type(exc).__name__, exc)


def main():
    catalog = yaml.safe_load(open("labs.yaml"))["labs"]
    labs = [l for l in catalog if l.get("active")]

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(fetch_one, labs))

    matched, evergreen, errors, scanned = [], [], [], 0
    # Per-lab tally. Without it a lab that quietly stops returning postings looks
    # identical to a lab that simply has no internship open right now, and the only
    # visible symptom is a smaller total that nobody can attribute.
    by_lab = []
    for lab, jobs, err in results:
        if err:
            errors.append({"lab": lab["name"], "ats": lab["ats"],
                           "slug": lab["slug"], "error": err})
            by_lab.append({"lab": lab["name"], "ats": lab["ats"], "slug": lab["slug"],
                           "postings": None, "matched": 0, "evergreen": 0, "error": err})
            continue
        scanned += len(jobs)
        before_m, before_e = len(matched), len(evergreen)
        for j in jobs:
            if EVERGREEN.search(j["title"]) and not EVERGREEN_BLOCK.search(j["title"]) \
                    and english_enough(j["title"], j.get("desc") or ""):
                evergreen.append({
                    "company": lab["name"], "tier": lab["tier"], "ats": lab["ats"],
                    "domain": lab.get("domain", ""),
                    "source": "ats", "kind": "evergreen",
                    "title": j["title"], "location": j["location"], "url": j["url"],
                    "posted_at": j["posted_at"], "department": j["department"],
                    "confidence": "evergreen", "match": ["always-open"],
                    "phd": bool(PHD.search(j["title"] + " " + j["desc"][:3000])),
                    "job_id": j["job_id"],
                })
                continue
            keep, confidence, reasons = classify(
                j["title"], j["desc"], j["employment_type"], j["commitment"], j["department"])
            if not keep:
                continue
            matched.append({
                "company": lab["name"], "tier": lab["tier"], "ats": lab["ats"],
                    "domain": lab.get("domain", ""),
                "source": "ats", "kind": "tracked",
                "title": j["title"], "location": j["location"], "url": j["url"],
                "posted_at": j["posted_at"], "department": j["department"],
                "confidence": confidence, "match": reasons,
                "phd": bool(PHD.search(j["title"] + " " + j["desc"][:3000])),
                "job_id": j["job_id"],
            })
        by_lab.append({"lab": lab["name"], "ats": lab["ats"], "slug": lab["slug"],
                       "postings": len(jobs), "matched": len(matched) - before_m,
                       "evergreen": len(evergreen) - before_e, "error": None})

    by_lab.sort(key=lambda r: (-(r["matched"] + r["evergreen"]), -(r["postings"] or 0)))
    # A lab whose board answered but yielded nothing. Expected for most of them most
    # of the year, so this is a list to read rather than an alarm to fire -- but a big
    # lab appearing here for weeks is the signal that its interns are posted elsewhere.
    silent = [r["lab"] for r in by_lab
              if r["error"] is None and r["postings"] and not r["matched"] and not r["evergreen"]]

    matched.sort(key=lambda x: (x["posted_at"] or "", x["company"]), reverse=True)
    evergreen.sort(key=lambda x: (x["tier"], x["company"]))

    # --- openings that never reach a job board ----------------------------
    # The structural gap this board cannot close on its own: labs that announce
    # an internship in an X post or a mailing list and never file it anywhere
    # machine-readable. Automated collection has no route to those, so a person
    # adds them and they are trusted as-is.
    try:
        manual = manual_source.load()
    except Exception as exc:
        manual = []
        errors.append({"lab": "manual.yaml", "ats": "manual", "slug": "-",
                       "error": "%s: %s" % (type(exc).__name__, exc)})

    # --- X announcements shown as a strip, not as board listings ----------
    try:
        xposts, xstats = x_source.load_feed()
    except Exception as exc:
        xposts, xstats = [], {"error": "%s: %s" % (type(exc).__name__, exc)}

    # --- secondary source ------------------------------------------------
    try:
        discover, simplify_stats = simplify_source.fetch(catalog)
    except Exception as exc:
        discover, simplify_stats = [], {"error": "%s: %s" % (type(exc).__name__, exc)}
        errors.append({"lab": "SimplifyJobs", "ats": "simplify",
                       "slug": "-", "error": str(exc)})

    # An archived feed answers 200 forever with a snapshot that never moves, so
    # surface staleness as loudly as an outright failure.
    if simplify_stats.get("stale"):
        errors.append({"lab": "SimplifyJobs", "ats": "simplify", "slug": "-",
                       "error": "feed looks frozen: newest entry is %s days old (season %s)"
                                % (simplify_stats.get("newest_entry_age_days"),
                                   simplify_stats.get("season"))})

    # Discovery rows come from companies we know nothing about, so put their titles
    # through the same filter used for tracked labs. Simplify's own AI/ML/Data
    # category still lets through things like "Capital Markets Intern - Quantitative
    # Strategies". Blind-spot rows skip this: those are labs we already trust, and
    # their research roles sometimes sit under a Hardware or Software category.
    kept = []
    for d in discover:
        if d["kind"] == "blindspot":
            kept.append(d)
            continue
        keep, confidence, reasons = classify(d["title"], "", "Intern", "Intern", d["department"])
        if keep:
            d["confidence"] = confidence
            d["match"] = d["match"] + reasons
            kept.append(d)
    simplify_stats["discovery_after_title_filter"] = sum(
        1 for d in kept if d["kind"] == "discovery")
    discover = kept
    discover.sort(key=lambda x: (x["posted_at"] or "", x["company"]), reverse=True)

    # --- diff across both sources ----------------------------------------
    try:
        previous = set(json.load(open("data/seen.json"))["job_ids"])
    except (FileNotFoundError, KeyError, ValueError):
        previous = set()
    everything = manual + matched + evergreen + discover
    # Region is attached here rather than in each source, because there are four of
    # them and patching each one is how one of them ends up without the field.
    for j in everything:
        j["regions"] = regions_of(j.get("location"))
    current = {j["job_id"] for j in everything}
    fresh = [j for j in everything if j["job_id"] not in previous]
    first_run = not previous

    # One entry per company, not per listing. Inlining the same base64 favicon on
    # every Anthropic posting bloated the page by ~150KB for no reason; the site
    # references them through a CSS class instead.
    logos = logo_source.collect(everything)

    write("api/logos.json", {"generated_at": NOW, "count": len(logos), "logos": logos})
    write("api/jobs.json", {"generated_at": NOW, "count": len(matched), "jobs": matched})
    write("api/xposts.json", {"generated_at": NOW, "count": len(xposts),
                              "stats": xstats, "posts": xposts})
    write("api/manual.json", {"generated_at": NOW, "count": len(manual),
                              "jobs": manual})
    write("api/evergreen.json", {"generated_at": NOW, "count": len(evergreen),
                                 "jobs": evergreen})
    write("api/discover.json", {
        "generated_at": NOW, "count": len(discover),
        "blindspot": sum(1 for d in discover if d["kind"] == "blindspot"),
        "discovery": sum(1 for d in discover if d["kind"] == "discovery"),
        "stats": simplify_stats, "jobs": discover})
    write("api/new.json", {"generated_at": NOW, "first_run": first_run,
                           "count": len(fresh), "jobs": fresh})
    write("api/labs.json", {
        "generated_at": NOW,
        "active": sum(1 for l in catalog if l.get("active")),
        "excluded": sum(1 for l in catalog if l.get("active") is False),
        "unresolved": sum(1 for l in catalog if l["ats"] == "none"),
        "labs": catalog})
    # Counted by kind, not by which file they came from: a manual.yaml entry marked
    # always_open has kind "evergreen" and the site groups it that way, so the API
    # has to agree with what the page shows.
    by_kind = {}
    for j in everything:
        k = j.get("kind") or "tracked"
        by_kind[k] = by_kind.get(k, 0) + 1

    write("api/status.json", {
        "generated_at": NOW, "scanned_labs": len(labs), "scanned_jobs": scanned,
        "by_kind": by_kind, "total_listings": len(everything),
        "matched": len(matched), "off_board_file": len(manual),
        "evergreen": by_kind.get("evergreen", 0), "xposts": len(xposts),
        "discover": len(discover),
        "simplify": simplify_stats, "new": len(fresh),
        "by_lab": by_lab, "silent_labs": silent, "errors": errors})
    json.dump({"generated_at": NOW, "job_ids": sorted(current)}, open("data/seen.json", "w"))

    highs = sum(1 for m in matched if m["confidence"] == "high")
    print("scanned %d labs / %d postings -> %d matched (%d high, %d medium), %d new%s"
          % (len(labs), scanned, len(matched), highs, len(matched) - highs, len(fresh),
             "  [first run]" if first_run else ""))
    print("logos: %d of %d companies have one"
          % (len(logos), len({j["company"] for j in everything})))
    print("off-board: %d openings not on any job board" % len(manual))
    print("x strip: %d posts  %s" % (len(xposts), xstats))
    print("evergreen: %d always-open application channels" % len(evergreen))
    print("silent: %d of %d tracked labs answered with no research opening"
          % (len(silent), len(labs)))
    print("simplify: %d blind spot / %d discovery  %s"
          % (sum(1 for d in discover if d["kind"] == "blindspot"),
             sum(1 for d in discover if d["kind"] == "discovery"), simplify_stats))
    for e in errors:
        print("  ERROR %s (%s/%s): %s" % (e["lab"], e["ats"], e["slug"], e["error"][:100]))


def write(path, blob):
    json.dump(blob, open(path, "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
