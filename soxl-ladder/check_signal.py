"""Monthly check of the SOXL tranche-ladder signal (rules: RULES.md, Amendment 2).

Downloads real SOXL daily data from Yahoo and reports the last completed month:
whether the first-buy condition fired (low in the bottom 20% of the 20-month band AND
volume >= 1.5x its 12-month average), whether there was a volume spike (the condition for
buys 2-4, which also need a close below the previous buy and 2+ months since it), and the
middle band (the exit level after 5 years). Standard library only.

Usage: python check_signal.py
"""

import json
import sys

import ladder as L


def main():
    L.fetch("SOXL")
    soxl = L.load("SOXL")
    daily = [(r["Date"], r["High"] * r["Adj Close"] / r["Close"], r["Low"] * r["Adj Close"] / r["Close"], r["Adj Close"])
             for r in soxl]
    vol = L.monthly_volume(soxl)
    bars = L.monthly(daily, {})
    first = min(vol)
    L.add_indicators(bars, lambda m: ("SOXL", vol[m]) if m in vol and m > first else None)
    b = bars[-1]
    entry_level = b["lower"] + L.NEAR * (b["upper"] - b["lower"])
    first_buy = b["near_band"] and b["spike"]
    out = {
        "month": b["month"],
        "close": round(b["close"], 2),
        "low": round(b["low"], 2),
        "entry_level": round(entry_level, 2),
        "lower_band": round(b["lower"], 2),
        "middle_band": round(b["mid"], 2),
        "upper_band": round(b["upper"], 2),
        "volume_vs_12mo_avg": round(b["vol_ratio"], 2) if b["vol_ratio"] else None,
        "first_buy_signal": first_buy,
        "volume_spike": b["spike"],
    }
    if first_buy:
        verdict = (f"FIRST-BUY SIGNAL for {b['month']}: low {out['low']} <= entry level {out['entry_level']} "
                   f"and volume {out['volume_vs_12mo_avg']}x. Plan: buy 1/4 of the sleeve.")
    elif b["spike"]:
        verdict = (f"Volume spike in {b['month']} ({out['volume_vs_12mo_avg']}x), no band signal. "
                   "If you hold tranches: buy the next 1/4 only if the close is below your last buy and 2+ months have passed.")
    else:
        verdict = f"No signal for {b['month']}. Entry level {out['entry_level']} vs low {out['low']}."
    print(verdict)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
