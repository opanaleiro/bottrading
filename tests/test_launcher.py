"""Local launcher contracts without starting a server or installing packages."""
from __future__ import annotations

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import io
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

import run_bot


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.lock = self.root / "requirements.lock"
        self.lock.write_text("fastapi==0.115.12\nuvicorn==0.34.2\nhttpx==0.28.1\n")
        self.venv = self.root / ".venv"
        self.executable = run_bot.python_in_venv(self.venv)
        self.data = self.root / "account"
        self.addCleanup(self.directory.cleanup)

    def make_python(self):
        self.executable.parent.mkdir(parents=True)
        self.executable.touch()

    def launch(self, extra=(), *, existing=False, available=True, process=None,
               clock=None):
        """Invoke the CLI while replacing all process, network and browser I/O."""
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(patch.object(run_bot, "ROOT", self.root))
            stack.enter_context(patch.object(run_bot.sys, "version_info", (3, 12, 0)))
            stack.enter_context(redirect_stdout(self.stdout))
            stack.enter_context(redirect_stderr(self.stderr))
            probes = stack.enter_context(patch.object(run_bot, "is_vector"))
            probes.side_effect = [True] if existing else [False, True]
            ports = stack.enter_context(patch.object(run_bot, "port_available", return_value=available))
            prepare = stack.enter_context(patch.object(run_bot, "prepare_python", return_value=self.executable))
            popen = stack.enter_context(patch.object(run_bot.subprocess, "Popen", return_value=process))
            browser = stack.enter_context(patch.object(run_bot.webbrowser, "open", return_value=True))
            stack.enter_context(patch.object(run_bot.time, "monotonic", side_effect=clock,
                                           return_value=0))
            sleeper = stack.enter_context(patch.object(run_bot.time, "sleep"))
            result = run_bot.main(["--data-dir", str(self.data), *extra])
        return result, {"probes": probes, "ports": ports, "prepare": prepare,
                        "popen": popen, "browser": browser, "sleep": sleeper}

    def finished_child(self):
        process = MagicMock()
        process.poll.return_value = None
        process.returncode = 0

        def finish(*args, **kwargs):
            process.poll.return_value = 0
            return 0

        process.wait.side_effect = finish
        return process

    def test_existing_vector_reuses_server_and_account_without_installing(self):
        self.data.mkdir()
        account = self.data / "paper.sqlite3"
        account.write_bytes(b"existing account must remain untouched")
        result, calls = self.launch(existing=True)
        self.assertEqual(result, 0)
        calls["prepare"].assert_not_called()
        calls["popen"].assert_not_called()
        calls["ports"].assert_not_called()
        calls["browser"].assert_called_once_with("http://127.0.0.1:8000")
        self.assertEqual(account.read_bytes(), b"existing account must remain untouched")

    def test_occupied_non_vector_port_is_reported_without_process_or_install(self):
        result, calls = self.launch(available=False)
        self.assertEqual(result, 1)
        calls["prepare"].assert_not_called()
        calls["popen"].assert_not_called()
        calls["browser"].assert_not_called()
        self.assertFalse(self.data.exists())
        self.assertIn("No se ha cerrado", self.stderr.getvalue())
        self.assertIn("8000", self.stderr.getvalue())

    def test_no_browser_applies_to_both_existing_and_new_servers(self):
        for existing in (True, False):
            with self.subTest(existing=existing):
                process = self.finished_child()
                result, calls = self.launch(["--no-browser"], existing=existing, process=process)
                self.assertEqual(result, 0)
                calls["browser"].assert_not_called()
                if existing:
                    calls["popen"].assert_not_called()
                else:
                    process.wait.assert_called_once_with()
                    process.terminate.assert_not_called()

    def test_new_server_uses_loopback_kraken_and_explicit_account_without_erasing_it(self):
        self.data.mkdir()
        account = self.data / "paper.sqlite3"
        account.write_bytes(b"saved paper account")
        process = self.finished_child()
        result, calls = self.launch(["--port", "8002", "--no-install"], process=process)
        self.assertEqual(result, 0)
        calls["prepare"].assert_called_once_with(self.venv, install=False)
        command = calls["popen"].call_args.args[0]
        self.assertEqual(command, [str(self.executable), "-m", "uvicorn", "bot.app:app",
                                   "--host", "127.0.0.1", "--port", "8002"])
        options = calls["popen"].call_args.kwargs
        self.assertEqual(options["cwd"], self.root)
        self.assertEqual(options["env"]["BOT_DB_PATH"], str(account.resolve()))
        self.assertEqual(options["env"]["BOT_INITIAL_SOURCE"], "kraken")
        calls["browser"].assert_called_once_with("http://127.0.0.1:8002")
        self.assertEqual(account.read_bytes(), b"saved paper account")

    def test_interruption_terminates_only_owned_child_and_keeps_account(self):
        self.data.mkdir()
        account = self.data / "paper.sqlite3"
        account.write_bytes(b"saved trades")
        process = MagicMock()
        process.poll.return_value = None
        process.wait.side_effect = [KeyboardInterrupt(), 0]
        result, calls = self.launch(["--no-browser"], process=process)
        self.assertEqual(result, 0)
        calls["popen"].assert_called_once()
        process.terminate.assert_called_once_with()
        self.assertEqual(process.wait.call_args_list[-1].kwargs, {"timeout": 30})
        process.kill.assert_not_called()
        self.assertEqual(account.read_bytes(), b"saved trades")

    def test_startup_timeout_reaps_child_and_reports_failure(self):
        process = MagicMock()
        process.poll.return_value = None
        process.wait.return_value = 0
        result, calls = self.launch(["--no-browser"], process=process, clock=[0, 31])
        self.assertEqual(result, 1)
        self.assertIn("no terminó de arrancar", self.stderr.getvalue())
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=30)
        process.kill.assert_not_called()
        calls["browser"].assert_not_called()

    def test_unresponsive_owned_child_is_killed_after_graceful_shutdown_timeout(self):
        process = MagicMock()
        process.poll.return_value = None
        process.wait.side_effect = [KeyboardInterrupt(), subprocess.TimeoutExpired("uvicorn", 30), 0]
        result, _ = self.launch(["--no-browser"], process=process)
        self.assertEqual(result, 0)
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertEqual(process.wait.call_count, 3)

    def test_missing_venv_with_no_install_fails_before_creating_any_environment(self):
        with patch.object(run_bot, "ROOT", self.root), \
                patch.object(run_bot.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "Falta .venv"):
                run_bot.prepare_python(self.venv, install=False)
        run.assert_not_called()
        self.assertFalse(self.venv.exists())

    def test_missing_dependencies_with_no_install_do_not_invoke_pip(self):
        self.make_python()
        marker = self.venv / ".vector-lock-sha256"
        marker.write_text(hashlib.sha256(self.lock.read_bytes()).hexdigest() + "\n")
        with patch.object(run_bot, "ROOT", self.root), \
                patch.object(run_bot.subprocess, "run", return_value=MagicMock(returncode=1)) as run:
            with self.assertRaisesRegex(RuntimeError, "Faltan dependencias"):
                run_bot.prepare_python(self.venv, install=False)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][1], "-c")

    def test_successful_install_records_exact_lock_digest_and_next_run_skips_pip(self):
        self.make_python()
        original = self.lock.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        with patch.object(run_bot, "ROOT", self.root), \
                redirect_stdout(io.StringIO()), \
                patch.object(run_bot.subprocess, "run", return_value=MagicMock(returncode=0)) as run:
            self.assertEqual(run_bot.prepare_python(self.venv), self.executable)
            self.assertEqual(run.call_count, 2)
            install = run.call_args.args[0]
            self.assertEqual(install[:4], [str(self.executable), "-m", "pip", "install"])
            self.assertEqual(install[-2:], ["--requirement", str(self.lock)])
            self.assertNotIn("--trusted-host", install)
            self.assertEqual(run.call_args.kwargs["check"], True)
            self.assertEqual((self.venv / ".vector-lock-sha256").read_text().strip(), digest)
            run.reset_mock()
            run_bot.prepare_python(self.venv)
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0][1], "-c")
        self.assertEqual(self.lock.read_bytes(), original)

    def test_changed_lock_reinstalls_and_failed_install_keeps_previous_marker(self):
        self.make_python()
        marker = self.venv / ".vector-lock-sha256"
        marker.write_text("previous successful lock\n")
        with patch.object(run_bot, "ROOT", self.root), \
                redirect_stdout(io.StringIO()), \
                patch.object(run_bot.subprocess, "run", side_effect=[MagicMock(returncode=0),
                    subprocess.CalledProcessError(1, ["pip", "install"])]) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                run_bot.prepare_python(self.venv)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(marker.read_text(), "previous successful lock\n")

    def test_server_probe_requires_vector_page_and_paper_health_and_bypasses_proxy(self):
        for health, page, expected in (
            ({"status": "ok", "mode": "paper"}, b"<title>Vector</title>", True),
            ({"status": "ok", "mode": "live"}, b"<title>Vector</title>", False),
            ({"status": "ok", "mode": "paper"}, b"<title>Another application</title>", False),
        ):
            with self.subTest(health=health, page=page):
                opener = MagicMock()
                page_response = MagicMock()
                page_response.__enter__.return_value.read.return_value = page
                opener.open.side_effect = [MagicMock(), page_response]
                with patch.object(run_bot.urllib.request, "build_opener", return_value=opener) as build, \
                        patch.object(run_bot.json, "load", return_value=health):
                    self.assertEqual(run_bot.is_vector("http://127.0.0.1:8000"), expected)
                self.assertEqual(build.call_args.args[0].proxies, {})
                self.assertEqual(opener.open.call_args_list[0].args[0],
                                 "http://127.0.0.1:8000/api/health")


if __name__ == "__main__":
    unittest.main()
