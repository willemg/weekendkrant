#!/bin/bash
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Install this wrapper and ci_runner.py together under /home/weekendkrant/ci/bin.
config="${WEEKENDKRANT_CI_CONFIG:-/home/weekendkrant/ci/env}"
if [[ -f "$config" ]]; then
    set -a
    source "$config"
    set +a
fi
state_dir="${WEEKENDKRANT_CI_STATE:-/home/weekendkrant/ci}"
ci_python="${WEEKENDKRANT_CI_PYTHON:-/home/weekendkrant/ci/venv/bin/python}"
cd "$state_dir"
exec "$ci_python" "$script_dir/ci_runner.py" --state "$state_dir" run \
    --python "$ci_python" \
    --source "${WEEKENDKRANT_CI_SOURCE:-https://github.com/willemg/weekendkrant.git}"
