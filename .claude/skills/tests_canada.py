"""Tests for the Canadian (TSX / TSX Venture) support added to the trader-* skills.

    python3 .claude/skills/tests_canada.py

Standard library only, no network.
"""

import datetime
import importlib.util
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def load(folder, name):
    spec = importlib.util.spec_from_file_location("ca_" + name, os.path.join(HERE, folder, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


scan = load("trader-scanner", "scan")
entry = load("trader-entry", "entry")
exitp = load("trader-exit", "exit")
tm = load("trader-timemachine", "timemachine")
alerts = load("trader-alerts", "alerts")
check = load("trader-risk", "check")
ticket = load("trader-broker", "ticket")
news = load("trader-news", "news")

D = datetime.date
WITH_CALENDAR = (entry, exitp, alerts, check)


def bracket(sym, entry_px=7.87, stop=7.75, target=8.11, qty=4):
    return {"symbol": sym, "side": "buy", "qty": str(qty), "type": "market", "time_in_force": "day",
            "order_class": "bracket", "take_profit_limit_price": "%.2f" % target,
            "stop_loss_stop_price": "%.2f" % stop,
            "plan": {"entry": entry_px, "stop": stop, "target": target, "risk_per_share": round(entry_px - stop, 2),
                     "max_loss": round((entry_px - stop) * qty, 2), "setup": "orb", "flat_by": "15:55"}}


CFG = {"budget": 50, "cash_buffer_pct": 10, "max_position_pct": 75, "max_order_usd": 45, "min_order_usd": 5,
       "max_loss_per_trade_usd": 1, "max_daily_loss_usd": 3, "max_trades_per_day": 3, "max_orders_per_day": 10,
       "min_reward_risk": 1.0, "require_stop": True, "no_entries_before": "09:45", "no_entries_after": "15:30",
       "flat_by": "15:55", "fractional": False, "paper": True}


class Tickers(unittest.TestCase):
    def test_yahoo_form_keeps_the_exchange_suffix(self):
        cases = {"RY.TO": "RY.TO", "CTC.A.TO": "CTC-A.TO", "AP.UN.TO": "AP-UN.TO", "ONE.V": "ONE.V",
                 "BRK.B": "BRK-B", "TSLA": "TSLA", "ctc.a.to": "CTC-A.TO"}
        for ours, yahoo in cases.items():
            self.assertEqual(scan.to_yahoo(ours), yahoo, ours)
            self.assertEqual(entry.yahoo_symbol(ours), yahoo, ours)
            self.assertEqual(news.yahoo_symbol(ours), yahoo, ours)
            for mod in (exitp, tm, alerts, check):
                self.assertEqual(mod.yahoo_ticker(ours), yahoo, ours)

    def test_yahoo_answers_map_back_to_our_tickers(self):
        doc = {"spark": {"result": [{"symbol": "CTC-A.TO", "response": [{"meta": {}, "timestamp": [],
                                                                         "indicators": {"quote": [{}]}}]}]}}
        self.assertIn("CTC.A.TO", scan.parse_spark(doc))

    def test_alerts_urls(self):
        self.assertIn("/CTC-A.TO?", alerts.yahoo_url("CTC.A.TO"))
        with self.assertRaises(alerts.AlertError):
            alerts.stooq_url("RY.TO")
        self.assertIn("tsla.us", alerts.stooq_url("TSLA"))

    def test_risk_accepts_canadian_tickers(self):
        for ok in ("RY.TO", "CTC.A.TO", "AP.UN.TO", "ONE.V", "SHOP.TO", "TSLA", "BRK.B"):
            self.assertTrue(check.TICKER.match(ok), ok)
        for bad in ("RY.XYZ", "TOOLONGX.TO", "BTC/USD"):
            self.assertFalse(check.TICKER.match(bad), bad)


class Calendar(unittest.TestCase):
    def tearDown(self):
        scan.MARKET = "us"
        for mod in WITH_CALENDAR:
            mod.use_market("TSLA")
        tm.use_market("TSLA")

    def test_scanner_tsx_calendar(self):
        scan.MARKET = "ca"
        self.assertEqual(scan.trading_day(D(2026, 12, 28)), (False, "TSX holiday: Boxing Day (observed)"))
        self.assertFalse(scan.trading_day(D(2026, 5, 18))[0])        # Victoria Day
        self.assertTrue(scan.trading_day(D(2026, 11, 26))[0])        # US Thanksgiving: Toronto is open
        self.assertTrue(scan.trading_day(D(2026, 7, 3))[0])          # US Independence Day (observed)
        self.assertEqual(scan.session(D(2026, 12, 24))[1], scan.EARLY)
        self.assertEqual(scan.session(D(2026, 11, 27))[1], scan.CLOSE)  # no early close day after US Thanksgiving
        scan.MARKET = "us"
        self.assertTrue(scan.trading_day(D(2026, 12, 28))[0])
        self.assertFalse(scan.trading_day(D(2026, 11, 26))[0])

    def test_use_market_switches_each_skill(self):
        for mod in WITH_CALENDAR:
            mod.use_market("RY.TO")
            self.assertEqual(mod.EXCHANGE, "TSX", mod.__name__)
            self.assertIn("2026-12-28", mod.NYSE_HOLIDAYS)
            self.assertNotIn("2026-11-26", mod.NYSE_HOLIDAYS)
            mod.use_market("TSLA")
            self.assertEqual(mod.EXCHANGE, "NYSE", mod.__name__)
            self.assertIn("2026-11-26", mod.NYSE_HOLIDAYS)
        tm.use_market("ONE.V")
        self.assertIn("2026-12-24", tm.NYSE_EARLY_CLOSE)
        self.assertNotIn("2026-11-27", tm.NYSE_EARLY_CLOSE)

    def test_alerts_clock(self):
        alerts.use_market("RY.TO")
        st = alerts.market_status(alerts.parse_now("2026-12-28 10:00"))
        self.assertFalse(st["open"])
        self.assertEqual(st["next_open"], "2026-12-29 09:30")
        alerts.use_market("TSLA")
        self.assertTrue(alerts.market_status(alerts.parse_now("2026-12-28 10:00"))["open"])


class Universe(unittest.TestCase):
    def test_classify(self):
        keep = [("RY", "Royal Bank of Canada"), ("CTC.A", "Canadian Tire"), ("AP.UN", "Allied Properties REIT"),
                ("CHE.UN", "Chemtrade Logistics Income Fund"), ("AAPL", "Apple CDR (CAD Hedged)")]
        for sym, name in keep:
            self.assertEqual(scan.classify_ca(sym, name), "keep", sym)
        out = {("XIU", "iShares S&P/TSX 60 Index ETF"): "ETF", ("ENB.PF.A", "Enbridge"): "preferred",
               ("AIM.PR.A", "Aimia"): "preferred", ("CJ.DB", "Cardinal"): "debenture or note",
               ("CJ.WT", "Cardinal"): "warrant", ("FIVD.P", "5D Acquisition"): "capital pool company",
               ("BTCQ.U", "3iQ Bitcoin"): "US-dollar line", ("IAU.WT.U", "i-80"): "warrant",
               ("FCA.U", "Firm Capital"): "US-dollar line", ("AB1", "x"): "not a plain ticker"}
        for (sym, name), why in out.items():
            self.assertEqual(scan.classify_ca(sym, name), why, sym)
        self.assertNotEqual(scan.classify_ca("AAPL", "Apple CDR (CAD Hedged)", cdr=False), "keep")

    def test_build(self):
        docs = {"tsx": {"results": [
                    {"symbol": "RY", "name": "Royal Bank of Canada", "instruments": [
                        {"symbol": "RY", "name": "Royal Bank"}, {"symbol": "RY.PR.J", "name": "RBC Pr J"}]},
                    {"symbol": "XIU", "name": "iShares S&P/TSX 60 Index ETF", "instruments": [
                        {"symbol": "XIU", "name": "iShares"}]}]},
                "tsxv": {"results": [{"symbol": "ONE", "name": "01 Quantum Inc.", "instruments": [
                    {"symbol": "ONE", "name": "01 Quantum Inc."}]}]}}
        kept, counts = scan.build_universe_ca(docs)
        self.assertEqual([s for s, _ in kept], ["ONE.V", "RY.TO"])
        self.assertEqual(counts["rows"], 4)

    def test_daily_scan_drops_etfs_in_canada(self):
        t0 = int(datetime.datetime(2026, 9, 1, 20, 0).timestamp())
        ts = [t0 + 86400 * i for i in range(60)]
        closes = [10 + 0.01 * i for i in range(59)] + [12.0]    # a 20-day closing-high breakout
        def series(kind):
            return {"t": ts, "c": closes, "meta": {"regularMarketPrice": 12.0, "regularMarketVolume": 500000,
                                                   "instrumentType": kind}}
        data = {"RY.TO": series("EQUITY"), "XIU.TO": series("ETF")}
        now = datetime.datetime(2026, 11, 18, 4, 0)
        scan.MARKET = "ca"
        try:
            hits, counts, _ = scan.scan_daily(data, ["RY.TO", "XIU.TO"], now, 1.0, 100000)
        finally:
            scan.MARKET = "us"
        self.assertEqual([h["symbol"] for h in hits], ["RY.TO"])
        self.assertEqual(counts["fund"], 1)


class RiskAndBroker(unittest.TestCase):
    def tearDown(self):
        check.use_market("TSLA")

    def test_a_canadian_bracket_passes_with_a_note(self):
        res = check.check([bracket("IVN.TO")], CFG, today="2026-11-12", now=check.parse_now("2026-11-12 09:56"))
        self.assertEqual(res["pass"], 1, res)
        self.assertTrue(any("Canadian dollars" in w for w in res["warnings"]), res["warnings"])

    def test_tsx_holiday_blocks_a_canadian_entry_but_not_a_us_one(self):
        now = check.parse_now("2026-12-28 10:15")   # Boxing Day (observed): Toronto closed, New York open
        ca = check.check([bracket("IVN.TO")], CFG, today="2026-12-28", now=now)
        self.assertEqual(ca["block"], 1)
        self.assertIn("TSX holiday", json.dumps(ca["results"]))
        us = check.check([bracket("F", 12.00, 11.88, 12.24, qty=3)], CFG, today="2026-12-28", now=now)
        self.assertEqual(us["pass"], 1, us)

    def test_broker_prints_a_manual_ticket(self):
        text, _ = ticket.render(bracket("IVN.TO"), 1, 1, {"broker": "alpaca", "paper": True}, None, {}, "2026-11-12")
        self.assertIn("Enter it by hand", text)
        self.assertNotIn("place_stock_order with exactly", text)
        text, _ = ticket.render(bracket("F", 12.00, 11.88, 12.24), 1, 1, {"broker": "alpaca"}, None, {}, "2026-11-12")
        self.assertIn("place_stock_order with exactly", text)


class Wealthsimple(unittest.TestCase):
    def test_steps_for_a_tsx_bracket(self):
        text, _ = ticket.render(bracket("IVN.TO"), 1, 1, {"broker": "wealthsimple", "paper": False}, None, {},
                                "2026-11-12")
        self.assertIn("Wealthsimple (you enter it in the app)", text)
        self.assertIn("search IVN, pick the TSX listing", text)
        self.assertIn("Buy 4 IVN.TO, market order", text)
        self.assertIn("Stop market, stop price 7.75", text)
        self.assertIn("Stop limit: stop 7.75, limit 7.71", text)
        self.assertNotIn("place_stock_order with exactly", text)
        self.assertNotIn("currency fee", text)

    def test_paper_says_do_not_enter_it(self):
        text, _ = ticket.render(bracket("IVN.TO"), 1, 1, {"broker": "wealthsimple", "paper": True}, None, {},
                                "2026-11-12")
        self.assertIn("Do NOT enter this in the app", text)

    def test_us_stock_warns_about_currency(self):
        text, _ = ticket.render(bracket("F", 12.00, 11.88, 12.24, qty=3), 1, 1, {"broker": "wealthsimple"},
                                None, {}, "2026-11-12")
        self.assertIn("currency fee", text)

    def test_a_sell_cancels_the_stop_first(self):
        steps = "\n".join(ticket.wealthsimple_steps({"symbol": "IVN.TO", "side": "sell", "qty": "4",
                                                     "type": "market"}))
        self.assertIn("Cancel any open stop order", steps)

    def test_stop_limit_price(self):
        self.assertEqual(ticket.stop_limit_price(7.75), 7.71)
        self.assertEqual(ticket.stop_limit_price(1.00), 0.99)
        self.assertEqual(ticket.stop_limit_price(0.38), 0.37)


class News(unittest.TestCase):
    def test_tsx_mentions(self):
        pats = news.mention_patterns({"RY.TO": None, "CTC.A.TO": None})
        self.assertTrue(pats["RY.TO"].search("Royal Bank (TSX: RY) raises its dividend"))
        self.assertTrue(pats["CTC.A.TO"].search("Canadian Tire (TSX:CTC.A) reports"))
        self.assertFalse(pats["RY.TO"].search("(TSX: RYX) something else"))

    def test_sec_is_skipped_for_canadian_tickers(self):
        class F:
            offline = None
            def get(self, url, name, sec=False):
                if "company_tickers" in url:
                    return json.dumps({"0": {"ticker": "TSLA", "cik_str": 1318605}}).encode()
                if "rss" in url:
                    return b"<rss><channel></channel></rss>"
                raise AssertionError("no SEC feed for a Canadian ticker: " + url)
        errors = []
        news.collect(F(), {"RY.TO": None}, {}, errors=errors)
        self.assertTrue(any("SEDAR+" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
