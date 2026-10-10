"""Real-price local accounts persist without silently replacing existing data."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from bot.app import create_app
from bot.service import PaperBot


class LocalSettingsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / "paper.sqlite3"
        self.bot = None

    async def asyncTearDown(self):
        if self.bot is not None:
            await self.bot.shutdown()
        self.directory.cleanup()

    async def test_new_kraken_account_persists_source_and_starts_paused_without_ai(self):
        self.bot = PaperBot(self.path, initial_source="kraken")
        state = self.bot.snapshot()
        self.assertEqual(state["settings"]["market_source"], "kraken")
        self.assertEqual(state["portfolio"]["equity"], 10000)
        self.assertFalse(state["meta"]["running"])
        self.assertFalse(state["settings"]["ai_enabled"])
        self.assertEqual(state["positions"], [])
        self.assertEqual(state["trades"], [])
        await self.bot.shutdown()
        self.bot = PaperBot(self.path)
        self.assertEqual(self.bot.snapshot()["settings"]["market_source"], "kraken")

    async def test_initial_source_never_overrides_existing_account_or_history(self):
        self.bot = PaperBot(self.path, initial_source="demo")
        await self.bot.reset(4321)
        await self.bot.settings({"aggressiveness": 7, "max_positions": 2, "cycle_seconds": 120})
        await self.bot.add_news("Contexto guardado del usuario")
        # Persisted history can exist even while a new launcher requests Kraken.
        self.bot.state["trades"] = [{"id": "saved", "side": "long", "pnl": 12.0}]
        self.bot.state["cash"] = 4333.0
        self.bot.state["meta"]["running"] = True
        self.bot.save()
        expected = copy.deepcopy(self.bot.state)
        self.bot.connection.close()
        self.bot = PaperBot(self.path, initial_source="kraken")
        for key in ("settings", "trades", "news", "cash", "equity_history", "events"):
            self.assertEqual(self.bot.state[key], expected[key])
        self.assertEqual(self.bot.state["settings"]["market_source"], "demo")
        self.assertFalse(self.bot.state["meta"]["running"])

    async def test_invalid_initial_source_creates_neither_parent_directory_nor_database(self):
        invalid_path = self.path.parent / "not-created" / "paper.sqlite3"
        for source in ("live", "Kraken", "", None):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, "demo o kraken"):
                    PaperBot(invalid_path, initial_source=source)
                self.assertFalse(invalid_path.parent.exists())
                self.assertFalse(invalid_path.exists())

    async def test_reset_changes_balance_and_clears_account_but_preserves_local_settings(self):
        self.bot = PaperBot(self.path, initial_source="kraken")
        await self.bot.settings({"aggressiveness": 7, "max_positions": 5, "cycle_seconds": 120,
                                 "daily_loss_limit_pct": 2.0, "operation_mode": "close_only"})
        await self.bot.add_news("Texto manual que no debe quedar tras reiniciar")
        self.bot.state.update({"positions": [{"id": "open", "notional": 500, "unrealized_pnl": -10}],
                               "trades": [{"id": "closed", "side": "short", "pnl": -30}],
                               "assets": [{"symbol": "BTC/USD"}], "cash": 9420.0,
                               "fees_paid": 20.0, "cycle_count": 20, "daily_halted": True})
        self.bot.state["equity_history"].append({"time": "2026-01-01", "equity": 9910})
        self.bot.save()
        expected_settings = copy.deepcopy(self.bot.state["settings"])
        expected_settings["initial_balance"] = 2500
        state = await self.bot.reset(2500)
        self.assertEqual(state["settings"], expected_settings)
        self.assertFalse(state["settings"]["ai_enabled"])
        self.assertFalse(state["meta"]["running"])
        self.assertFalse(state["meta"]["risk_halted"])
        for key in ("positions", "trades", "assets", "news"):
            self.assertEqual(state[key], [])
        for key in ("equity", "cash"):
            self.assertEqual(state["portfolio"][key], 2500)
        for key in ("realized_pnl", "unrealized_pnl", "fees_paid", "total_return_pct"):
            self.assertEqual(state["portfolio"][key], 0)
        self.assertEqual(len(state["equity_history"]), 1)
        self.assertEqual(state["equity_history"][0]["equity"], 2500)
        await self.bot.shutdown()
        self.bot = PaperBot(self.path)
        self.assertEqual(self.bot.state["settings"], expected_settings)
        self.assertEqual(self.bot.snapshot()["portfolio"]["equity"], 2500)

    async def test_failed_reset_preserves_memory_and_persisted_account(self):
        self.bot = PaperBot(self.path, initial_source="kraken")
        await self.bot.reset(5000)
        await self.bot.add_news("El reinicio fallido debe preservar este texto")
        expected = copy.deepcopy(self.bot.state)
        with patch.object(self.bot, "save", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(ValueError, "cuenta permanece intacta"):
                await self.bot.reset(2500)
        self.assertEqual(self.bot.state, expected)
        self.bot.connection.close()
        self.bot = PaperBot(self.path, initial_source="demo")
        self.assertEqual(self.bot.state, expected)


class LocalApplicationSettingsTests(unittest.TestCase):
    def test_application_honors_launcher_environment_for_new_account_only(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "local.sqlite3"
            with patch.dict(os.environ, {"BOT_DB_PATH": str(path), "BOT_INITIAL_SOURCE": "kraken"}):
                with TestClient(create_app()) as client:
                    state = client.get("/api/state").json()
                    self.assertEqual(state["settings"]["market_source"], "kraken")
                    self.assertFalse(state["settings"]["ai_enabled"])
                    self.assertEqual(client.post("/api/reset", json={"initial_balance": 6789}).status_code, 200)
            with patch.dict(os.environ, {"BOT_DB_PATH": str(path), "BOT_INITIAL_SOURCE": "demo"}):
                with TestClient(create_app()) as client:
                    state = client.get("/api/state").json()
                    self.assertEqual(state["settings"]["market_source"], "kraken")
                    self.assertEqual(state["portfolio"]["equity"], 6789)
                    self.assertFalse(state["meta"]["running"])


if __name__ == "__main__":
    unittest.main()
