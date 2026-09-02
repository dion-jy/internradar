#!/usr/bin/env python3
"""Submit the board's URL to IndexNow.

IndexNow is the only index submission that can be done without owning an account:
Bing, Yandex, Naver and Seznam all read from it, and ownership is proved by hosting
a key file on the site rather than by logging in. Google does not participate, and
its old sitemap ping is gone -- www.google.com/ping now answers 404 and Bing's
answers 410 -- so Google still needs Search Console, by hand.

The key file sits next to index.html rather than at the host root, because the host
root is a different repository. IndexNow allows that, with the restriction that the
key then only authorises URLs at or below its own directory, which is exactly the
one URL this site has.

Run after a change worth re-crawling. It is not in the daily workflow: submitting an
unchanged page every day is what the protocol asks you not to do.
"""
import json
import sys
import urllib.request

KEY = "fac1944da19df06f7f05b44f4eca31ae"
HOST = "dion-jy.github.io"
BASE = "https://dion-jy.github.io/phd-intern-board/"
ENDPOINTS = ["https://api.indexnow.org/indexnow",
             "https://www.bing.com/indexnow",
             "https://yandex.com/indexnow",
             "https://searchadvisor.naver.com/indexnow"]

payload = json.dumps({
    "host": HOST,
    "key": KEY,
    "keyLocation": BASE + KEY + ".txt",
    "urlList": [BASE, BASE + "sitemap.xml"],
}).encode()

for url in ENDPOINTS:
    req = urllib.request.Request(url, data=payload, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("%-46s %s" % (url, r.status))
    except urllib.error.HTTPError as e:
        # 202 accepted, 200 ok, 422 key/url mismatch, 429 too many
        print("%-46s %s %s" % (url, e.code, e.read()[:120].decode("utf-8", "replace")))
    except Exception as e:
        print("%-46s ERR %s" % (url, type(e).__name__))
