#!/bin/bash
# start.sh
# Linux: run ./start.sh to set up and open the AI Agent Spend Gate app.
# It only finds Python and runs start.py, which does the real setup.
cd "$(dirname "$0")" || exit 1

if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
else
    echo "Python 3.10 or newer is needed, and it wasn't found."
    echo "Install it with your package manager (for example: sudo apt install python3 python3-venv)."
    exit 1
fi

exec "$PYTHON" start.py "$@"
