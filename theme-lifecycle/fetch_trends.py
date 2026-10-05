"""Download Google Trends (worldwide, all categories, monthly from 2004) into data/trends/<term>.csv.

Writes the same layout as a Trends "Download CSV". Standard library only.
The current, incomplete month is dropped.
Usage: python fetch_trends.py [TERM ...]   (default: every term in config.json)
"""

import http.cookiejar
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date

import score

OUT = score.HERE / "data" / "trends"
BASE = "https://trends.google.com/trends/api"


def opener():
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    op.addheaders = [("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36")]
    op.open("https://trends.google.com/trends/?geo=US", timeout=30).read()
    return op


def get_json(op, url, tries=5):
    for i in range(tries):
        try:
            text = op.open(url, timeout=30).read().decode()
            return json.loads(text[text.index("{"):])
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < tries - 1:
                time.sleep(5 * 2 ** i)
                continue
            raise


def fetch(op, term):
    req = {"comparisonItem": [{"keyword": term, "geo": "", "time": "all"}], "category": 0, "property": ""}
    explore = get_json(op, f"{BASE}/explore?" + urllib.parse.urlencode({"hl": "en-US", "tz": "0", "req": json.dumps(req)}))
    w = next(x for x in explore["widgets"] if x["id"] == "TIMESERIES")
    data = get_json(op, f"{BASE}/widgetdata/multiline?" + urllib.parse.urlencode(
        {"hl": "en-US", "tz": "0", "req": json.dumps(w["request"]), "token": w["token"]}))
    current = date.today().strftime("%Y-%m")
    rows = []
    for p in data["default"]["timelineData"]:
        m = date.fromtimestamp(int(p["time"])).strftime("%Y-%m")
        if m >= current or p.get("isPartial"):
            continue
        rows.append((m, p["formattedValue"][0]))
    return rows


def main():
    cfg = json.loads(score.CONFIG_PATH.read_text())
    terms = sys.argv[1:] or [t["trends_term"] for t in cfg["themes"] if t.get("trends_term")]
    OUT.mkdir(parents=True, exist_ok=True)
    op = opener()
    for term in terms:
        try:
            rows = fetch(op, term)
            with open(OUT / f"{score.safe_name(term)}.csv", "w") as f:
                f.write("Category: All categories\n\n")
                f.write(f"Month,{term}: (Worldwide)\n")
                for m, v in rows:
                    f.write(f"{m},{v}\n")
            print(f"{term:25s} {len(rows)} months ({rows[0][0]} - {rows[-1][0]})")
        except Exception as e:
            print(f"{term:25s} FAILED: {e}")
        time.sleep(3)


if __name__ == "__main__":
    main()
