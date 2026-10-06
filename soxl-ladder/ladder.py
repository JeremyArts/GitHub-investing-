"""SOXL tranche ladder stress test. Rules: RULES.md. Standard library only.

python ladder.py fetch   # daily ^SOX, ^IRX, SOXL, SOXX from Yahoo into data/
python ladder.py run     # monthly bars, signals, episodes -> results.json
"""

import csv
import json
import sys
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
SP500TR = HERE.parent / "theme-lifecycle" / "data" / "prices" / "^SP500TR.csv"

BAND_N, BAND_K, NEAR = 20, 2.0, 0.2
VOL_MULT, VOL_N = 1.5, 12
GAP_MONTHS = 2
TRANCHES = 4
EXPENSE, SPREAD = 0.0090, 0.0050


# ---------- fetch ----------

def fetch(ticker):
    url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(ticker)}"
           "?period1=-1000000000&period2=9999999999&interval=1d&events=div,split")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for i in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                res = json.load(r)["chart"]["result"][0]
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == 4:
                raise
            time.sleep(2 ** (i + 1))
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose") or q["close"]
    today = date.today().isoformat()
    DATA.mkdir(exist_ok=True)
    with open(DATA / f"{ticker.replace('^', '')}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"])
        for i, ts in enumerate(res["timestamp"]):
            d = datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
            if d >= today or None in (q["close"][i], adj[i], q["high"][i], q["low"][i]):
                continue
            w.writerow([d, q["open"][i], q["high"][i], q["low"][i], q["close"][i], adj[i], q["volume"][i] or 0])


def load(name):
    with open(DATA / f"{name}.csv") as f:
        return [{k: (v if k == "Date" else float(v)) for k, v in r.items()} for r in csv.DictReader(f)]


# ---------- series ----------

def synthetic_soxl(sox, irx):
    """Daily synthetic SOXL bars (date, high, low, close) from SOX, per the journal's E0 recipe."""
    rate = {r["Date"]: r["Close"] / 100 for r in irx}
    out, level, last_rate = [], 100.0, 0.05
    for prev, cur in zip(sox, sox[1:]):
        days = (date.fromisoformat(cur["Date"]) - date.fromisoformat(prev["Date"])).days
        last_rate = rate.get(prev["Date"], last_rate)
        cost = (EXPENSE + 2 * (last_rate + SPREAD)) * days / 365
        pc = prev["Close"]
        new = level * (1 + 3 * (cur["Close"] / pc - 1) - cost)
        hi = level * (1 + 3 * (cur["High"] / pc - 1) - cost)
        lo = level * max(1 + 3 * (cur["Low"] / pc - 1) - cost, 0.001)
        out.append((cur["Date"], max(hi, new), min(lo, new), new))
        level = new
    return out


def spliced_daily(sox, irx, soxl):
    """Synthetic before real SOXL starts, scaled so it meets the first real adjusted close."""
    syn = synthetic_soxl(sox, irx)
    first = soxl[0]["Date"]
    syn = [b for b in syn if b[0] < first]
    real = [(r["Date"], r["High"] * r["Adj Close"] / r["Close"], r["Low"] * r["Adj Close"] / r["Close"], r["Adj Close"])
            for r in soxl]
    # Scale synthetic so its level on the day before the real start equals the real first close
    # divided by the synthetic return on that first day (approximated as continuity of level).
    k = real[0][3] / syn[-1][3]
    syn = [(d, h * k, l * k, c * k) for d, h, l, c in syn]
    return syn + real


def monthly(daily, volume_by_month):
    months = {}
    for d, h, l, c in daily:
        m = d[:7]
        if m not in months:
            months[m] = {"month": m, "high": h, "low": l, "close": c}
        else:
            b = months[m]
            b["high"], b["low"], b["close"] = max(b["high"], h), min(b["low"], l), c
    current = date.today().strftime("%Y-%m")  # drop the incomplete month
    bars = [months[m] for m in sorted(months) if m < current]
    for b in bars:
        b["volume"] = volume_by_month.get(b["month"])
    return bars


def monthly_volume(rows):
    v = {}
    for r in rows:
        v[r["Date"][:7]] = v.get(r["Date"][:7], 0) + r["Volume"]
    return v


def add_indicators(bars, vol_source):
    for i, b in enumerate(bars):
        if i >= BAND_N - 1:
            w = [x["close"] for x in bars[i - BAND_N + 1:i + 1]]
            mid = sum(w) / BAND_N
            sd = (sum((x - mid) ** 2 for x in w) / BAND_N) ** 0.5
            b["mid"], b["upper"], b["lower"] = mid, mid + BAND_K * sd, mid - BAND_K * sd
        src = vol_source(b["month"])
        prev = [vol_source(bars[j]["month"]) for j in range(i - VOL_N, i)] if i >= VOL_N else None
        b["vol_src"] = src[0] if src else None
        if src and prev and all(p and p[0] == src[0] for p in prev):
            avg = sum(p[1] for p in prev) / VOL_N
            b["vol_ratio"] = src[1] / avg if avg else None
        else:
            b["vol_ratio"] = None
        b["spike"] = b["vol_ratio"] is not None and b["vol_ratio"] >= VOL_MULT
        b["near_band"] = "lower" in b and b["low"] <= b["lower"] + NEAR * (b["upper"] - b["lower"])


# ---------- simulation ----------

