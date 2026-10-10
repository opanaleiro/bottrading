"""HTTP contract, validation and cross-origin protections without network access."""
from __future__ import annotations

import copy
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from bot.app import create_app
from bot.market import MarketDataError


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / "api.sqlite3"
        self.app = create_app(self.path)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.directory.cleanup()

    def state(self):
        response = self.client.get("/api/state")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_initial_account_health_and_browser_security_headers(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.json(), {"status": "ok", "mode": "paper"})
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        state = self.state()
        self.assertEqual(state["portfolio"]["equity"], 10000)
        self.assertEqual(state["positions"], [])
        self.assertFalse(state["settings"]["ai_enabled"])
        self.assertFalse(state["meta"]["running"])
        self.assertEqual(state["meta"]["mode"], "paper")

    def test_manual_demo_cycle_runs_real_engine_without_paid_api_or_public_network(self):
        with patch("bot.service.fetch_kraken_markets", AsyncMock()) as real_feed, \
                patch.object(self.app.state.bot, "ai_verdict", AsyncMock()) as ai:
            response = self.client.post("/api/cycle")
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual(len(result["assets"]), 16)
            self.assertEqual(len({asset["symbol"] for asset in result["assets"]}), 16)
            self.assertGreaterEqual(result["portfolio"]["cash"], 0)
            self.assertEqual(result["meta"]["market_source"], "demo")
            self.assertEqual(result["meta"]["ai_provider"], "rules")
            real_feed.assert_not_awaited()
            ai.assert_not_awaited()

    def test_settings_round_trip_and_rejection_of_unknown_or_live_fields(self):
        update = {"aggressiveness": 8, "operation_mode": "close_only", "cycle_seconds": 120,
                  "max_positions": 2, "daily_loss_limit_pct": 2.5}
        result = self.client.post("/api/settings", json=update)
        self.assertEqual(result.status_code, 200)
        for key, value in update.items():
            self.assertEqual(self.state()["settings"][key], value)
        before = self.state()["settings"]
        for payload in ({"live_mode": True}, {"mode": "live"}, {"exchange_api_key": "not-a-key"},
                        {"aggressiveness": 4, "unknown": "field"}):
            with self.subTest(payload=payload):
                response = self.client.post("/api/settings", json=payload)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(self.state()["settings"], before)

    def test_settings_ranges_and_enums_cannot_corrupt_existing_configuration(self):
        invalid = [{"aggressiveness": 0}, {"aggressiveness": 11}, {"aggressiveness": 1.5},
                   {"operation_mode": "live"}, {"market_source": "unknown"},
                   {"cycle_seconds": 29}, {"cycle_seconds": 3601}, {"max_positions": 0},
                   {"max_positions": 9}, {"daily_loss_limit_pct": 0},
                   {"daily_loss_limit_pct": 11}, {"daily_loss_limit_pct": "NaN"},
                   {"daily_loss_limit_pct": "Infinity"}]
        before = copy.deepcopy(self.state()["settings"])
        for payload in invalid:
            with self.subTest(payload=payload):
                response = self.client.post("/api/settings", json=payload)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(self.state()["settings"], before)

    def test_ai_activation_requires_securely_injected_key(self):
        with patch.dict(os.environ, {}, clear=True):
            response = self.client.post("/api/settings", json={"ai_enabled": True})
            self.assertEqual(response.status_code, 400)
            self.assertIn("ANTHROPIC_API_KEY", response.json()["detail"])
            self.assertFalse(self.state()["settings"]["ai_enabled"])
            self.assertFalse(self.state()["meta"]["ai_available"])

    def test_failed_real_data_cycle_is_an_actionable_error_without_demo_substitution(self):
        self.assertEqual(self.client.post("/api/settings", json={"market_source": "kraken"}).status_code, 200)
        with patch("bot.service.fetch_kraken_markets", AsyncMock(side_effect=MarketDataError("offline"))), \
                patch("bot.service.fetch_demo_markets", AsyncMock()) as demo:
            response = self.client.post("/api/cycle")
            self.assertEqual(response.status_code, 400)
            demo.assert_not_awaited()
        state = self.state()
        self.assertEqual(state["meta"]["status"], "Error de datos")
        self.assertEqual(state["positions"], [])
        self.assertEqual(state["portfolio"]["equity"], 10000)
        self.assertEqual(state["settings"]["market_source"], "kraken")

    def test_start_stop_and_running_reset_guard(self):
        # Block the scheduler itself, so this API test cannot open a background trade.
        with patch.object(self.app.state.bot, "loop", AsyncMock()):
            started = self.client.post("/api/start")
            self.assertEqual(started.status_code, 200)
            self.assertTrue(started.json()["meta"]["running"])
            self.assertEqual(self.client.post("/api/cycle").status_code, 400)
            self.assertEqual(self.client.post("/api/reset", json={"initial_balance": 5000}).status_code, 400)
            stopped = self.client.post("/api/stop")
            self.assertEqual(stopped.status_code, 200)
            self.assertFalse(stopped.json()["meta"]["running"])
        reset = self.client.post("/api/reset", json={"initial_balance": 5000})
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(reset.json()["portfolio"]["equity"], 5000)

    def test_reset_and_news_inputs_are_validated_before_mutation(self):
        for payload in ({"initial_balance": 99}, {"initial_balance": 1000000001},
                        {"initial_balance": "NaN"}, {"initial_balance": "Infinity"},
                        {"initial_balance": 5000, "live_mode": True}):
            with self.subTest(reset=payload):
                self.assertEqual(self.client.post("/api/reset", json=payload).status_code, 422)
                self.assertEqual(self.state()["portfolio"]["equity"], 10000)
        for payload in ({"text": "abc"}, {"text": "      "}, {"text": "x" * 2001},
                        {"text": "texto correcto", "api_key": "not-a-key"}):
            with self.subTest(news=payload):
                self.assertEqual(self.client.post("/api/news", json=payload).status_code, 422)
                self.assertEqual(self.state()["news"], [])
        response = self.client.post("/api/news", json={"text": "  Titular manual de prueba  "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["news"][0]["text"], "Titular manual de prueba")
        unknown = self.client.post("/api/positions/not-a-position/close")
        self.assertEqual(unknown.status_code, 400)
        self.assertIn("no encontrada", unknown.json()["detail"])

    def test_hostile_cross_origin_mutations_are_rejected_without_side_effects(self):
        origins = ["https://evil.example", "http://testserver.evil.example", "null",
                   "https://testserver", "javascript://testserver", "http://[malformed"]
        for origin in origins:
            with self.subTest(origin=origin):
                before = self.state()
                response = self.client.post("/api/reset", json={"initial_balance": 5555}, headers={"origin": origin})
                self.assertEqual(response.status_code, 403, response.text)
                self.assertEqual(self.state(), before)
        self.assertEqual(self.client.post("/api/reset", json={"initial_balance": 5555},
                                         headers={"origin": "http://testserver"}).status_code, 200)
        self.assertEqual(self.state()["portfolio"]["equity"], 5555)

    def test_non_json_form_input_cannot_mutate_settings_or_reset(self):
        before = self.state()
        self.assertEqual(self.client.post("/api/reset", data={"initial_balance": "5555"}).status_code, 422)
        self.assertEqual(self.client.post("/api/settings", data={"ai_enabled": "true"}).status_code, 422)
        self.assertEqual(self.state(), before)

    def test_account_persists_across_app_recreation_and_starts_paused(self):
        self.client.post("/api/reset", json={"initial_balance": 4321})
        self.client.post("/api/settings", json={"aggressiveness": 6})
        self.client.post("/api/news", json={"text": "Contexto persistente de prueba"})
        self.client.__exit__(None, None, None)
        self.app = create_app(self.path)
        self.client = TestClient(self.app)
        self.client.__enter__()
        result = self.state()
        self.assertEqual(result["portfolio"]["equity"], 4321)
        self.assertEqual(result["settings"]["aggressiveness"], 6)
        self.assertEqual(result["news"][0]["text"], "Contexto persistente de prueba")
        self.assertFalse(result["meta"]["running"])


if __name__ == "__main__":
    unittest.main()
