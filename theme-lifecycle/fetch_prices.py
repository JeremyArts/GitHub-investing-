"""Download monthly prices from Yahoo's chart API into data/prices/<TICKER>.csv.

Writes the same columns as a Yahoo CSV export. Standard library only.
Usage: python fetch_prices.py [TICKER ...]   (default: every ticker in config.json)
"""

import csv
import json
import sys
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import score

URL = "https://query2.finance.yahoo.com/v8/finance/chart/{}?period1=0&period2=9999999999&interval=1mo&events=div,split"
OUT = score.HERE / "data" / "prices"


def fetch(ticker, tries=5):
    req = urllib.request.Request(URL.format(urllib.request.quote(ticker)), headers={"User-Agent": "Mozilla/5.0"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < tries - 1:
                time.sleep(2 ** (i + 1))
                continue
            raise


def write(ticker, payload):
    res = payload["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose") or q["close"]
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{score.safe_name(ticker)}.csv"
    current = date.today().strftime("%Y-%m")  # incomplete month is dropped
    n = 0
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"])
        for i, ts in enumerate(res.get("timestamp") or []):
            if q["close"][i] is None or adj[i] is None:
                continue
            d = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
            if d[:7] >= current:
                continue
            w.writerow([d, q["open"][i], q["high"][i], q["low"][i], q["close"][i], adj[i], q["volume"][i]])
            n += 1
    return n


def main():
    cfg = json.loads(score.CONFIG_PATH.read_text())
    tickers = sys.argv[1:] or list(dict.fromkeys([cfg["benchmark"]] + [t for th in cfg["themes"] for t in th["members"]]))
    for t in tickers:
        try:
            print(f"{t:10s} {write(t, fetch(t))} months")
        except Exception as e:  # report and keep going
            print(f"{t:10s} FAILED: {e}")
        time.sleep(1)


if __name__ == "__main__":
    main()
