#!/bin/bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
export TIKTOKEN_CACHE_DIR="${TIKTOKEN_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/tiktoken}"
# Keep bibib's local environment while supporting any checkout/venv.
if [[ -n "${WEEKENDKRANT_TEST_PYTHON:-}" ]]; then
    python="$WEEKENDKRANT_TEST_PYTHON"
elif [[ -x .venv/bin/python ]]; then
    python=.venv/bin/python
else
    python=python3
fi
if [[ "${1:-}" == "--plugin" && "$#" == 1 ]]; then
    npm --prefix plugin/weekendkrant_ingress test
    exec "$python" plugin/weekendkrant_ingress/tests/bridge_backend.py
fi
exec "$python" test_runner.py "$@"
