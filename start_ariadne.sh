#!/bin/bash
set -euo pipefail

cd /home/weekendkrant/app
exec /home/weekendkrant/app/.venv/bin/python ariadne.py "$@"
