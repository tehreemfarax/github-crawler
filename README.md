# GitHub Crawler — Stars @100k (Python + Postgres + GitHub Actions)

This repo contains a production‑ready implementation of the assignment:
- Crawl star counts for **100,000 GitHub repositories** using the **GraphQL API**.
- **Respect rate limits** (primary + secondary) via exponential backoff, jitter, and per-worker throttling.
- Store results in **PostgreSQL** with **upserts** (current snapshot) and an **append‑only history table**.
- Ship a **GitHub Actions pipeline** that satisfies the assignment contract:
  1. Spins up the required **Postgres service container**.
  2. Installs dependencies and wires an **anti-corruption layer** (`gitcrawler.github`) around the GitHub API.
  3. Runs `scripts/init_db.py` to create/update the schema.
  4. Executes the crawler with the **default `GITHUB_TOKEN`** (no extra secrets).
  5. Exports the database and **uploads a CSV artifact**.
- Emphasise clean architecture: configuration lives in `config.py`, I/O in `db.py`, transport adapters in `github.py`, orchestration in `crawl_stars.py`, and utilities (retry/backoff) in `utils.py`.

The default crawl targets 100k repos and consistently finishes under ~20–25 minutes on Actions, thanks to parallel GraphQL workers sized from the live rate limit.

---

## Local quickstart

### 1) Requirements
- Docker & Docker Compose
- Python 3.11+ (if you want to run locally outside CI)

### 2) Start Postgres in Docker
```bash
docker compose up -d
# or (Compose v1) docker-compose up -d
```

### 3) Create `.env` from example and set GITHUB_TOKEN
```bash
cp .env.example .env
# Required: paste a personal access token with public_repo scope
# GITHUB_TOKEN=ghp_... 
```

> On GitHub Actions, a default `GITHUB_TOKEN` is automatically injected and is sufficient.

### 4) Initialize schema
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python scripts/init_db.py
```

### 5) Run the crawler (fetch 100k repos)
```bash
python -m gitcrawler.crawl_stars
```

To do a quick local smoke test without a long bucket build, scope the query and rely on the 1k GraphQL cap:

```bash
python -m gitcrawler.crawl_stars --recent-days 30 --simple
```

### 6) Export as CSV
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
- Split ranges iteratively while total bucket coverage is <≈140% of the target so we avoid scanning the entire history on every run.
- Within each accepted bucket (≤ threshold or single day), paginate with cursors until exhausted.
- Stop once we reach the fixed 100,000 repository target.
- Determine the worker fan-out by sampling the current rate limit, computing `ceil(2,100,000 / limit)`, and running that many independent jobs in parallel; each job buffers its results and a single writer flushes them to Postgres after all jobs finish.

### Reliability
- **Rate-limit aware**: reads `rateLimit` from GraphQL and sleeps when near exhaustion.
- **Exponential backoff** + **jitter** on transient failures (HTTP 5xx, network).
- **Idempotent upsert**: uses `ON CONFLICT (repo_id) DO UPDATE` to keep the row count minimal.

### Schema evolution for richer metadata
The star tables are the first slice of a wider event model:
- Keep `repositories` as the canonical entity table (immutable `repo_id`, mutable projections).
- Add append-only fact tables keyed by `(repo_id, observed_at)` or natural identifiers, e.g. `issues`, `pull_requests`, `pr_comments`, `issue_comments`, `checks`.
- Use `captured_at` (date) or `captured_at_ts` (timestamp) as part of the primary key to support **upsert-on-id** with **append history** semantics—efficient for both fresh inserts and daily refreshes.
- For nested resources (comments, reviews), partition tables by `repo_id hash` or `captured_at` and rely on `ON CONFLICT` for “latest state” while keeping history in companion tables.
- Expose data access through dedicated modules (e.g. `gitcrawler.issues`) so the crawler stays immutable and testable.

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
- Cleans up (service container is ephemeral; data lives only in the artifact).

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
