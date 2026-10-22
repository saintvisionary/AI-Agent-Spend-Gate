#!/bin/bash
# start.command
# Double-click on a Mac to set up and open the AI Agent Spend Gate app.
# It only finds Python and runs start.py, which does the real setup.
# (Linux users: run ./start.sh instead.)
cd "$(dirname "$0")" || exit 1

if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
else
    echo "Python 3.10 or newer is needed, and it wasn't found."
    echo "Download it from https://www.python.org/downloads/ and double-click this file again."
    read -r -p "Press Enter to close."
    exit 1
fi

"$PYTHON" start.py "$@"
status=$?

# Keep the window open if something went wrong, so the message stays readable.
if [ $status -ne 0 ]; then
    echo
    read -r -p "The app stopped. The message above says what to do next. Press Enter to close."
fi
exit $status
