#!/bin/sh
# Start Auto Typer on Linux (or ask a running copy to start/stop).
#   ./start_auto_typer.sh            start the app
#   ./start_auto_typer.sh --toggle   start/stop the last run (bind this to a key)
set -eu

here=$(cd "$(dirname "$0")" && pwd)

for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        python=$candidate
        break
    fi
done
: "${python:?Python 3 was not found - install it with: sudo apt install python3}"

if ! "$python" -c 'import tkinter' >/dev/null 2>&1; then
    echo "tkinter is missing - install it with: sudo apt install python3-tk" >&2
    exit 1
fi

exec "$python" "$here/auto_typer.pyw" "$@"
