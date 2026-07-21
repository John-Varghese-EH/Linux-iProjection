#!/usr/bin/env bash
# epsonctl — Built by John Varghese (J0X) | https://github.com/John-Varghese-EH
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
    python3 -m venv .venv --system-site-packages
    .venv/bin/pip install -e .
fi
exec .venv/bin/epsonctl "$@"
