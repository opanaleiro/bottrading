"""Useful invariants for the strategy and its simulated risk limits."""

import math
import time
import unittest
from unittest.mock import patch

import httpx

from bot.engine import analyze_market, ema, exit_reason, risk_plan, rsi
from bot import market


class IndicatorsTests(unittest.TestCase):
    def test_flat_history_is_neutral(self):
        self.assertEqual(ema([100.0] * 60, 12), 100.0)
        self.assertEqual(rsi([100.0] * 60), 50.0)
        result = analyze_market({"symbol": "BTC/USD", "price": 100, "candles": [100] * 60, "source": "demo"}, 7)
        self.assertEqual(result["signal"], "wait")
        self.assertEqual(result["indicators"]["volatility_pct"], 0)

    def test_rsi_extremes_and_insufficient_history(self):
        self.assertEqual(rsi(list(range(1, 61))), 100.0)
        self.assertEqual(rsi(list(range(60, 0, -1))), 0.0)
        with self.assertRaises(ValueError):
            rsi([1, 2, 3])

    def test_invalid_data_never_produces_trade(self):
        for prices in ([100] * 59, [100] * 59 + [float("nan")], [100] * 59 + [0]):
            result = analyze_market({"symbol": "BTC/USD", "price": 100, "candles": prices}, 10)
            self.assertEqual(result["signal"], "wait")
            self.assertEqual(result["confidence"], 0)

    def test_coherent_trends_produce_opposite_signals(self):
        increasing = [100 + index * 0.05 + 0.5 * math.sin(index * 0.9) for index in range(96)]
        decreasing = [200 - value for value in increasing]
        for prices, expected in ((increasing, "buy"), (decreasing, "sell")):
            result = analyze_market({"symbol": "BTC/USD", "price": prices[-1], "candles": prices, "source": "demo"}, 7)
            self.assertEqual(result["signal"], expected)
            self.assertGreaterEqual(result["confidence"], 0.5)
            self.assertLess(result["confidence"], 1)
            self.assertEqual(next(stage for stage in result["pipeline"] if stage["name"] == "Analista IA")["status"], "unavailable")


class RiskTests(unittest.TestCase):
    def test_full_collateral_and_risk_budget_at_all_aggressiveness(self):
        for aggression in range(1, 11):
            for cash in (15, 200, 1000):
                plan = risk_plan(1000, cash, 100, 0.5, aggression, 0, 0.8)
                self.assertIsNotNone(plan)
                self.assertLessEqual(plan["notional"], cash * 0.985)
                self.assertAlmostEqual(plan["notional"], plan["quantity"] * 100)
                expected_budget = 1000 * (0.0025 + (aggression - 1) / 9 * 0.0075) * 0.9
                self.assertLessEqual(plan["notional"] * plan["stop_distance_pct"] / 100, expected_budget + 1e-10)
                self.assertGreater(plan["take_distance_pct"], plan["stop_distance_pct"])

    def test_no_trade_when_balance_confidence_or_capacity_insufficient(self):
        self.assertIsNone(risk_plan(1000, 0, 100, 1, 7, 0, 0.8))
        self.assertIsNone(risk_plan(1000, 100, 100, 1, 7, 0, 0.49))
        self.assertIsNone(risk_plan(1000, 1000, 100, 1, 10, 6, 0.8))
        self.assertIsNone(risk_plan(1000, 9, 100, 1, 7, 0, 0.8))
        self.assertIsNone(risk_plan(float("nan"), 100, 100, 1, 7, 0, 0.8))
        self.assertIsNone(risk_plan(1000, 100, 0, 1, 7, 0, 0.8))

    def test_more_aggression_increases_bounded_allocation(self):
        conservative = risk_plan(1000, 1000, 100, 0.2, 1, 0, 0.8)
        aggressive = risk_plan(1000, 1000, 100, 0.2, 10, 0, 0.8)
        self.assertLess(conservative["notional"], aggressive["notional"])
        self.assertLessEqual(aggressive["notional"], 160)


