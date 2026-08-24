# PhD Intern Board

<a href="https://paypal.me/JunyeobBaek"><img src="https://img.shields.io/badge/Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black" height="35"></a>

Research internships, fellowships, student researcher roles, AI residencies and predoctoral
positions at AI labs, big tech and startups — collected every day, with only the new ones flagged.

**→ [dion-jy.github.io/phd-intern-board](https://dion-jy.github.io/phd-intern-board/)**

Built because the existing aggregators are dominated by software engineering internships,
and the one list that was actually research-focused
([`frankaging/awesome-ai-research-intern-list`](https://github.com/frankaging/awesome-ai-research-intern-list))
has been dead since 2024. Research postings also tend to close within days of appearing,
which makes checking 70+ career pages by hand unsustainable.

## How it works

No HTML scraping. Every source is a public JSON endpoint that needs no authentication,
which means there is no layout to break and no robots.txt to worry about.

| Source | Endpoint | Role |
|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true` | precision |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{slug}` | precision |
| Lever | `api.lever.co/v0/postings/{slug}?mode=json` | precision |
| SimplifyJobs | `raw.githubusercontent.com/SimplifyJobs/Summer{season}-Internships/dev/.github/scripts/listings.json` | coverage |

Listings are categorised on the site by **kind of organisation** — frontier lab, big tech,
startup, infra & chips, research org — because that is what a reader actually filters on.

Separately, each listing carries a `kind` recording how it was collected. That matters for
judging what might be *missing*, not for reading any single listing, so it appears only as a
footnote on the card:

| Kind | Where it comes from | What it is for |
|---|---|---|
| `tracked` | the three ATS APIs | the 76 hand-picked labs in `labs.yaml`. Their whole board is read daily, so for these an empty result really does mean nothing is open |
| `blindspot` | SimplifyJobs | big tech that has no public API at all |
| `discovery` | SimplifyJobs | companies not among the 76 in `labs.yaml` — nobody thought to list them |
| `evergreen` | the three ATS APIs | standing applications at tracked labs, open with no deadline |
| `manual` | `manual.yaml` | labs that only announce on X or their own site; each listing is labelled by its actual origin — X post, Lab website, Mailing list, Referral |

## Two traps in slug verification

**1 — Never decide a board exists by counting items.** Lever's failure response is
`{"ok": false, "error": "Document not found"}`. That is a dict, so `len()` returns 2, and a
naive check reports two openings for a company that has no board. `mistral-ai`, `together-ai`,
`cohere` and `adept` were all recorded as live that way before it was caught. `probe_slugs.py`
decides on response *shape* instead: Lever must return a list, Greenhouse a dict with a `jobs`
array, and Ashby anything other than the plain text `Not Found`.

**2 — A slug can respond correctly and belong to somebody else.** Caught by `verify_identity.py`,
which checks the owning company name rather than just the payload:

| Slug | Actually | Correct answer |
|---|---|---|
| `greenhouse/figure` | Figure Lending, a fintech | `greenhouse/figureai` |
| `ashby/runway` | cfo.ai | Runway ML has no public board |
| `greenhouse/cais` | CAIS, an investments platform | not the Center for AI Safety |
| `lever/sesame` | a healthcare company | `ashby/sesame` |

Without this second pass, three companies would have quietly pushed unrelated postings
into the feed every morning.

**Slugs cannot be guessed.** OpenAI is not on Greenhouse but is on Ashby. AI2's slug turned out
to be `thealleninstitute` after seven reasonable guesses — `allenai`, `ai2`, `alleninstitute`
and others — all failed. It was found by grepping the careers page HTML, which is the reliable
method.

## Why the filter looks the way it does

Everything below is a rule that exists because something specific went wrong.

- **Word boundaries are mandatory.** A substring search for `intern` also matches
  `Internal Controls`, `International Tax` and `Internal Communications`.
- **Structured signals beat regex.** Ashby exposes `employmentType: "Intern"` and Lever exposes
  `categories.commitment: "Intern"`. Both are used ahead of any title matching.
- **Anthropic never uses the word "intern".** Of 518 openings, the research-internship
  equivalent is the `Anthropic Fellows Program` — 4 roles, none of which contain `intern`. The
  keyword list therefore has to include *Fellows*, *Residency*, *Scholar* and
  *Visiting Researcher*.
- **AI2 does not use it either.** Its pre-PhD position is called
  `Predoctoral Young Investigator`, matching neither `intern` nor `fellowship`.
- **A named programme form is a signal on its own.** A fellowship, residency or scholarship *is*
  the research-track role, so requiring a separate word like "research" alongside it drops real
  openings — Scale AI's `STEM Fellow` and `SWE Fellow`, Tenstorrent's `CPU Verification Fellow`.
  These are kept at `medium` because nothing in the title confirms the subject area, and the
  blocklist still removes Scale AI's Finance Fellow and Legal Fellow.
- **`residency` is never matched alone.** On its own it hits *data residency* in infrastructure
  job descriptions. It always requires a qualifier.
- **"PhD appears near research" is far too weak a body-text rule.** Etched's chip internships say
  `Bachelor's, Master's, or PhD degree in electrical engineering` and carry the boilerplate
  `we do not have boundaries between engineering and research`. Both signals are incidental, and
  nine hardware roles came through. The rule now requires a phrase that names a research
  position, which cut Etched from 10 matches to 1.
- **Discovery rows get filtered twice.** Simplify's own `AI/ML/Data` category still admits
  `Capital Markets Intern - Quantitative Strategies`, so discovery titles also go through the
  ATS filter — 127 down to 92. Without the category gate first, quant trading and defence
  dominate: of ~400 active PhD listings, ~50 are categorised Quant outright, and Citadel, DRW,
  Optiver, Tower Research and L3Harris post plenty more under Software and Hardware.
- **Blind-spot rows skip that second pass**, because NVIDIA files genuine research roles under
  Hardware and those labs are already trusted.

### Always-open applications

Small research labs frequently post no internship at all and hire through a standing
"general application" or "expression of interest" instead — which makes that channel the only
real way in at precisely the labs this board exists to cover. Those carry no internship signal
and no date worth trusting, so they are collected as their own kind rather than mixed into the
dated postings: no relative date is shown, and they are tagged `no deadline`.

11 are currently live, including Anthropic's `[Expression of Interest] Research Engineer /
Scientist`, plus standing applications at Goodfire, METR, Epoch AI, Reflection AI, Prime Intellect
and Cognition. Channels that cannot lead to a research role are filtered out — Apollo Research's
finance associate opening, Scale AI's hackathon interest form and Goodfire's senior-leadership
form are all dropped.

Each listing carries a `confidence`:

- `high` — the title alone settles it (`Research Intern`, `Anthropic Fellows Program`)
- `medium` — an internship signal plus a research signal, but not conclusive. Kept and tagged
  rather than dropped, so the site can filter it out.

## Openings that never reach a job board

The one gap automated collection cannot close: labs that announce an internship in an X post, a
mailing list or a line on their own site, and never file it anywhere machine-readable. Sakana AI
and AMI Labs are the usual examples. Every automated route into X is shut — the v2 API needs a
paid tier to search, the syndication endpoint rate-limits immediately, and Nitter is dead — so
these are listed directly and trusted without filtering.

Append to [`manual.yaml`](manual.yaml). Only `company`, `title` and `url` are required:

```yaml
openings:
  - company: Sakana AI
    title: Research Intern, 2027
    url: https://x.com/SakanaAILabs/status/1234567890
    via: x                # x | email | referral | lab-page | conference | other
    tier: frontier        # frontier | research-org | bigtech | startup | infra
    posted: 2026-08-20    # when it was announced, not when you added it
    location: Tokyo, Japan
    phd: true
    deadline: 2026-09-30
    note: Apply by DM; mentioned in a thread reply.
```

A malformed entry is skipped with a message rather than failing the run, so a typo cannot break
the daily collection. `note` and `deadline` are worth filling in — an X post often carries the
only application instructions there are, and the post itself may be deleted later.

There is **no automatic expiry**: delete an entry once it closes.

## Static JSON API

| Path | Contents |
|---|---|
| `api/jobs.json` | matched postings from tracked labs |
| `api/discover.json` | secondary-source postings, split into `blindspot` and `discovery` |
| `api/new.json` | **only what appeared since the previous run**, across both sources |
| `api/evergreen.json` | standing applications with no deadline |
| `api/manual.json` | openings not on any job board |
| `api/logos.json` | company favicons as data URIs, one per company |
| `api/labs.json` | the full catalogue, including the 34 unresolved entries |
| `api/status.json` | labs and postings scanned, match counts, and any boards that failed |

Listing schema:

```json
{
  "company": "Waabi", "tier": "startup", "ats": "lever",
  "source": "ats", "kind": "tracked",
  "title": "2026 Intern, PhD Research Scientist",
  "location": "Toronto", "url": "https://jobs.lever.co/waabi/...",
  "posted_at": "2026-08-19T...", "department": "Internships / Co-ops",
  "confidence": "high", "match": ["ats-intern-flag", "title-strong"],
  "phd": true, "job_id": "lever:waabi:62700386-..."
}
```

## What this cannot see

- **Small research labs post nothing at all.** Sakana AI, AMI Labs and similar hire through X,
  faculty referrals and personal email. They are outside the reach of any automated collector and
  have to be tracked by following people.
- **Big tech is only partially covered.** Meta, Apple, Microsoft, Amazon, NVIDIA and ByteDance run
  their own applicant systems. Google DeepMind does have a Greenhouse board, but it holds ~10
  roles while the real Student Researcher postings live on google.com/about/careers. The
  `blindspot` rows fill some of this gap through SimplifyJobs — **they are not exhaustive.**
- **Zero results is not the same as "not hiring".** Research internships are seasonal; on
  2026-08-23, OpenAI had 753 open roles and none of them were internships. That is the reason for
  a daily diff rather than a one-off scrape.
- **Degree requirements, visa sponsorship and start dates** are frequently ambiguous in the
  posting text. Always open the original.

## Files

| File | Role |
|---|---|
| `labs.yaml` | the catalogue — 82 confirmed boards plus 33 recorded dead ends |
| `probe_slugs.py` | probe candidate slugs across the three ATS APIs |
| `verify_identity.py` | confirm a responding board belongs to the right company |
| `build_labs.py` | rebuild `labs.yaml`, taking job counts from the probe results |
| `collect.py` | fetch, normalise, filter, diff → `api/*.json` |
| `simplify_source.py` | the secondary source and its classification rules |
| `manual_source.py` | reads and validates `manual.yaml` |
| `logo_source.py` | fetches and caches company favicons |
| `x_source.py` | reads the X posts listed in `xposts.yaml` |
| `manual.yaml` | **openings not on any job board — the one file you edit yourself** |
| `build_site.py` | `api/*.json` → `data.js` plus pre-rendered rows in `index.html` |
| `index.html` | the site — filter by source, tier, company, confidence, PhD and new |
| `sitemap.xml`, `robots.txt` | generated by `build_site.py` alongside the page |

## Running it

```bash
pip install requests pyyaml
python collect.py       # -> api/*.json
python build_site.py    # -> data.js, index.html
python -m http.server   # then open http://localhost:8000
```

`.github/workflows/daily.yml` runs both scripts at 01:00 UTC (10:00 KST) and commits only when
something actually changed.

## Notifications

**This repository sends nothing.** A separate agent reads `api/new.json` on a schedule and
composes the briefing. Note the `first_run` flag: on a cold start every listing counts as new,
and a briefing should suppress that case.
