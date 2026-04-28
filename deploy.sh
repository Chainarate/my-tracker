#!/usr/bin/env bash
# Chelsea Transfer Tracker - one-command deploy to GitHub Actions.
#
# What it does (all via the GitHub CLI - no browser clicks):
#   1. Verifies/installs gh CLI and auth.
#   2. git init + .gitignore check + initial commit.
#   3. Creates a private GitHub repo named chelsea-transfer-tracker.
#   4. Pushes main branch.
#   5. Sets GROQ_API_KEY as a repo secret (read from .env).
#   6. Triggers the first workflow run.
#   7. Tails the run logs until success/failure.
#
# Usage:
#   ./deploy.sh                       # private repo (default)
#   ./deploy.sh --public              # public repo
#   ./deploy.sh --name custom-name    # custom repo name

set -euo pipefail
cd "$(dirname "$0")"

cyan()  { printf "\033[36m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
red()   { printf "\033[31m%s\033[0m\n" "$*" >&2; }
yellow(){ printf "\033[33m%s\033[0m\n" "$*"; }

# ---- Args ------------------------------------------------------------------
VISIBILITY="--private"
REPO_NAME="chelsea-transfer-tracker"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --public)  VISIBILITY="--public"; shift ;;
    --private) VISIBILITY="--private"; shift ;;
    --name)    REPO_NAME="$2"; shift 2 ;;
    *)         red "Unknown arg: $1"; exit 1 ;;
  esac
done

# ---- 1. gh CLI presence + auth --------------------------------------------
cyan "==> [1/7] Verifying GitHub CLI"
if ! command -v gh >/dev/null 2>&1; then
  yellow "    gh CLI not installed. Installing via Homebrew..."
  if ! command -v brew >/dev/null 2>&1; then
    red "    Homebrew not found. Install from https://brew.sh first, then re-run."
    exit 1
  fi
  brew install gh
fi
if ! gh auth status >/dev/null 2>&1; then
  yellow "    Not logged in to GitHub. Launching gh auth login..."
  yellow "    (choose: GitHub.com -> HTTPS -> Y -> Login with a web browser)"
  gh auth login
fi
GH_USER=$(gh api user --jq .login)
green "    Logged in as: $GH_USER"

# ---- 2. .env / secret prep -------------------------------------------------
cyan "==> [2/7] Reading GROQ_API_KEY from .env"
if [[ ! -f .env ]]; then
  red "    .env not found. Run: cp .env.example .env && open -e .env"
  exit 1
fi
GROQ_KEY=$(grep -E '^GROQ_API_KEY=' .env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
if [[ -z "$GROQ_KEY" || "$GROQ_KEY" == paste_your_groq_key_here ]]; then
  red "    GROQ_API_KEY in .env is empty or placeholder. Set it first."
  exit 1
fi
green "    GROQ_API_KEY found (prefix: ${GROQ_KEY:0:6}..., length: ${#GROQ_KEY})"

# ---- 3. .gitignore safety net ---------------------------------------------
cyan "==> [3/7] Verifying .gitignore protects secrets"
if ! grep -qE '^\.env$' .gitignore 2>/dev/null; then
  echo ".env" >> .gitignore
fi
if ! grep -qE '^data/$|^data$' .gitignore 2>/dev/null; then
  echo "data/" >> .gitignore
fi
green "    .gitignore covers .env and data/"

# ---- 4. git init + commit --------------------------------------------------
cyan "==> [4/7] Initializing git repo"
if [[ ! -d .git ]]; then
  git init -q
  git branch -M main
fi
# Configure user if missing (gh-config-derived fallback)
if ! git config user.email >/dev/null 2>&1; then
  git config user.email "$(gh api user --jq .email 2>/dev/null || echo "$GH_USER@users.noreply.github.com")"
  git config user.name "$(gh api user --jq .name 2>/dev/null || echo "$GH_USER")"
fi
git add .
if git diff --cached --quiet; then
  green "    No new changes to commit"
else
  git commit -q -m "Chelsea transfer tracker pipeline (RSS + Groq, hands-off cron)"
  green "    Commit created"
fi

# Sanity: make sure .env is NOT staged
if git ls-files | grep -qE '^\.env$'; then
  red "    DANGER: .env is tracked. Aborting."
  exit 1
fi
green "    Confirmed: .env is not tracked"

# ---- 5. Create remote repo -------------------------------------------------
cyan "==> [5/7] Creating GitHub repo $GH_USER/$REPO_NAME ($VISIBILITY)"
if gh repo view "$GH_USER/$REPO_NAME" >/dev/null 2>&1; then
  yellow "    Repo already exists - using existing one"
  if ! git remote get-url origin >/dev/null 2>&1; then
    git remote add origin "https://github.com/$GH_USER/$REPO_NAME.git"
  fi
else
  gh repo create "$REPO_NAME" \
    "$VISIBILITY" \
    --description "Chelsea FC transfer-news scraper + AI tier classifier (Groq)" \
    --source . \
    --remote origin \
    --push
  green "    Repo created and code pushed"
fi

# Push if not already pushed
if [[ "$(git rev-parse --abbrev-ref HEAD)" == "main" ]] && \
   ! git ls-remote --exit-code origin main >/dev/null 2>&1; then
  git push -u origin main
fi
green "    Code on https://github.com/$GH_USER/$REPO_NAME"

# ---- 6. Set the single secret ---------------------------------------------
cyan "==> [6/7] Setting GROQ_API_KEY repo secret"
echo -n "$GROQ_KEY" | gh secret set GROQ_API_KEY --repo "$GH_USER/$REPO_NAME"
green "    Secret set"

# ---- 7. Trigger first workflow run ----------------------------------------
cyan "==> [7/7] Triggering first workflow run"
gh workflow run scraper.yml --repo "$GH_USER/$REPO_NAME" --ref main
sleep 4

# Tail the most recent run
RUN_ID=$(gh run list --repo "$GH_USER/$REPO_NAME" --workflow=scraper.yml --limit 1 --json databaseId --jq '.[0].databaseId')
if [[ -n "${RUN_ID:-}" ]]; then
  yellow "    Following run #$RUN_ID (Ctrl+C to detach - the run keeps going)"
  gh run watch "$RUN_ID" --repo "$GH_USER/$REPO_NAME" --exit-status || true
fi

green ""
green "==================================================================="
green "  Deployed. The cron in .github/workflows/scraper.yml runs every"
green "  6 hours (UTC). Each run uploads chelsea_tracker.csv as an artifact."
green ""
green "  Repo:      https://github.com/$GH_USER/$REPO_NAME"
green "  Actions:   https://github.com/$GH_USER/$REPO_NAME/actions"
green "==================================================================="
