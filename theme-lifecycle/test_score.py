"""Checks score.py on made-up data only. Run: python -m unittest test_score"""

import csv
import json
import tempfile
import unittest
from pathlib import Path

import score

BASE_CFG = json.loads(score.CONFIG_PATH.read_text())


def months(start, n):
    return [score.add_months(start, i) for i in range(n)]


def write_prices(root, ticker, values):
    p = Path(root) / "prices" / f"{score.safe_name(ticker)}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"])
        for m, v in values.items():
            w.writerow([f"{m}-01", v, v, v, v, v, 0])


def write_trends(root, term, values):
    p = Path(root) / "trends" / f"{score.safe_name(term)}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="") as f:
        f.write("Category: All categories\n\n")
        f.write(f"Month,{term}: (Worldwide)\n")
        for m, v in values.items():
            f.write(f"{m},{v}\n")


def synthetic_dir():
    d = tempfile.mkdtemp()
    (Path(d) / "SYNTHETIC").write_text("made-up data\n")
    return d


def one_theme_cfg(theme):
    cfg = json.loads(json.dumps(BASE_CFG))
    cfg["themes"] = [theme]
    return cfg


class Months(unittest.TestCase):
    def test_entry_a_is_first_month_end_after_catalyst(self):
        self.assertEqual(score.entry_a_month({"catalyst": "1995-08-09"}), "1995-08")
        # Catalyst on the last day of the month: the next month-end is the entry.
        self.assertEqual(score.entry_a_month({"catalyst": "2022-11-30"}), "2022-12")
        self.assertEqual(score.entry_a_month({"catalyst": "2004-01-01", "entry_a_month": "2005-03"}), "2005-03")
        self.assertIsNone(score.entry_a_month({"catalyst": None, "entry_a_excluded": True}))

    def test_config_entry_months(self):
        got = {t["id"]: score.entry_a_month(t) for t in BASE_CFG["themes"]}
        self.assertEqual(got["shale"], "2008-04")
        self.assertEqual(got["printing3d"], "2012-04")
        self.assertEqual(got["clean2"], "2019-12")
        self.assertEqual(got["clean1"], "2005-03")
        self.assertIsNone(got["crypto"])


class HandChecked(unittest.TestCase):
    """The three cases checked by hand on Oct 5."""

    def test_steady_compounding(self):
        d = synthetic_dir()
        ms = months("2000-01", 61)
        write_prices(d, "AAA", {m: 100 * 1.01 ** i for i, m in enumerate(ms)})
        path = score.basket_path(score.Data(d, BASE_CFG), ["AAA"], "2000-01", ms[-1])
        self.assertAlmostEqual(path[ms[60]] - 1, 0.8167, places=4)  # 81.7%

    def test_crash_detected_at_right_month(self):
        d = synthetic_dir()
        ms = months("2000-01", 24)
        vals = [100 + 10 * i for i in range(8)]          # rises to 170 in month 7
        vals += [170 * f for f in (0.8, 0.6, 0.45, 0.4)]  # 0.45 is the first >= 50% fall
        vals += [70] * (24 - len(vals))
        write_prices(d, "AAA", dict(zip(ms, vals)))
        path = score.basket_path(score.Data(d, BASE_CFG), ["AAA"], "2000-01", ms[-1])
        self.assertEqual(score.crash_month(path, 0.5), ms[10])

    def test_delisted_member_held_at_last_price(self):
        d = synthetic_dir()
        ms = months("2000-01", 13)
        write_prices(d, "UP", {m: 100 * (1 + 0.2 * i / 12) for i, m in enumerate(ms)})
        write_prices(d, "GONE", {m: 50 for m in ms[:5]})  # delisted after 4 months, flat
        path = score.basket_path(score.Data(d, BASE_CFG), ["UP", "GONE"], "2000-01", ms[-1])
        self.assertAlmostEqual(path[ms[12]] - 1, 0.10, places=6)  # 10.0%


class Baskets(unittest.TestCase):
    def test_late_lister_joins_at_rebalance(self):
        d = synthetic_dir()
        ms = months("2010-06", 25)
        write_prices(d, "OLD", {m: 100 for m in ms})                      # flat
        write_prices(d, "NEW", {m: 10 * (2 if m >= ms[18] else 1) for m in ms[3:]})  # lists month 3, doubles month 18
        data = score.Data(d, BASE_CFG)
        path = score.basket_path(data, ["OLD", "NEW"], ms[0], ms[-1])
        self.assertAlmostEqual(path[ms[12]], 1.0)       # NEW not held in year 1
        self.assertAlmostEqual(path[ms[24]], 1.5)       # half in NEW from month 12, which doubles

    def test_palm_cash_buyout(self):
        d = synthetic_dir()
        ms = months("2010-01", 12)
        write_prices(d, "PALM", {m: 4.0 for m in ms[:7]})  # data runs to Jul 2010
        s = score.Data(d, BASE_CFG).prices("PALM")
        self.assertEqual(s["2010-06"], 4.0)
        self.assertEqual(s["2010-07"], 5.70)
        self.assertEqual(score.price_at(s, "2010-12"), 5.70)

    def test_nothing_trading_is_unpriceable(self):
        d = synthetic_dir()
        write_prices(d, "LATE", {m: 1 for m in months("2018-01", 12)})
        self.assertIsNone(score.basket_path(score.Data(d, BASE_CFG), ["LATE"], "2014-01", "2018-12"))