class ExitTests(unittest.TestCase):
    def test_long_stop_and_target_including_boundary(self):
        position = {"direction": "long", "stop_price": 95, "take_price": 110}
        self.assertEqual(exit_reason(position, 95), "stop_loss")
        self.assertEqual(exit_reason(position, 110), "take_profit")
        self.assertIsNone(exit_reason(position, 100))

    def test_short_stop_and_target_including_boundary(self):
        position = {"direction": "short", "stop_price": 105, "take_price": 90}
        self.assertEqual(exit_reason(position, 105), "stop_loss")
        self.assertEqual(exit_reason(position, 90), "take_profit")
        self.assertIsNone(exit_reason(position, 100))

    def test_close_only_and_invalid_prices(self):
        self.assertEqual(exit_reason({}, 100, close_only=True), "close_only")
        self.assertIsNone(exit_reason({"stop_price": 95}, float("nan")))
        self.assertIsNone(exit_reason({"stop_price": 95}, -1))


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        market._pair_keys.clear()
        market._history_cache.clear()
        self.requests = []
        self.ticker_generation = 0
        self.real_client = httpx.AsyncClient

    def response(self, request):
        endpoint = request.url.path.rsplit("/", 1)[-1]
        self.requests.append(endpoint)
        if endpoint == "AssetPairs":
            result = {f"canonical_{pair}": {"altname": pair} for _, pair, _ in market.ASSETS}
        elif endpoint == "Ticker":
            self.ticker_generation += 1
            result = {f"canonical_{pair}": {"c": [str(base * (1 + self.ticker_generation * 0.01)), "1"]} for _, pair, base in market.ASSETS}
        elif endpoint == "OHLC":
            pair = request.url.params["pair"]
            bucket = int(time.time()) // 900 * 900
            rows = [[bucket - index * 900, "100", "101", "99", str(100 + index / 100), "100", "20", 3] for index in range(719, -1, -1)]
            result = {pair: rows, "last": bucket}
        else:
            return httpx.Response(404)
        return httpx.Response(200, json={"error": [], "result": result})

    def client_patch(self, handler):
        transport = httpx.MockTransport(handler)
        return patch("bot.market.httpx.AsyncClient", side_effect=lambda **kwargs: self.real_client(transport=transport, **kwargs))

    async def test_demo_is_explicitly_synthetic_and_reproducible(self):
        first = await market.fetch_demo_markets(3)
        same = await market.fetch_demo_markets(3)
        next_step = await market.fetch_demo_markets(4)
        self.assertEqual(first, same)
        self.assertEqual(len({item["symbol"] for item in first}), 16)
        self.assertTrue(all(item["source"] == "demo" and item["synthetic"] for item in first))
        self.assertTrue(all(len(item["candles"]) >= 60 and item["price"] > 0 for item in first))
        self.assertEqual(first[0]["candles"][1:], next_step[0]["candles"][:-1])

    async def test_real_provider_resolves_pairs_caches_history_and_refreshes_quotes(self):
        with self.client_patch(self.response), patch("bot.market.OHLC_REQUEST_INTERVAL_SECONDS", 0):
            first = await market.fetch_kraken_markets()
            second = await market.fetch_kraken_markets()
        self.assertEqual(len(first), 16)
        self.assertTrue(all(item["source"] == "kraken" and not item["synthetic"] for item in first))
        self.assertTrue(all(len(item["candles"]) == 97 for item in first))
        self.assertNotEqual(first[0]["price"], second[0]["price"])
        self.assertEqual(self.requests.count("AssetPairs"), 1)
        self.assertEqual(self.requests.count("OHLC"), 16)
        self.assertEqual(self.requests.count("Ticker"), 2)
        self.assertEqual(self.requests[-1], "Ticker")

    async def test_api_rate_failure_is_explicit_and_never_replaced_with_demo(self):
        def failure(request):
            return httpx.Response(200, json={"error": ["EAPI:Rate limit exceeded"], "result": {}})
        with self.client_patch(failure), patch("bot.market.OHLC_REQUEST_INTERVAL_SECONDS", 0):
            with self.assertRaisesRegex(market.MarketDataError, "Rate limit exceeded"):
                await market.fetch_kraken_markets()

    async def test_http_failure_is_explicit(self):
        with self.client_patch(lambda request: httpx.Response(403)), patch("bot.market.OHLC_REQUEST_INTERVAL_SECONDS", 0):
            with self.assertRaisesRegex(market.MarketDataError, "Kraken AssetPairs"):
                await market.fetch_kraken_markets()

    async def test_bad_one_asset_quote_rejects_entire_real_snapshot(self):
        def broken(request):
            response = self.response(request)
            if request.url.path.endswith("/Ticker"):
                payload = response.json()
                payload["result"]["canonical_XBTUSD"]["c"][0] = "nan"
                return httpx.Response(200, json=payload)
            return response
        with self.client_patch(broken), patch("bot.market.OHLC_REQUEST_INTERVAL_SECONDS", 0):
            with self.assertRaisesRegex(market.MarketDataError, "precio actual inválido"):
                await market.fetch_kraken_markets()

    async def test_stale_one_asset_history_rejects_entire_snapshot(self):
        def stale(request):
            response = self.response(request)
            if request.url.path.endswith("/OHLC") and request.url.params["pair"] == "canonical_XBTUSD":
                payload = response.json()
                for row in payload["result"]["canonical_XBTUSD"]:
                    row[0] -= 3600
                return httpx.Response(200, json=payload)
            return response
        with self.client_patch(stale), patch("bot.market.OHLC_REQUEST_INTERVAL_SECONDS", 0):
            with self.assertRaisesRegex(market.MarketDataError, "30 minutos"):
                await market.fetch_kraken_markets()


if __name__ == "__main__":
    unittest.main()
