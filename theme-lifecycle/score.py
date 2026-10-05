"""Theme Lifecycle Study scorer.

Implements the pre-registered rules in config.json. Standard library only.

Data layout (monthly or daily files both work; the last value in each month is used):
  <data>/prices/<TICKER>.csv   Yahoo export: Date,...,Close,Adj Close,...
  <data>/trends/<term>.csv     Google Trends export ("Month,<term>: (Worldwide)")

Real data is refused until config.json has "signed_off": true. A data folder
holding a file named SYNTHETIC is treated as made-up test data and always runs.

Usage:
  python score.py coverage --data DIR   # date ranges only, no returns
  python score.py score --data DIR      # full scoring (locked until sign-off)
"""

import argparse
import calendar
import csv
import hashlib
import json
import math
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"


# ---------- months ----------

def month_key(y, m):
    return f"{y:04d}-{m:02d}"


def parse_month(s):
    y, m = s[:7].split("-")
    return int(y), int(m)


def add_months(key, k):
    y, m = parse_month(key)
    i = y * 12 + (m - 1) + k
    return month_key(i // 12, i % 12 + 1)


def months_between(a, b):
    ya, ma = parse_month(a)
    yb, mb = parse_month(b)
    return (yb * 12 + mb) - (ya * 12 + ma)


def entry_a_month(theme):
    """First month-end strictly after the catalyst date (or a pinned override)."""
    if theme.get("entry_a_excluded"):
        return None
    if theme.get("entry_a_month"):
        return theme["entry_a_month"]
    d = date.fromisoformat(theme["catalyst"])
    last_day = calendar.monthrange(d.year, d.month)[1]
    key = month_key(d.year, d.month)
    return key if d.day < last_day else add_months(key, 1)


# ---------- loading ----------

def safe_name(s):
    return re.sub(r"[^A-Za-z0-9^._-]+", "_", s)


def load_prices(path):
    """Return {YYYY-MM: last adjusted close in that month}."""
    out = {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        col = "Adj Close" if "Adj Close" in reader.fieldnames else "Close"
        rows = []
        for r in reader:
            v = (r.get(col) or "").strip()
            if not v or v.lower() == "null":
                continue
            rows.append((r["Date"][:10], float(v)))
    for d, v in sorted(rows):
        out[d[:7]] = v
    return out


def load_trends(path):
    out = {}
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and re.fullmatch(r"\d{4}-\d{2}", row[0].strip()):
                v = row[1].strip()
                out[row[0].strip()] = None if v == "" else (v if v.startswith("<") else float(v))
    return out


class Data:
    def __init__(self, root, cfg):
        self.root = Path(root)
        self.cfg = cfg
        self._prices = {}
        self._trends = {}

    def prices(self, ticker):
        if ticker not in self._prices:
            p = self.root / "prices" / f"{safe_name(ticker)}.csv"
            series = load_prices(p) if p.exists() else {}
            ov = self.cfg.get("price_overrides", {}).get(ticker)
            if ov and series:
                # Cash buyout: from this month on the position is worth the deal price.
                series = {m: (ov["price"] if m >= ov["cash_from"] else v) for m, v in series.items()}
                series[ov["cash_from"]] = ov["price"]
                series = dict(sorted(series.items()))
            self._prices[ticker] = series
        return self._prices[ticker]

    def trends(self, term):
        if term not in self._trends:
            p = self.root / "trends" / f"{safe_name(term)}.csv"
            self._trends[term] = load_trends(p) if p.exists() else {}
        return self._trends[term]


# ---------- baskets ----------

def price_at(series, m):
    """Price at month m; a member whose data has ended is held at its last price."""
    if m in series:
        return series[m]
    earlier = [k for k in series if k <= m]
    if not earlier or m < min(series):
        return None
    return series[max(earlier)]


def is_live(series, m):
    return bool(series) and min(series) <= m <= max(series)


def basket_path(data, members, start, end, rebalance_every=12):
    """Monthly value of an equal-weighted basket bought at `start`.

    Rebalanced every `rebalance_every` months to equal weight across members
    trading at that month. Members that start trading later join at the next
    rebalance; members whose data ends are held at their last price until the
    next rebalance, then their value is spread over the live members.
    Returns {month: value} with value 1.0 at start, or None if nothing traded at start.
    """
    series = {t: data.prices(t) for t in members}
    live = [t for t in members if is_live(series[t], start)]
    if not live:
        return None
    value = 1.0
    units = {t: (value / len(live)) / price_at(series[t], start) for t in live}
    path = {start: 1.0}
    m = start
    k = 0
    while m < end:
        m = add_months(m, 1)
        k += 1
        value = sum(u * price_at(series[t], m) for t, u in units.items())
        path[m] = value
        if k % rebalance_every == 0:
            live = [t for t in members if is_live(series[t], m)]
            if not live:
                # Nothing trading: hold the old positions at their last prices.
                continue
            units = {t: (value / len(live)) / price_at(series[t], m) for t in live}
    return path


def last_common_month(data, members, benchmark):
    ends = [max(s) for s in (data.prices(t) for t in members) if s]
    b = data.prices(benchmark)
    if not ends or not b:
        return None
    return min(max(ends), max(b))


def max_drawdown(values):
    peak, worst = -math.inf, 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst


# ---------- entries ----------

def crash_month(path, threshold):
    peak = -math.inf
    for m in sorted(path):
        v = path[m]
        peak = max(peak, v)
        if v <= (1 - threshold) * peak:
            return m
    return None


def trends_value(v, less_than_one):
    if v is None:
        return None
    if isinstance(v, str):
        return less_than_one
    return v


def attention_month(series, floor_month, rules):
    """First month M >= floor where the 3x condition holds for `confirm` months in a row.

    Entry is the end of the last confirming month. Each month is compared with the
    average of the `trailing` months before it, which must be complete and >= the minimum.
    """
    months = sorted(series)
    vals = {m: trends_value(series[m], rules["less_than_one_value"]) for m in months}
    n, mult, confirm = rules["trailing_months"], rules["multiple"], rules["confirm_months"]

    def hot(m):
        window = [add_months(m, -i) for i in range(1, n + 1)]
        if any(vals.get(w) is None for w in window) or vals.get(m) is None:
            return False
        avg = sum(vals[w] for w in window) / n
        return avg >= rules["min_trailing_avg"] and vals[m] >= mult * avg

    for m in months:
        if m < floor_month:
            continue
        run = [add_months(m, i) for i in range(confirm)]
        if all(hot(r) for r in run):
            return run[-1]
    return None


# ---------- scoring ----------

def binomial_threshold(n, alpha):
    """Smallest k with P(X >= k) < alpha for X ~ Binomial(n, 0.5)."""
    for k in range(n + 1):
        p = sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n
        if p < alpha:
            return k, p
    return None, None


def score_entry(data, cfg, theme, start):
    members, bench = theme["members"], cfg["benchmark"]
    end = last_common_month(data, members, bench)
    out = {"entry_month": start, "horizons": {}}
    if start is None or end is None or start > end:
        out["status"] = "no data" if end is None else "after data end"
        return out
    path = basket_path(data, members, start, end, cfg["rebalance_every_months"])
    b = data.prices(bench)
    if path is None or start not in b:
        out["status"] = "unpriceable"
        return out
    out["status"] = "ok"
    out["members_at_entry"] = [t for t in members if is_live(data.prices(t), start)]
    for h in cfg["horizons_months"]:
        stop = add_months(start, h)
        if stop > end or stop not in b:
            out["horizons"][str(h)] = {"status": "incomplete"}
            continue
        r = path[stop] / path[start] - 1
        rb = b[stop] / b[start] - 1
        window = [path[m] for m in sorted(path) if start <= m <= stop]
        out["horizons"][str(h)] = {
            "status": "ok",
            "theme_return": r,
            "benchmark_return": rb,
            "excess": r - rb,
            "beats": r > rb,
            "max_drawdown": max_drawdown(window),
        }
    return out


def score_theme(data, cfg, theme):
    res = {"id": theme["id"], "name": theme["name"], "flags": []}
    bench = cfg["benchmark"]

    # Entry (a)
    a = entry_a_month(theme)
    res["a"] = score_entry(data, cfg, theme, a) if a else {"status": "excluded", "horizons": {}}

    # Entry (b)
    if theme.get("attention_fixed_month"):
        b_month = theme["attention_fixed_month"]
    elif theme.get("trends_term"):
        series = data.trends(theme["trends_term"])
        # Only triggers on or after the catalyst month count.
        floor = theme.get("attention_floor_month") or parse_floor(theme)
        b_month = attention_month(series, floor, cfg["trends"]) if series else None
        if not series:
            res["flags"].append("trends file missing")
    else:
        b_month = None
    res["b"] = score_entry(data, cfg, theme, b_month) if b_month else {"status": "no trigger", "horizons": {}}

    # Entry (c): crash on the basket tracked from entry (a), or from the first data month.
    track_from = a or first_month(data, theme["members"])
    end = last_common_month(data, theme["members"], bench)
    c_month = None
    if track_from and end and track_from <= end:
        path = basket_path(data, theme["members"], track_from, end, cfg["rebalance_every_months"])
        if path:
            c_month = crash_month(path, cfg["crash_threshold"])
    res["c"] = score_entry(data, cfg, theme, c_month) if c_month else {"status": "no crash", "horizons": {}}

    for t in theme["members"]:
        if t in cfg.get("price_only_proxies", []):
            res["flags"].append(f"{t} is price-only (biased against theme ~1-3%/yr)")
        if not data.prices(t):
            res["flags"].append(f"{t} missing (survivorship)")
    if theme.get("weak_proxy"):
        res["flags"].append("weak proxy")
    if theme.get("entry_a_note"):
        res["flags"].append(theme["entry_a_note"])
    return res


def parse_floor(theme):
    d = date.fromisoformat(theme["catalyst"])
    return month_key(d.year, d.month)


def first_month(data, members):
    starts = [min(s) for s in (data.prices(t) for t in members) if s]
    return min(starts) if starts else None


def test_hypothesis(cfg, results, hid):
    h = cfg["hypotheses"][hid]
    if h.get("exploratory"):
        return {"exploratory": True}
    rows, support, against, incomplete = [], 0, 0, 0
    for r in results:
        if r["id"] in h["exclude"]:
            continue
        e = r[h["entry"]]
        if e["status"] in ("excluded", "unpriceable", "no data"):
            continue  # not in the sample
        if e["status"] == "no trigger":
            outcome = "against" if h.get("no_trigger_counts_against") else "skip"
        else:
            hz = e["horizons"].get(str(h["horizon"]), {"status": "incomplete"})
            if hz["status"] != "ok":
                outcome = "incomplete"
            elif h["support"] == "beats":
                outcome = "support" if hz["beats"] else "against"
            else:
                outcome = "support" if not hz["beats"] else "against"
        if outcome == "skip":
            continue
        rows.append((r["id"], outcome))
        support += outcome == "support"
        against += outcome == "against"
        incomplete += outcome == "incomplete"
    n = len(rows)
    k, p = binomial_threshold(n, cfg["alpha"])
    return {
        "n": n, "support": support, "against": against, "incomplete": incomplete,
        "pass_bar": k, "pass_bar_p": p,
        "verdict": "supported (Plausible at best)" if k is not None and support >= k else "inconclusive",
        "themes": rows,
    }


def summarize(cfg, results):
    share = {}
    for entry in "abc":
        for h in cfg["horizons_months"]:
            ok = [r[entry]["horizons"][str(h)] for r in results
                  if r["id"] != "ai" and r[entry].get("horizons", {}).get(str(h), {}).get("status") == "ok"]
            if ok:
                share[f"{entry}_{h}"] = {"beat": sum(x["beats"] for x in ok), "of": len(ok)}
    return share


def config_hash(path=CONFIG_PATH):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(data_dir, cfg=None):
    if cfg is None:
        cfg = json.loads(CONFIG_PATH.read_text())
    data_dir = Path(data_dir)
    synthetic = (data_dir / "SYNTHETIC").exists()
    if not synthetic and not cfg.get("signed_off"):
        sys.exit("Locked: config.json is not signed off. Real data will not be scored "
                 "until the pre-registration is approved.")
    data = Data(data_dir, cfg)
    results = [score_theme(data, cfg, t) for t in cfg["themes"]]
    return {
        "config_sha256": config_hash(),
        "synthetic": synthetic,
        "themes": results,
        "hypotheses": {hid: test_hypothesis(cfg, results, hid) for hid in cfg["hypotheses"]},
        "share_beating_benchmark": summarize(cfg, results),
    }


# ---------- coverage (no returns) ----------

def coverage(data_dir, cfg):
    data = Data(data_dir, cfg)
    print("Prices (first month - last month); no returns are computed here")
    tickers = [cfg["benchmark"]] + [t for th in cfg["themes"] for t in th["members"]]
    for t in dict.fromkeys(tickers):
        s = data.prices(t)
        print(f"  {t:10s} {min(s) + ' - ' + max(s) if s else 'MISSING'}")
    print("\nTrends")
    for th in cfg["themes"]:
        if th.get("trends_term"):
            s = data.trends(th["trends_term"])
            print(f"  {th['trends_term']:25s} {min(s) + ' - ' + max(s) if s else 'MISSING'}")
    print("\nMembers trading at entry (a)")
    for th in cfg["themes"]:
        a = entry_a_month(th)
        live = [t for t in th["members"] if a and is_live(data.prices(t), a)]
        print(f"  {th['name']:30s} {a or '-':8s} {', '.join(live) or 'NONE (unpriceable)'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["coverage", "score"])
    ap.add_argument("--data", required=True)
    ap.add_argument("--out")
    args = ap.parse_args()
    cfg = json.loads(CONFIG_PATH.read_text())
    if args.command == "coverage":
        coverage(args.data, cfg)
        return
    result = run(args.data, cfg)
    text = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