def months_apart(a, b):
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def simulate(bars, alloc=1.0, all_at_once=False, start_index=0, one_episode=False, chart_from=None):
    episodes, ep = [], None
    for i, b in enumerate(bars):
        if i < start_index or (one_episode and episodes):
            continue
        if ep is None:
            if b["near_band"] and b["spike"]:
                # Amendment 1 (chart_from): for starts on or after the real SOXL launch, the target is
                # the highest close on the real SOXL chart, which is all a trader can see.
                hist = [x["close"] for x in bars[:i] if not chart_from or b["month"] < chart_from or x["month"] >= chart_from]
                target = max(hist) if hist else b["close"]
                ep = {"start": b["month"], "target": target, "cash": alloc, "units": 0.0, "buys": [],
                      "path": []}
                n = TRANCHES if all_at_once else 1
                amt = alloc * n / TRANCHES
                ep["cash"] -= amt
                ep["units"] += amt / b["close"]
                ep["buys"].append({"month": b["month"], "price": b["close"], "amount": amt})
                ep["path"].append((b["month"], ep["cash"] + ep["units"] * b["close"]))
            continue
        # exit check first: limit sell at the target
        if b["high"] >= ep["target"]:
            ep["exit"] = b["month"]
            ep["final"] = ep["cash"] + ep["units"] * ep["target"]
            ep["path"].append((b["month"], ep["final"]))
            episodes.append(ep)
            ep = None
            continue
        last = ep["buys"][-1]
        if (len(ep["buys"]) < TRANCHES and not all_at_once and b["spike"]
                and months_apart(last["month"], b["month"]) >= GAP_MONTHS and b["close"] < last["price"]):
            amt = alloc / TRANCHES
            ep["cash"] -= amt
            ep["units"] += amt / b["close"]
            ep["buys"].append({"month": b["month"], "price": b["close"], "amount": amt})
        ep["path"].append((b["month"], ep["cash"] + ep["units"] * b["close"]))
    if ep:
        ep["exit"] = None
        ep["final"] = ep["path"][-1][1]
        episodes.append(ep)
    for e in episodes:
        vals = [v for _, v in e["path"]]
        e["worst"] = min(vals) / alloc - 1
        e["worst_month"] = e["path"][vals.index(min(vals))][0]
        e["months"] = len(vals) - 1
        e["months_underwater"] = sum(1 for v in vals[1:] if v < alloc)
        e["multiple"] = e["final"] / alloc
        e["avg_cost"] = sum(x["amount"] for x in e["buys"]) / e["units"] if e["units"] else None
        del e["path"]
    return episodes


def sp500_multiple(start, end):
    if not SP500TR.exists():
        return None
    with open(SP500TR) as f:
        px = {r["Date"][:7]: float(r["Adj Close"]) for r in csv.DictReader(f)}
    if start in px and end in px:
        return px[end] / px[start]
    return None


def run():
    sox, irx, soxl, soxx = (load(n) for n in ("SOX", "IRX", "SOXL", "SOXX"))
    daily = spliced_daily(sox, irx, soxl)
    bars = monthly(daily, {})
    soxl_v, soxx_v = monthly_volume(soxl), monthly_volume(soxx)
    first_soxl = min(soxl_v)

    def vol_source(m):
        # SOXL's own volume once it has 12 full months of history; SOXX before that.
        if m >= add_month(first_soxl, VOL_N + 1) and m in soxl_v:
            return ("SOXL", soxl_v[m])
        if m in soxx_v and m > min(soxx_v):
            return ("SOXX", soxx_v[m])
        return None

    add_indicators(bars, vol_source)
    signals = [b["month"] for b in bars if b["near_band"] and b["spike"]]
    plan = simulate(bars)
    lump = simulate(bars, all_at_once=True)
    # Fresh starts: the plan begun at each signal that comes 6+ months after the previous signal.
    idx = {b["month"]: i for i, b in enumerate(bars)}
    starts = [m for k, m in enumerate(signals) if k == 0 or months_apart(signals[k - 1], m) >= 6]
    fresh = {m: {"plan": simulate(bars, start_index=idx[m], one_episode=True),
                 "all_at_once": simulate(bars, all_at_once=True, start_index=idx[m], one_episode=True)}
             for m in starts}
    chart = add_month(first_soxl, 1)  # first full month of real SOXL
    plan_chart = simulate(bars, chart_from=chart)
    lump_chart = simulate(bars, all_at_once=True, chart_from=chart)
    fresh_chart = {m: {"plan": simulate(bars, start_index=idx[m], one_episode=True, chart_from=chart),
                       "all_at_once": simulate(bars, all_at_once=True, start_index=idx[m], one_episode=True, chart_from=chart)}
                   for m in starts}
    last = bars[-1]["month"]
    for e in (plan + lump + plan_chart + lump_chart
              + [e for f in (fresh, fresh_chart) for v in f.values() for e in v["plan"] + v["all_at_once"]]):
        e["sp500_multiple"] = sp500_multiple(e["start"], e["exit"] or last)
    out = {"data_through": last, "first_signal_possible": next(b["month"] for b in bars if b.get("vol_ratio") is not None),
           "entry_signal_months": signals, "plan": plan, "all_at_once": lump, "fresh_starts": fresh,
           "amendment_1_chart_ath": {"plan": plan_chart, "all_at_once": lump_chart, "fresh_starts": fresh_chart},
           "current": {k: bars[-1].get(k) for k in ("month", "close", "lower", "mid", "upper", "vol_ratio")}}
    (HERE / "results.json").write_text(json.dumps(out, indent=2))
    return out


def add_month(m, k):
    y, mo = int(m[:4]), int(m[5:7]) - 1 + k
    return f"{y + mo // 12:04d}-{mo % 12 + 1:02d}"


if __name__ == "__main__":
    if sys.argv[1:] == ["fetch"]:
        for t in ("^SOX", "^IRX", "SOXL", "SOXX"):
            fetch(t)
            print("fetched", t)
            time.sleep(1)
    else:
        print(json.dumps(run(), indent=2))
