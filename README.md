# GitHub Crawler — Stars @100k (Python + Postgres + GitHub Actions)

This repo contains a production‑ready implementation of the assignment:
- Crawl star counts for **100,000 GitHub repositories** using the **GraphQL API**
- **Respect rate limits** with automatic backoff/retry
- Store results in **PostgreSQL**, with **upserts** and an **append‑only history**
- Provide a **GitHub Actions pipeline** with a **Postgres service container** that:
  1) sets up schema,
  2) runs the crawler (using the default `GITHUB_TOKEN`),
  3) uploads a CSV artifact.

## Local quickstart

### 0) Requirements
- Docker & Docker Compose
- Python 3.11+ (if you want to run locally outside CI)

### 1) Start Postgres in Docker
```bash
docker compose up -d
# or (Compose v1) docker-compose up -d
```

### 2) Create `.env` from example and set GITHUB_TOKEN
```bash
cp .env.example .env
# Required: paste a personal access token with public_repo scope
# GITHUB_TOKEN=ghp_... 
```

> On GitHub Actions, a default `GITHUB_TOKEN` is automatically injected and is sufficient.

### 3) Initialize schema
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python scripts/init_db.py
```

### 4) Run the crawler (fetch 100k repos)
```bash
python -m gitcrawler.crawl_stars --target 100000
```

To do a quick local test (e.g., 100 repos from the last 30 days) and avoid a long bucket build:

```bash
python -m gitcrawler.crawl_stars --target 100 --recent-days 30 --bucket-threshold 5000
# or, for the simplest path with one search query:
python -m gitcrawler.crawl_stars --target 100 --recent-days 30 --simple
```

### 5) Export as CSV
```bash
python -m gitcrawler.crawl_stars --export csv --out data/export.csv
```

---

## Postgres (Docker) connection details

With the provided `docker-compose.yml`:
- Host (from your machine): **localhost**
- Port: **5432**
- User: **postgres-user-name**
- Password: **postgres-password**
- DB: **gitcrawler**

Connection string examples:

- psql:
```bash
psql postgresql://postgres-user-name:postgres-password@localhost:5432/gitcrawler
```

- psycopg (Python DSN):
```
postgresql://postgres-user-name:postgres-password@localhost:5432/gitcrawler
```

> For GitHub Actions, the app connects to the service container via host `localhost` and port `5432` thanks to `services: postgres:` with published port.

---

## Design

### Schema
- `repositories` (current state, **upserted** by repo_id)
- `repo_star_history` (append‑only; one row per crawl & repo if the value changed)

This gives efficient reads for the current view and a compact history for trend analysis.

### Crawling strategy (to overcome search 1k cap)
- Use GraphQL `search(type: REPOSITORY)` with **dynamic time bucketing** on `created:` range.
- Recursively split time windows whenever `approximateResultCount >= 1000` until each window fetches < 1000.
- Within each window, paginate with cursors until exhausted.
- Stop once we reach `--target` repositories (default 100,000).

### Reliability
- **Rate-limit aware**: reads `rateLimit` from GraphQL and sleeps when near exhaustion.
- **Exponential backoff** + **jitter** on transient failures (HTTP 5xx, network).
- **Idempotent upsert**: uses `ON CONFLICT (repo_id) DO UPDATE` to keep the row count minimal.

### Scaling to 500M repos (high-level notes)
See `README_SCALING.md` for details, but in summary:
- Replace GitHub API with dataset sources (public GH Archive / GH BigQuery / GHTorrent) for discovery, use API only for deltas.
- **Sharded ingestion** (Kafka + multiple workers), **batched writes** (COPY), **partitioned tables** by date/hash.
- Snapshot + delta architecture; columnar store for analytics; move hot entities to Redis for coordination.
- Strong observability (OpenTelemetry), backpressure, and autoscaling.

---

## GitHub Actions

The workflow:
- Brings up a **Postgres service container**
- Installs Python deps
- Initializes schema
- Runs the crawler to 100k
- Dumps the DB to a CSV
- Uploads the CSV as an artifact

See `.github/workflows/crawl.yml`.

---

## Useful make targets
```bash
make install        # create venv + install deps
make db-up          # start postgres (docker compose)
make db-wait        # wait until db is ready
make db-init        # run schema
make crawl          # run 100k crawl
make export         # export CSV
```
