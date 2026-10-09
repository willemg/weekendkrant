#!/bin/bash
set -euo pipefail

export TIKTOKEN_CACHE_DIR=/home/weekendkrant/.cache/tiktoken

cd /home/weekendkrant/app
exec /home/weekendkrant/app/.venv/bin/python -m unittest discover -s tests
