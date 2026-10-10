#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
if command -v python3.12 >/dev/null 2>&1; then
  python3.12 run_bot.py
elif command -v python3 >/dev/null 2>&1; then
  python3 run_bot.py
else
  echo "Instala Python 3.12 y el paquete python3-venv de tu distribución."
fi
read -r -p "Pulsa Enter para cerrar esta ventana… "
