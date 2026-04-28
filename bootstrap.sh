#!/usr/bin/env bash
# Chelsea Transfer Tracker - one-command bootstrap (zero-cost stack).
#
# What it does:
#   1. Verifies you have a .env with GROQ_API_KEY.
#   2. Builds the Docker image.
#   3. Runs one full pipeline execution and writes the CSV to ./data/.
#   4. Prints next steps.
#
# Usage:
#   cp .env.example .env       # then fill in GROQ_API_KEY
#   ./bootstrap.sh

set -euo pipefail

cd "$(dirname "$0")"

cyan()  { printf "\033[36m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
red()   { printf "\033[31m%s\033[0m\n" "$*" >&2; }
warn()  { printf "\033[33m%s\033[0m\n" "$*"; }

# -- 1. Sanity checks ---------------------------------------------------------
cyan "==> [1/4] Checking prerequisites"

if ! command -v docker >/dev/null 2>&1; then
  red "Docker is not installed. Install Docker Desktop from https://www.docker.com/products/docker-desktop"
  exit 1
fi

if [[ ! -f .env ]]; then
  red ".env file not found."
  echo "    Run:  cp .env.example .env  and fill in GROQ_API_KEY."
  exit 1
fi

# shellcheck disable=SC1091
set -a; . ./.env; set +a
val="${GROQ_API_KEY:-}"
if [[ -z "$val" || "$val" == "your_groq_api_key" || "$val" == "paste_your_groq_key_here" ]]; then
  red "Missing or placeholder GROQ_API_KEY in .env."
  echo "    Get a free key from https://console.groq.com/keys (no credit card required)"
  exit 1
fi
green "    .env looks valid (GROQ_API_KEY set)"

# -- 2. Build image -----------------------------------------------------------
cyan "==> [2/4] Building Docker image (chelsea-transfer-tracker:dev)"
docker build --quiet -t chelsea-transfer-tracker:dev . >/dev/null
green "    Image built"

# -- 3. Run pipeline once -----------------------------------------------------
cyan "==> [3/4] Running scraper container (this may take ~1-3 minutes)"
mkdir -p ./data

# Default to local storage so first run never needs AWS.
RUN_BACKEND="${STORAGE_BACKEND:-local}"
if [[ "$RUN_BACKEND" != "local" && -z "${STORAGE_BUCKET:-}" ]]; then
  warn "    STORAGE_BACKEND=$RUN_BACKEND but STORAGE_BUCKET is empty - falling back to local for this run."
  RUN_BACKEND=local
fi

docker run --rm \
  --env-file .env \
  -e STORAGE_BACKEND="$RUN_BACKEND" \
  -e OUTPUT_DIR=/data \
  -v "$PWD/data:/data" \
  chelsea-transfer-tracker:dev

# -- 4. Done ------------------------------------------------------------------
cyan "==> [4/4] Done"
if [[ -f ./data/chelsea_tracker.csv ]]; then
  rows=$(($(wc -l < ./data/chelsea_tracker.csv) - 1))
  green "    chelsea_tracker.csv created with $rows rows -> ./data/chelsea_tracker.csv"
else
  red "    chelsea_tracker.csv was NOT created. Check logs above."
  exit 1
fi

cat <<'NEXT'

Next steps:
  - Inspect the CSV:   head -20 ./data/chelsea_tracker.csv
  - Re-run anytime:    ./bootstrap.sh   (idempotent, only adds new rows)
  - Push to GitHub:    git init && git add . && git commit -m "init" && git remote add origin <your-repo> && git push -u origin main
  - Deploy to Harness: follow Steps 1-7 in README.md (only secret needed: groq_api_key)

NEXT
