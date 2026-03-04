#!/usr/bin/env bash
# Infosphere Converters — Linux/Crostini starter
# Gebruik: bash start.sh   of   ./start.sh (na chmod +x start.sh)

cd "$(dirname "$0")"

if command -v python3 &>/dev/null; then
    python3 web_ui.py
elif command -v python &>/dev/null; then
    python web_ui.py
else
    echo "Python niet gevonden. Installeer Python 3 via je pakketbeheerder."
    echo "  Debian/Ubuntu/Crostini: sudo apt install python3"
    exit 1
fi
