#!/usr/bin/env bash
# Run the Chelsea Transfer Tracker WITHOUT Docker.
# Uses a local Python virtualenv. Good for first-run smoke testing.
#
# Usage:
#   ./run_local.sh

set -euo pipefail
cd "$(dirname "$0")"

cyan()  { printf "\033[36m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
red()   { printf "\033[31m%s\033[0m\n" "$*" >&2; }

# 1. Sanity
if [[ ! -f .env ]]; then
  red ".env not found. Run: cp .env.example .env  and fill in GROQ_API_KEY."
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  red "python3 not found. Install Python 3.10+ from https://www.python.org/downloads/"
  exit 1
fi

# 2. Virtualenv
if [[ ! -d .venv ]]; then
  cyan "==> Creating virtualenv (.venv)"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

cyan "==> Installing dependencies (first run takes ~1 min)"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# 3. Load .env into shell, force local storage so no AWS is needed
set -a; . ./.env; set +a
export STORAGE_BACKEND=local
export OUTPUT_DIR="$PWD/data"
mkdir -p "$OUTPUT_DIR"

# 4. Run
cyan "==> Running pipeline (live RSS + Groq)"
PYTHONPATH=. python3 -m src.main

# 5. Report
if [[ -f "$OUTPUT_DIR/chelsea_tracker.csv" ]]; then
  rows=$(($(wc -l < "$OUTPUT_DIR/chelsea_tracker.csv") - 1))
  green "==> Done. chelsea_tracker.csv has $rows rows -> $OUTPUT_DIR/chelsea_tracker.csv"
  echo
  echo "Preview:"
  head -3 "$OUTPUT_DIR/chelsea_tracker.csv"
else
  red "==> chelsea_tracker.csv was NOT created. Check logs above."
  exit 1
fi
