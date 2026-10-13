#!/usr/bin/env bash
set -euo pipefail
LAB="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$LAB/../../.."
exec "$LAB/.venv/bin/python" -m app.labs.pretrade_ai demo