class Attention(unittest.TestCase):
    rules = BASE_CFG["trends"]

    def series(self, spikes, start="2004-01", n=60, base=10):
        ms = months(start, n)
        return {m: spikes.get(i, base) for i, m in enumerate(ms)}, ms

    def test_two_month_confirmation(self):
        s, ms = self.series({30: 40, 31: 40})
        self.assertEqual(score.attention_month(s, "2004-01", self.rules), ms[31])

    def test_single_noisy_month_does_not_trigger(self):
        s, ms = self.series({30: 40, 40: 40})
        self.assertIsNone(score.attention_month(s, "2004-01", self.rules))

    def test_needs_full_trailing_window(self):
        # Spike in months 5-6 is ignored: fewer than 24 months of history before it.
        s, ms = self.series({5: 40, 6: 40})
        self.assertIsNone(score.attention_month(s, "2004-01", self.rules))
        # Earliest possible trigger with data from Jan 2004 is Feb 2006.
        s, ms = self.series({24: 40, 25: 40})
        self.assertEqual(score.attention_month(s, "2004-01", self.rules), "2006-02")

    def test_jump_from_near_zero_ignored(self):
        s, ms = self.series({30: "<1", 31: 3, 32: 3}, base="<1")
        self.assertIsNone(score.attention_month(s, "2004-01", self.rules))

    def test_floor_blocks_earlier_wave(self):
        s, ms = self.series({30: 40, 31: 40, 50: 200, 51: 200})
        self.assertEqual(score.attention_month(s, ms[40], self.rules), ms[51])

    def test_trends_csv_parsing(self):
        d = synthetic_dir()
        write_trends(d, "3D printing", {"2004-01": "<1", "2004-02": 5})
        s = score.Data(d, BASE_CFG).trends("3D printing")
        self.assertEqual(s, {"2004-01": "<1", "2004-02": 5.0})


class PassBar(unittest.TestCase):
    def test_thresholds_match_preregistration(self):
        self.assertEqual(score.binomial_threshold(13, 0.05)[0], 10)
        k, p = score.binomial_threshold(12, 0.05)
        self.assertEqual(k, 10)
        self.assertAlmostEqual(p, 0.019, places=3)
        k, p = score.binomial_threshold(11, 0.05)
        self.assertEqual(k, 9)
        self.assertAlmostEqual(p, 0.033, places=3)


class EndToEnd(unittest.TestCase):
    def test_full_run_on_synthetic_theme(self):
        d = synthetic_dir()
        ms = months("2007-01", 90)
        write_prices(d, "^SP500TR", {m: 100 * 1.005 ** i for i, m in enumerate(ms)})
        write_prices(d, "AAPL", {m: 100 * 1.02 ** i for i, m in enumerate(ms)})
        write_trends(d, "smartphone", {m: 10 for m in months("2004-01", 120)})
        theme = next(t for t in BASE_CFG["themes"] if t["id"] == "smartphones")
        theme = dict(theme, members=["AAPL"])
        res = score.run(d, one_theme_cfg(theme))
        a = res["themes"][0]["a"]
        self.assertEqual(a["entry_month"], "2007-01")
        self.assertTrue(a["horizons"]["60"]["beats"])
        self.assertEqual(res["themes"][0]["b"]["status"], "no trigger")
        self.assertEqual(res["hypotheses"]["H1"]["support"], 1)
        self.assertEqual(res["hypotheses"]["H2"]["against"], 1)  # no trigger counts against H2

    def test_horizon_past_data_is_incomplete(self):
        d = synthetic_dir()
        ms = months("2019-12", 30)
        write_prices(d, "^SP500TR", {m: 100 for m in ms})
        write_prices(d, "ICLN", {m: 100 for m in ms})
        theme = dict(next(t for t in BASE_CFG["themes"] if t["id"] == "clean2"), members=["ICLN"])
        res = score.run(d, one_theme_cfg(theme))
        hz = res["themes"][0]["a"]["horizons"]
        self.assertEqual(hz["12"]["status"], "ok")
        self.assertEqual(hz["36"]["status"], "incomplete")
        self.assertEqual(res["hypotheses"]["H1"]["incomplete"], 1)

    def test_locked_without_signoff(self):
        d = tempfile.mkdtemp()  # no SYNTHETIC marker = treated as real data
        cfg = json.loads(json.dumps(BASE_CFG))
        cfg["signed_off"] = False
        with self.assertRaises(SystemExit):
            score.run(d, cfg)


if __name__ == "__main__":
    unittest.main()
