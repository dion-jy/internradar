#!/usr/bin/env python3
"""Rank the board against one person's research profile.

The board is deliberately impersonal -- it collects every research internship it can
reach and lets filters do the rest. This does the opposite: it scores listings for a
specific reader so a daily briefing can lead with the handful worth opening.

Profile below is Junyeob's, read off the published work rather than guessed: world
models and JEPA, adaptive computation and halting, OOD generalisation,
interpretability, agents and alignment. Weights also carry the constraints that
actually decide whether a role is reachable -- Asia over Europe over the US, because
of family, and PhD eligibility.

    python brief.py            # everything, ranked
    python brief.py --new      # only what arrived since the last collection
"""
import json
import re
import sys

# Topic weights. Phrases, not bare words: "world model" earns, "model" does not.
TOPICS = [
    (10, r"world model|jepa|video pred|latent dynamic|model-based rl|dreamer"),
    (10, r"adaptive comput|early exit|halting|recurrent depth|test-?time comput|chain-of-thought"),
    (9,  r"out-of-distribution|\bood\b|generali[sz]ation|systematic|composition"),
    (9,  r"interpretab|mechanistic|probing|representation analysis"),
    (8,  r"alignment|ai safety|safety|oversight|scalable oversight|evaluation|red.?team"),
    (8,  r"agentic|\bagents?\b|embodied|planning|long-horizon"),
    (7,  r"reinforcement learning|\brl\b|exploration|open-?ended|curriculum"),
    (6,  r"reasoning|multimodal|vision.language|\bvlm\b|\bllm\b|foundation model"),
    (5,  r"self-supervised|pre-?training|post-?training|architecture"),
    (4,  r"computer vision|perception|3d|geometry|robot"),
]
# Reachability, which for this reader is not a tiebreaker but a real term.
REGION = {"Asia": 12, "UK": 6, "Europe": 6, "Canada": 3, "Remote": 4, "US": 0,
          "Other": 0, "Unspecified": 0}
TIER = {"frontier": 8, "research-org": 7, "bigtech": 4, "startup": 3, "infra": 2, "other": 0}
# Things that look like a match on keywords but are not this person's work.
AWAY = [(-14, r"\bads?\b|advertis|monetiz|e-?commerce|recommendation|search rank|"
              r"trust and safety|fraud|risk control|supply chain"),
        (-10, r"\bqa\b|test dev|verification|physical design|\bvlsi\b|\bdft\b|asic|"
              r"thermal|mechanical|firmware|hardware"),
        (-8,  r"data engineer|business intelligence|analytics|marketing|finance|legal")]

TOPICS = [(w, re.compile(p, re.I)) for w, p in TOPICS]
AWAY = [(w, re.compile(p, re.I)) for w, p in AWAY]


def score(j):
    text = "%s  %s" % (j.get("title") or "", j.get("department") or "")
    pts, why = 0, []
    for w, pat in TOPICS:
        m = pat.search(text)
        if m:
            pts += w
            why.append(m.group(0).lower())
    for w, pat in AWAY:
        m = pat.search(text)
        if m:
            pts += w
            why.append("-" + m.group(0).lower())
    best = max((REGION.get(r, 0) for r in (j.get("regions") or [])), default=0)
    pts += best
    pts += TIER.get(j.get("tier") or "other", 0)
    if j.get("phd"):
        pts += 5
    return pts, why


def load(new_only):
    if new_only:
        return json.load(open("api/new.json"))["jobs"]
    out = []
    for f in ("jobs", "discover", "evergreen", "manual"):
        out += json.load(open("api/%s.json" % f))["jobs"]
    return out


def main():
    rows = load("--new" in sys.argv)
    scored = sorted(((score(j), j) for j in rows), key=lambda x: -x[0][0])
    for (pts, why), j in scored[:25]:
        if pts <= 0:
            break
        print("%3d  %-15s %-9s %-26s %s" % (
            pts, j["company"][:15], ",".join(j.get("regions") or [])[:9],
            (j.get("location") or "")[:26], j["title"][:52]))
        print("     %s%s" % ("phd · " if j.get("phd") else "", ", ".join(why[:5])))


if __name__ == "__main__":
    main()
