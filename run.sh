#!/usr/bin/env bash
# linux-iprojection - Built by John Varghese (J0X) | https://github.com/John-Varghese-EH
set -euo pipefail
cd "$(dirname "$0")"
glib-compile-resources --sourcedir=data data/linux_iprojection.gresource.xml --target=data/linux_iprojection.gresource 2>/dev/null || true
if [ ! -d .venv ]; then
    python3 -m venv .venv --system-site-packages
    .venv/bin/pip install -e .
fi
exec env PYTHONPATH=src .venv/bin/linux-iprojection "$@"
