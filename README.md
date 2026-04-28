# Chelsea FC Transfer News Scraper & AI Analyzer

**Zero-cost** enterprise pipeline that scrapes Chelsea-related transfer news from
public RSS feeds (Reddit RSS for `r/chelseafc` + BBC, Sky Sports, Football.London,
Chelsea FC official) and uses **Groq** (Llama 3.3 70B, free tier) to extract:

- **Journalist Name** ("Fabrizio Romano", "BBC Sport", ...)
- **Transfer Claim** (one-line factual claim)
- **Tier** (Tier 1 / Tier 2 / Tier 3 / Rumour / Unknown)
- **Hit/Miss** verdict (Hit / Miss / Pending / Unknown)
- **Confidence** + reasoning

No Reddit OAuth. No PRAW. No Anthropic key. No Gemini. **Only one secret in the
entire pipeline: `GROQ_API_KEY`.**

The container runs hands-off: Harness fires it on a 6-hour cron, injects the
single Groq secret from Harness Secrets Manager, and continuously builds your
CSV database of transfer-journalism reliability.

---

## 1. Project layout

```
chelsea-transfer-tracker/
├── src/
│   ├── main.py                       # entry point - orchestrates the run
│   ├── config.py                     # env-var driven config
│   ├── models.py                     # TransferItem / AnalyzedItem
│   ├── scrapers/
│   │   ├── reddit_rss_scraper.py     # feedparser -> r/chelseafc RSS (no auth)
│   │   └── rss_scraper.py            # feedparser -> BBC/Sky/Football.London/Chelsea FC
│   ├── analyzer/
│   │   └── groq_analyzer.py          # openai SDK -> Groq endpoint -> structured JSON
│   └── storage/
│       ├── csv_writer.py             # pandas append-only writer
│       └── object_store.py           # S3 / GCS / local backends
├── Dockerfile                        # multi-stage, non-root, slim
├── requirements.txt                  # feedparser, openai, pandas
├── .env.example
├── bootstrap.sh                      # one-command Docker run
├── run_local.sh                      # one-command venv run (no Docker)
├── tests/test_pipeline_e2e.py        # mocked end-to-end test
├── .harness/pipeline.yaml            # Harness CI/CD with cron trigger
└── .github/workflows/scraper.yml     # GitHub Actions fallback
```

## 2. Local development

```bash
cp .env.example .env
# Open .env and paste your free Groq key from https://console.groq.com/keys

./bootstrap.sh        # builds the image, runs once, writes ./data/chelsea_tracker.csv
```

If you don't have Docker, use the venv path instead:

```bash
./run_local.sh
```

The CSV is written to `./data/chelsea_tracker.csv`. Re-runs only **append**
new items (deduplicated by `fingerprint`).

---

## 3. Harness pipeline - executive setup guide

Total setup time: ~15 minutes.

### Step 1 - Create the Harness project

1. Sign in to **app.harness.io**.
2. Top-left org switcher → choose `Hocco` (or create org).
3. **Projects** → **+ New Project** → name **ChelseaTracker**.
4. Enable **Continuous Integration** and **Pipelines** modules.

### Step 2 - Connect the source repo

1. **Project Setup** → **Connectors** → **+ New Connector** → **GitHub**.
2. Auth: **Personal Access Token** (`repo` scope).
3. Save with identifier `GitHub_Hocco`. Test the connection.
4. (Optional) Connect a Harness Delegate if you want builds on your own
   Kubernetes cluster. Otherwise enable **Hosted Builds** on the project.

### Step 3 - Connect the container registry

Pick **one** of:

- **ECR**: Connectors → New → AWS → identifier `aws_ecr_push`.
- **DockerHub**: Connectors → New → Docker Registry → identifier `dockerhub`.

Update the registry references in `.harness/pipeline.yaml` to your real values.
(If you use `STORAGE_BACKEND=local`, you can skip ECR/DockerHub entirely and
just keep the CSV in the pipeline artifact tab.)

### Step 4 - Create the single secret

**Project Setup** → **Secrets** → **+ New Secret** → **Text**.

| Identifier      | Value                                                            |
| --------------- | ---------------------------------------------------------------- |
| `groq_api_key`  | from https://console.groq.com/keys (free, no credit card)        |

That's it. **One secret. No Reddit credentials. No AI Studio drama. No AWS keys
unless you opt into S3.**

### Step 5 - Import the pipeline

1. Project → **Pipelines** → **+ New Pipeline**.
2. Choose **Remote** so it reads `.harness/pipeline.yaml` from the repo.
3. Save. Harness will validate references (connectors, the single secret).

### Step 6 - Configure the cron trigger

The trigger is already declared at the bottom of `pipeline.yaml`
(`expression: "0 */6 * * *"`). Harness picks it up automatically when you
import a Remote pipeline. To verify: Pipeline → **Triggers** → confirm
`every_6h` is enabled.

### Step 7 - First run

1. Pipeline → **Run** → branch `main` → **Run Pipeline**.
2. Watch **Build & Push Image** compile, build, and push the image.
3. Watch **Run Scraper** pull the image, execute it, and confirm in logs:
   - `Total candidates from all sources: N`
   - `Wrote N new analyzed rows`
4. The CSV is attached as a **Pipeline Artifact** (visible under the run's
   Artifacts tab) and, if `STORAGE_BACKEND=s3`, also pushed to S3.

---

## 4. GitHub Actions alternative

If you don't want to use Harness, the same pipeline runs as a GitHub Action
out of the box:

1. Push the repo to GitHub.
2. **Settings → Secrets and variables → Actions → New repository secret**.
3. Name: `GROQ_API_KEY`. Value: your Groq key.
4. **Actions tab → Chelsea Transfer Tracker → Run workflow** (manual trigger).
5. After it succeeds, the cron in `.github/workflows/scraper.yml`
   (`0 */6 * * *`) runs every 6 hours automatically.
6. Each run uploads `chelsea_tracker.csv` as a workflow artifact.

---

## 5. Cost notes

- **Reddit RSS**: free, public, no API quota.
- **News feeds**: free, public RSS.
- **Groq** (Llama 3.3 70B Versatile): free tier 30 req/min, 14400 req/day. The pipeline only sends *new, deduplicated* items each run — usually 5-30 per 6-hour cycle, well within free quota.
- **Harness**: Free tier covers small CI/CD workloads.
- **GitHub Actions**: 2000 free minutes/month for public repos (unlimited for public repos).
- **AWS S3**: optional. Skip with `STORAGE_BACKEND=local` and keep the CSV as a Harness/Actions pipeline artifact.

The whole pipeline runs at **$0/month** on Groq Free + Actions/Harness Free + skip S3.

## 6. Failure modes

- **Reddit RSS 429 / blockpage**: scraper uses Chrome User-Agent + urllib pre-fetch. If Reddit still blocks, the pipeline logs a warning and continues with news-RSS data.
- **Groq rate-limited**: scraper sleeps 2s and retries. Items still fall back to `tier=Unknown` if quota exhausted entirely.
- **News feed 5xx**: per-feed try/except - a single broken feed never fails the pipeline.
- **Idempotency**: dedup by stable `fingerprint` (`source:external_id`). Re-running never duplicates rows.
