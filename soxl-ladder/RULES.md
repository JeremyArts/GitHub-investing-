# SOXL tranche ladder — stress test rules (written 2026-10-06, before any run)

Jeremy's plan, written down before testing. This is a **stress test**, not a test for an edge:
the SOXL journal records that no untouched historical data remains (H12, the same entry signal,
was rejected on 2026-10-03). The question is how bad the bad cases are for the money at risk.

## Data
- SOXL monthly bars: real SOXL (Yahoo, adjusted) from Mar 2010. Before that, synthetic SOXL from
  daily ^SOX and ^IRX, using the journal's E0 recipe: daily return = 3 × SOX return − (0.90% +
  2 × (prior-day T-bill + 0.50%)) × calendar days / 365. Synthetic highs/lows from SOX highs/lows
  relative to the prior close. Spliced onto real SOXL at its first day. Known bias: synthetic
  misses dividends (about −4.2%/yr vs real), pessimistic.
- Volume: SOXL's own monthly volume once it has 12 months of history (from Mar 2011); before
  that, SOXX volume (from Jul 2001). No volume exists before 2001, so no signal can fire earlier.

## Rules
1. Bollinger Bands on SOXL monthly closes: 20 months, ±2 standard deviations (population SD).
2. Volume spike: monthly volume ≥ 1.5× the average of the previous 12 months.
3. Buy 1 (1/4 of the allocation): a month whose low is within the bottom 20% of the band width
   (low ≤ lower + 0.2 × (upper − lower)) and that has a volume spike. Bought at that month's close.
4. Buys 2, 3, 4 (1/4 each): a month with a volume spike, at least 2 months after the previous buy,
   whose close is below the previous buy price. Bought at that month's close. No band condition.
5. Exit: sell everything at the target = highest SOXL monthly close before buy 1, in the first
   month whose high reaches it (limit fill at the target).
6. Unbought tranches stay in cash at 0% interest (pessimistic). After an exit, a new episode can
   start from the next month.

## Reported (no pass/fail; this informs sizing)
Per episode: buy dates and prices, tranches filled, exit date or still holding, worst loss of the
allocation, months underwater, final value. Compared with buying all 4 tranches at buy 1 (same
exit) and with the S&P 500 total return over the same months. Shown in dollars for a $2,000 and
$3,000 allocation (20–30% of a ~$10k Roth).

## Amendment 1 (2026-10-06, after the first run — disclosed)
As first written, "highest SOXL monthly close before buy 1" included the synthetic history, so every
target was the synthetic Feb 2000 peak (23,294 vs prices of 1–200), which no trade could reach.
That does not match the plan: the SOXL chart a trader sees starts in Mar 2010. Amendment: for buys
from Apr 2010 on, the target is the highest close on the real SOXL chart; earlier starts keep the
synthetic history (no chart existed). Both versions are reported in results.json.
Also added after the first run, as a reporting view only: the plan started fresh at each signal that
comes 6+ months after the previous one.

## Amendment 2 (2026-10-06, Jeremy's decision after seeing the first results — disclosed)
- Sleeve cap: 20% of the Roth (about $2,000 today).
- Exit: sell everything at the previous all-time high (Amendment 1 definition) if reached within
  5 years of buy 1. From 60 months after buy 1, also sell in the first month whose range reaches the
  20-month middle band: filled at the middle band, or at the month's open if it opens above it.
