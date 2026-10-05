# Theme Lifecycle Study

Does buying a theme at its first real catalyst beat the S&P 500, while buying at peak public attention trails it?
The rules are pre-registered in the [pre-registration doc](https://claude.ai/code/artifact/3ca3524f-5297-4e85-a870-983f8bb7452e)
and encoded in `config.json`. This commit timestamps them before any returns were seen.

**Status:** awaiting sign-off and data. `score.py` refuses real data until `config.json` has `"signed_off": true`.

## Run

```
python3 -m unittest test_score              # synthetic checks only
python3 score.py coverage --data data       # date ranges + who trades at entry (a); no returns
python3 score.py score --data data --out results.json   # locked until sign-off
```

Standard library only (Python 3.8+).

## Data needed

Put files in `data/prices/<TICKER>.csv` (Yahoo export, monthly or daily) and `data/trends/<term>.csv`
(Google Trends export, worldwide, all categories, 2004–present). Characters outside `A-Z a-z 0-9 ^ . _ -` in a
name become `_`, so `3D printing` → `3D_printing.csv`.

| Kind | Files |
| --- | --- |
| Benchmark | ^SP500TR |
| Index proxies | ^NDX, ^NBI, ^HSI |
| Stocks / ETFs | AMGN, BIIB, GILD, PBW, AAPL, NOK, BB, PALM, CRM, AMZN, XOP, TSLA, LIT, NIO, LCID, BTC-USD, DDD, SSYS, MJ, CGC, TLRY, ACB, META, U, RBLX, ICLN, TAN, NVDA, SMH, AIQ |
| Trends (12 terms) | China stocks, solar energy, smartphone, cloud computing, fracking, electric car, bitcoin, 3D printing, cannabis, virtual reality, clean energy, artificial intelligence |

Internet and Biotech use fixed attention dates (record IPO years), so they need no Trends file.
FXI and SKYY were dropped by the Oct 5 proxy decisions and are not needed.
