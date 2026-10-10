#!/usr/bin/env python3
"""Arranque local: prepara Python, inicia Vector y abre el navegador."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent


def python_in_venv(directory: Path) -> Path:
    return directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def prepare_python(directory: Path, install: bool = True) -> Path:
    """Install from the committed version lock; no paid providers or keys."""
    executable = python_in_venv(directory)
    lock = ROOT / "requirements.lock"
    digest = hashlib.sha256(lock.read_bytes()).hexdigest()
    marker = directory / ".vector-lock-sha256"
    valid_marker = marker.exists() and marker.read_text().strip() == digest
    if not executable.exists():
        if not install:
            raise RuntimeError("Falta .venv. Ejecuta el lanzador sin --no-install la primera vez.")
        print("Primera puesta en marcha: preparando Python…", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(directory)], check=True, cwd=ROOT)
    dependency_check = subprocess.run([str(executable), "-c", "import fastapi, uvicorn, httpx"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT)
    if dependency_check.returncode != 0 or (not valid_marker and install):
        if not install:
            raise RuntimeError("Faltan dependencias. Ejecuta el lanzador sin --no-install.")
        print("Instalando las dependencias gratuitas. Necesitas conexión a internet…", flush=True)
        subprocess.run([str(executable), "-m", "pip", "install", "--cache-dir", str(ROOT / ".local" / "pip-cache"),
                        "--requirement", str(lock)], check=True, cwd=ROOT)
        marker.write_text(digest + "\n")
    return executable


def is_vector(address: str) -> bool:
    # The probe is strictly local; a corporate HTTP proxy should not handle it.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(address + "/api/health", timeout=2) as response:
            health = json.load(response)
        with opener.open(address + "/", timeout=2) as response:
            html = response.read(1000).decode("utf-8")
        return health.get("status") == "ok" and health.get("mode") == "paper" and "Vector" in html
    except (urllib.error.URLError, OSError, ValueError, AttributeError):
        return False


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            listener.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Abre Vector: precios de Kraken y operaciones ficticias.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="No abrir el navegador automáticamente.")
    parser.add_argument("--no-install", action="store_true", help="Usar dependencias ya instaladas.")
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".local", help="Carpeta de la cuenta de simulación.")
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        print("Usa un puerto entre 1024 y 65535.", file=sys.stderr)
        return 1
    if sys.version_info[:2] != (3, 12):
        print("Necesitas Python 3.12. Instalador oficial para Windows: https://www.python.org/downloads/release/python-31210/", file=sys.stderr)
        return 1
    address = f"http://127.0.0.1:{args.port}"
    if is_vector(address):
        print(f"Vector ya está abierto en este ordenador: {address}", flush=True)
        if not args.no_browser:
            webbrowser.open(address)
        return 0
    if not port_available(args.port):
        print(f"Otro programa usa el puerto {args.port}. No se ha cerrado. Prueba --port 8002.", file=sys.stderr)
        return 1
    process = None
    try:
        args.data_dir = args.data_dir.resolve()
        args.data_dir.mkdir(parents=True, exist_ok=True)
        executable = prepare_python(ROOT / ".venv", install=not args.no_install)
        environment = os.environ.copy()
        environment["BOT_DB_PATH"] = str(args.data_dir / "paper.sqlite3")
        environment["BOT_INITIAL_SOURCE"] = "kraken"
        print("\nVector · Precios reales de Kraken; cuenta y operaciones ficticias.", flush=True)
        print("Claude está desactivado en las cuentas nuevas. No se necesitan claves.", flush=True)
        print("Deja esta ventana abierta. Cierra el programa con Ctrl+C.", flush=True)
        process = subprocess.Popen([str(executable), "-m", "uvicorn", "bot.app:app", "--host", "127.0.0.1",
                                    "--port", str(args.port)], cwd=ROOT, env=environment)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and process.poll() is None:
            if is_vector(address):
                print(f"\nPanel local: {address}\nPulsa «Iniciar bot» para comenzar. El panel arranca pausado.", flush=True)
                if not args.no_browser:
                    if not webbrowser.open(address):
                        print("No se abrió el navegador. Copia la dirección de arriba en el navegador de ESTE ordenador.")
                return process.wait()
            time.sleep(0.25)
        if process.poll() is not None:
            return process.returncode or 1
        print("El servidor no terminó de arrancar. Revisa los mensajes de esta ventana.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCerrando Vector. La cuenta queda guardada; los stops dejan de vigilarse.", flush=True)
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"No se pudo iniciar Vector: {error}", file=sys.stderr)
        return 1
    finally:
        # Stop only the process this launcher created, preserving the SQLite account.
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
