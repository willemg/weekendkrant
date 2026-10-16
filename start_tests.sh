#!/bin/bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
export TIKTOKEN_CACHE_DIR="${TIKTOKEN_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/tiktoken}"
# Keep bibib's local environment while supporting any checkout/venv.
if [[ -x .venv/bin/python ]]; then
    python=.venv/bin/python
else
    python=python3
fi
exec "$python" test_impact.py "$@"
