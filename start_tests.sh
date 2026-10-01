#!/bin/bash
set -euo pipefail

cd /home/weekendkrant/app
exec /home/weekendkrant/app/.venv/bin/python -m unittest discover -s tests -v
