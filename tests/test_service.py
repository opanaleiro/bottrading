"""Paper broker integration checks: accounting, persistence and fail-closed data."""
from __future__ import annotations

import asyncio
import copy
import os
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import httpx

from bot.market import ASSETS, MarketDataError
from bot.service import PaperBot


def markets(prices=None, source="demo"):
    overrides = prices or {}
    return [{"symbol": f"{symbol}/USD", "price": overrides.get(symbol, 100.0),
             "source": source, "change_pct": 0.0, "candles": [100.0] * 97}
            for symbol, _pair, _price in ASSETS]


def signals(selected=None):
    selected = selected or {"BTC/USD": "buy", "ETH/USD": "sell"}

    def analyze(market, _aggressiveness):
        return {"symbol": market["symbol"], "price": market["price"],
                "signal": selected.get(market["symbol"], "wait"), "confidence": 0.9,
                "indicators": {"volatility_pct": 1.0}, "pipeline": []}
    return analyze


def fixed_plan(quantity=10):
    return {"quantity": quantity, "notional": quantity * 100,
            "stop_distance_pct": 50, "take_distance_pct": 50}


class PaperBrokerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / "paper.sqlite3"
        self.bot = PaperBot(self.path)

    async def asyncTearDown(self):
        await self.bot.shutdown()
        self.directory.cleanup()

    async def open_positions(self, selected=None, quantity=10):
        with patch("bot.service.fetch_demo_markets", AsyncMock(return_value=markets())), \
                patch("bot.service.analyze_market", side_effect=signals(selected)), \
                patch("bot.service.risk_plan", return_value=fixed_plan(quantity)):
            return await self.bot.cycle()

    async def test_manual_cycle_analyzes_all_sixteen_assets_and_opens_both_sides(self):
        state = await self.open_positions()
        self.assertEqual(len(state["assets"]), 16)
        self.assertEqual(len({asset["symbol"] for asset in state["assets"]}), 16)
        self.assertEqual({position["side"] for position in state["positions"]}, {"long", "short"})
        self.assertEqual(state["meta"]["mode"], "paper")
        self.assertFalse(state["meta"]["running"])
        self.assertEqual(self.bot.state["cycle_count"], 1)

    async def test_long_and_short_reserve_cash_and_charge_entry_slippage_and_fees(self):
        state = await self.open_positions()
        by_side = {position["side"]: position for position in state["positions"]}
        self.assertAlmostEqual(by_side["long"]["entry_price"], 100.05)
        self.assertAlmostEqual(by_side["short"]["entry_price"], 99.95)
        self.assertAlmostEqual(state["portfolio"]["cash"], 7998.0)
        self.assertAlmostEqual(state["portfolio"]["fees_paid"], 2.0)
        self.assertAlmostEqual(state["portfolio"]["unrealized_pnl"], -1.0)
        self.assertAlmostEqual(state["portfolio"]["equity"], 9997.0)
        self.assertAlmostEqual(state["portfolio"]["realized_pnl"], 0.0)

    async def test_manual_exits_use_fresh_quotes_and_reconcile_realized_net_pnl(self):
        state = await self.open_positions()
        positions = {p["side"]: p["id"] for p in state["positions"]}
        fresh = AsyncMock(return_value=markets({"BTC": 110.0, "ETH": 90.0}))
        with patch("bot.service.fetch_demo_markets", fresh):
            await self.bot.close(positions["long"])
            result = await self.bot.close(positions["short"])
        self.assertEqual(fresh.await_count, 2)
        self.assertEqual(result["positions"], [])
        trades = {trade["side"]: trade for trade in result["trades"]}
        self.assertAlmostEqual(trades["long"]["exit_price"], 109.945)
        self.assertAlmostEqual(trades["short"]["exit_price"], 90.045)
        self.assertAlmostEqual(trades["long"]["pnl"], 96.85005)
        self.assertAlmostEqual(trades["short"]["pnl"], 97.15005)
        self.assertAlmostEqual(result["portfolio"]["cash"], 10194.0001)
        self.assertAlmostEqual(result["portfolio"]["equity"], 10194.0001)
        self.assertAlmostEqual(result["portfolio"]["realized_pnl"], 194.0001)
        self.assertAlmostEqual(result["portfolio"]["fees_paid"], 3.9999)
        self.assertAlmostEqual(result["portfolio"]["equity"] - 10000,
                               sum(trade["pnl"] for trade in result["trades"]))

    async def test_collateral_plus_fees_cannot_exceed_cash_for_long_or_short(self):
        for side in ("buy", "sell"):
            with self.subTest(side=side):
                state = await self.open_positions({"BTC/USD": side}, quantity=100)
                self.assertEqual(state["positions"], [])
                self.assertEqual(state["portfolio"]["cash"], 10000.0)
                self.assertEqual(state["portfolio"]["fees_paid"], 0.0)

    async def test_max_positions_and_one_position_per_asset(self):
        await self.bot.settings({"max_positions": 2})
        all_buys = {f"{symbol}/USD": "buy" for symbol, _, _ in ASSETS}
        await self.open_positions(all_buys)
        state = await self.open_positions(all_buys)
        self.assertEqual(len(state["positions"]), 2)
        self.assertEqual(len({p["symbol"] for p in state["positions"]}), 2)
        self.assertEqual(state["trades"], [])

    async def test_close_only_exits_existing_positions_without_reopening_candidates(self):
        await self.open_positions()
        await self.bot.settings({"operation_mode": "close_only"})
        result = await self.open_positions()
        self.assertEqual(result["positions"], [])
        self.assertEqual(len(result["trades"]), 2)
        self.assertTrue(all(trade["reason"] == "close_only" for trade in result["trades"]))
        self.assertAlmostEqual(result["portfolio"]["equity"], 9994.0)

    async def test_stop_loss_closes_both_sides_without_same_cycle_reentry(self):
        await self.open_positions()
        for position in self.bot.state["positions"]:
            position["stop_loss"] = 95.0 if position["side"] == "long" else 105.0
        with patch("bot.service.fetch_demo_markets", AsyncMock(return_value=markets({"BTC": 90, "ETH": 110}))), \
                patch("bot.service.analyze_market", side_effect=signals()), \
                patch("bot.service.risk_plan", return_value=fixed_plan()):
            result = await self.bot.cycle()
        self.assertEqual(result["positions"], [])
        self.assertEqual(len(result["trades"]), 2)
        self.assertTrue(all(trade["reason"] == "stop_loss" for trade in result["trades"]))
        self.assertTrue(all(trade["pnl"] < 0 for trade in result["trades"]))
        self.assertAlmostEqual(result["portfolio"]["realized_pnl"], -206.0001)

    async def test_daily_loss_limit_closes_positions_and_blocks_entries_until_new_day(self):
        await self.bot.settings({"daily_loss_limit_pct": 0.5})
        await self.open_positions()
        with patch("bot.service.fetch_demo_markets", AsyncMock(return_value=markets({"BTC": 90, "ETH": 110}))), \
                patch("bot.service.analyze_market", side_effect=signals()), \
                patch("bot.service.risk_plan", return_value=fixed_plan()):
            result = await self.bot.cycle()
            await self.bot.settings({"daily_loss_limit_pct": 10.0})
            repeated = await self.bot.cycle()
        self.assertEqual(result["positions"], [])
        self.assertEqual(len(result["trades"]), 2)
        self.assertTrue(all(trade["reason"] == "Límite de pérdida diaria" for trade in result["trades"]))
        self.assertTrue(all(trade["pnl"] < 0 for trade in result["trades"]))
        self.assertLess(result["portfolio"]["today_return_pct"], -0.5)
        self.assertAlmostEqual(result["portfolio"]["realized_pnl"], -206.0001)
        self.assertEqual(repeated["positions"], [])
        self.assertEqual(repeated["trades"], result["trades"])
        self.assertTrue(repeated["meta"]["risk_halted"])
        self.bot.state["day"] = "2000-01-01"
        resumed = await self.open_positions()
        self.assertEqual(len(resumed["positions"]), 2)
        self.assertFalse(resumed["meta"]["risk_halted"])
        self.assertGreater(resumed["portfolio"]["today_return_pct"], -0.5)

    async def test_projected_entry_costs_cannot_push_equity_below_daily_floor(self):
        self.bot.state["cash"] = 9701.0
        all_buys = {f"{symbol}/USD": "buy" for symbol, _, _ in ASSETS}
        # Use the actual risk planner here: only one dollar of the day's loss
        # allowance remains, less than the realistic first entry's costs.
        with patch("bot.service.fetch_demo_markets", AsyncMock(return_value=markets())), \
                patch("bot.service.analyze_market", side_effect=signals(all_buys)):
            result = await self.bot.cycle()
        self.assertEqual(result["positions"], [])
        self.assertEqual(result["portfolio"]["equity"], 9701.0)
        self.assertEqual(result["portfolio"]["fees_paid"], 0.0)
        self.assertGreater(result["portfolio"]["today_return_pct"], -3.0)

    async def test_short_price_gap_keeps_real_deficit_and_requires_reset_to_restart(self):
        await self.open_positions({"BTC/USD": "sell"})
        self.bot.state["meta"]["running"] = True
        with patch("bot.service.fetch_demo_markets", AsyncMock(return_value=markets({"BTC": 2000}))), \
                patch("bot.service.analyze_market", side_effect=signals()), \
                patch("bot.service.risk_plan", return_value=fixed_plan()):
            result = await self.bot.cycle(manual=False)
        self.assertEqual(result["positions"], [])
        self.assertEqual(len(result["trades"]), 1)
        self.assertAlmostEqual(result["trades"][0]["pnl"], -19031.5095)
        self.assertAlmostEqual(result["portfolio"]["equity"], -9031.5095)
        self.assertFalse(result["meta"]["running"])
        self.assertTrue(result["meta"]["risk_halted"])
        with self.assertRaisesRegex(ValueError, "no positivo"):
            await self.bot.start()
        self.bot.state["day"] = "2000-01-01"
        new_day = await self.open_positions()
        self.assertEqual(new_day["positions"], [])
        self.assertAlmostEqual(new_day["portfolio"]["equity"], -9031.5095)
        self.assertTrue(new_day["meta"]["risk_halted"])
        reset = await self.bot.reset(10000)
        self.assertEqual(reset["portfolio"]["equity"], 10000)
        self.assertFalse(reset["meta"]["risk_halted"])

    async def test_background_start_pause_and_manual_cycle_exclusion(self):
        blocker = asyncio.Event()
        with patch.object(self.bot, "loop", side_effect=blocker.wait):
            state = await self.bot.start()
            self.assertTrue(state["meta"]["running"])
            task = self.bot.task
            await self.bot.start()
            self.assertIs(self.bot.task, task)
            with self.assertRaisesRegex(ValueError, "Pausa"):
                await self.bot.cycle()
            with self.assertRaisesRegex(ValueError, "Pausa"):
                await self.bot.reset(5000)
            stopped = await self.bot.stop()
            self.assertFalse(stopped["meta"]["running"])
            self.assertIsNone(self.bot.task)

    async def test_sqlite_restores_positions_settings_news_and_finances_but_pauses(self):
        await self.open_positions()
        with patch("bot.service.fetch_demo_markets", AsyncMock(return_value=markets({"BTC": 110}))):
            await self.bot.close(self.bot.state["positions"][0]["id"])
        await self.bot.settings({"aggressiveness": 7, "cycle_seconds": 120})
        await self.bot.add_news("Contexto manual sin verificación externa")
        expected = copy.deepcopy(self.bot.state)
        self.bot.state["meta"]["running"] = True
        self.bot.save()
        self.bot.connection.close()
        self.bot = PaperBot(self.path)
        restored = self.bot.snapshot()
        self.assertFalse(restored["meta"]["running"])
        self.assertEqual(restored["meta"]["status"], "Pausado")
        for key in ("positions", "trades", "settings", "news", "cash", "fees_paid", "equity_history"):
            self.assertEqual(self.bot.state[key], expected[key])

    async def test_real_market_failure_does_not_fallback_or_change_portfolio(self):
        await self.bot.settings({"market_source": "kraken"})
        real_feed = AsyncMock(return_value=markets(source="kraken"))
        with patch("bot.service.fetch_kraken_markets", real_feed), \
                patch("bot.service.analyze_market", side_effect=signals()), \
                patch("bot.service.risk_plan", return_value=fixed_plan()):
            await self.bot.cycle()
        before = copy.deepcopy(self.bot.state)
        with patch("bot.service.fetch_kraken_markets", AsyncMock(side_effect=MarketDataError("offline"))), \
                patch("bot.service.fetch_demo_markets", AsyncMock()) as demo:
            with self.assertRaises(ValueError):
                await self.bot.cycle()
            demo.assert_not_awaited()
        for key in ("cash", "positions", "trades", "fees_paid", "cycle_count", "assets", "equity_history"):
            self.assertEqual(self.bot.state[key], before[key])
        self.assertEqual(self.bot.state["meta"]["status"], "Error de datos")

    async def test_cycle_analysis_failure_rolls_back_closed_positions_and_entries(self):
        await self.open_positions()
        await self.bot.settings({"operation_mode": "close_only"})
        before = copy.deepcopy(self.bot.state)
        with patch("bot.service.fetch_demo_markets", AsyncMock(return_value=markets())), \
                patch.object(self.bot, "record_equity", side_effect=RuntimeError("failed after simulated exits")):
            with self.assertRaises(ValueError):
                await self.bot.cycle()
        for key in ("cash", "positions", "trades", "fees_paid", "cycle_count", "equity_history"):
            self.assertEqual(self.bot.state[key], before[key])

    async def test_incomplete_duplicate_or_invalid_market_snapshot_is_rejected(self):
        bad_snapshots = [markets()[:-1]]
        duplicate = markets()
        duplicate[-1] = duplicate[0]
        bad_snapshots.append(duplicate)
        for price in (0.0, -1.0, float("nan"), float("inf")):
            bad_snapshots.append(markets({"BTC": price}))
        for snapshot in bad_snapshots:
            with self.subTest(snapshot=snapshot[0]["price"]):
                with patch("bot.service.fetch_demo_markets", AsyncMock(return_value=snapshot)):
                    with self.assertRaises(ValueError):
                        await self.bot.cycle()
                self.assertEqual(self.bot.state["positions"], [])
                self.assertEqual(self.bot.state["cash"], 10000.0)
                self.assertEqual(self.bot.state["cycle_count"], 0)

    async def test_failed_or_invalid_fresh_close_leaves_the_position_unchanged(self):
        await self.open_positions()
        identifier = self.bot.state["positions"][0]["id"]
        for price in (None, 0.0, -1.0, float("nan"), float("inf")):
            with self.subTest(price=price):
                before = copy.deepcopy(self.bot.state)
                feed = AsyncMock(side_effect=MarketDataError("offline")) if price is None else AsyncMock(return_value=markets({"BTC": price}))
                with patch("bot.service.fetch_demo_markets", feed):
                    with self.assertRaises(ValueError):
                        await self.bot.close(identifier)
                for key in ("positions", "cash", "trades", "fees_paid", "equity_history"):
                    self.assertEqual(self.bot.state[key], before[key])

    async def test_manual_close_save_failure_restores_complete_account_state(self):
        await self.open_positions()
        before = copy.deepcopy(self.bot.state)
        identifier = before["positions"][0]["id"]
        with patch("bot.service.fetch_demo_markets", AsyncMock(return_value=markets({"BTC": 110}))), \
                patch.object(self.bot, "save", side_effect=sqlite3.OperationalError("disk unavailable")):
            with self.assertRaisesRegex(ValueError, "guardar el cierre"):
                await self.bot.close(identifier)
        self.assertEqual(self.bot.state, before)

    async def test_source_switch_blocked_by_open_positions_and_realized_history(self):
        await self.open_positions()
        with self.assertRaisesRegex(ValueError, "historiales"):
            await self.bot.settings({"market_source": "kraken"})
        await self.bot.settings({"operation_mode": "close_only"})
        await self.open_positions()
        self.assertEqual(self.bot.state["positions"], [])
        self.assertEqual(len(self.bot.state["trades"]), 2)
        with self.assertRaisesRegex(ValueError, "historiales"):
            await self.bot.settings({"market_source": "kraken"})
        await self.bot.reset(5000)
        result = await self.bot.settings({"market_source": "kraken"})
        self.assertEqual(result["settings"]["market_source"], "kraken")
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["portfolio"]["equity"], 5000)

    async def test_optional_ai_requires_existing_key_and_never_calls_api_when_off(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "ANTHROPIC_API_KEY"):
                await self.bot.settings({"ai_enabled": True})
            self.assertFalse(self.bot.state["settings"]["ai_enabled"])
            with patch.object(self.bot, "ai_verdict", AsyncMock()) as ai:
                await self.open_positions()
                ai.assert_not_awaited()
            self.assertFalse(self.bot.snapshot()["meta"]["ai_available"])

    async def test_ai_errors_and_unstructured_answers_never_approve_an_entry(self):
        response_bodies = [[], None, {"content": "invalid envelope"}, {"content": ["not a content block"]},
                           {"content": [{"type": "text", "text": "not JSON"}]},
                           {"content": [{"type": "text", "text": "[]"}]},
                           {"content": [{"type": "text", "text": "null"}]},
                           {"content": [{"type": "text", "text": '{"approve": "true"}'}]},
                           {"content": [{"type": "text", "text": '{"approve": false, "reason": "débil"}'}]}]
        asset = signals()(markets()[0], 4)
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-placeholder"}):
            for body in response_bodies:
                with self.subTest(body=body):
                    with patch("bot.service.httpx.AsyncClient") as client_class:
                        client = client_class.return_value.__aenter__.return_value
                        client.post = AsyncMock(return_value=httpx.Response(200, json=body))
                        approved, _detail = await self.bot.ai_verdict(asset)
                    self.assertFalse(approved)
            with patch("bot.service.httpx.AsyncClient") as client_class:
                client = client_class.return_value.__aenter__.return_value
                client.post = AsyncMock(side_effect=httpx.ConnectError("offline"))
                approved, _detail = await self.bot.ai_verdict(asset)
                self.assertFalse(approved)
            with patch("bot.service.httpx.AsyncClient") as client_class:
                client = client_class.return_value.__aenter__.return_value
                client.post = AsyncMock(return_value=httpx.Response(429))
                approved, _detail = await self.bot.ai_verdict(asset)
                self.assertFalse(approved)

    async def test_optional_ai_veto_and_three_call_limit_preserve_cost_and_risk_bounds(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-placeholder"}):
            await self.bot.settings({"ai_enabled": True, "max_positions": 8})
        all_buys = {f"{symbol}/USD": "buy" for symbol, _, _ in ASSETS}
        with patch.object(self.bot, "ai_verdict", AsyncMock(return_value=(False, "Señal débil"))) as ai:
            vetoed = await self.open_positions(all_buys)
            self.assertEqual(ai.await_count, 3)
            self.assertEqual(vetoed["positions"], [])
            self.assertEqual(vetoed["portfolio"]["cash"], 10000)
        with patch.object(self.bot, "ai_verdict", AsyncMock(return_value=(True, "Señal admisible"))) as ai:
            approved = await self.open_positions(all_buys)
            self.assertEqual(ai.await_count, 3)
            self.assertEqual(len(approved["positions"]), 3)
            self.assertGreaterEqual(approved["portfolio"]["cash"], 0)

    async def test_failed_combined_settings_change_is_atomic(self):
        with patch("bot.service.fetch_demo_markets", AsyncMock(return_value=markets())), \
                patch("bot.service.analyze_market", side_effect=signals({"NONE": "wait"})):
            await self.bot.cycle()
        before = copy.deepcopy(self.bot.state)
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "ANTHROPIC_API_KEY"):
                await self.bot.settings({"market_source": "kraken", "ai_enabled": True})
        self.assertEqual(self.bot.state, before)


if __name__ == "__main__":
    unittest.main()
