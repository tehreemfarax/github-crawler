# Scaling Notes — 500M repositories (GraphQL API only)

While a data-lake source (GH Archive/BigQuery) is the pragmatic path for hundreds of millions of repositories, the notes below outline how to push the **same GitHub GraphQL API** much further. This plan assumes a dedicated GitHub App installation fleet, aggressive sharding, and heavy caching to stay within the platform’s rules.

1. **Token pool & governance**
   - Provision dozens of GitHub App installations (or personal tokens) across dedicated GitHub orgs.
   - Central coordinator assigns buckets to installations, respecting primary + secondary rate limits per token.
   - Maintain live telemetry (remaining cost, abuse flags) and automatically pause/shift work when a token throttles.

2. **Discovery sharding**
   - Precompute a dense grid of search qualifiers to bypass the 1k result cap: split by `created:` (day/hour), `pushed:`, `stars:` ranges, language, etc.
   - Persist shard definitions in Postgres/Redis; assign shards to workers in a consistent-hash ring so new workers can join without rebalancing everything.
   - Track coverage progress per shard (`cursor`, `last_seen_id`, `last_cost`), allowing incremental resumes.

3. **Distributed crawler**
   - Deploy hundreds of lightweight workers (Rust/Python/Go) each running the existing GraphQL iterator.
   - Each worker: request shard → stream up to 1k repos (`first: 100` × 10 pages) → push normalized payload onto Kafka/Redis queue.
   - Aggressive backoff: on secondary rate limit, worker sleeps for the reset window but does not lose shard ownership.

4. **Storage & upsert pipeline**
   - Collect repo snapshots via Kafka → Spark/Flink/Beam jobs → bulk upsert into partitioned Postgres/TimescaleDB/ClickHouse.
   - Use the same `repositories` / `repo_star_history` pattern, but partition by `(repo_id hash % N)` or `captured_at` to parallelize writes.
   - Append-only history tables stay narrow; star deltas, issues, PRs, comments all follow the same pattern (primary key = natural id + captured_at).

5. **Scheduling & orchestration**
   - Airflow/Argo orchestrates shard assignments, monitors lag, and triggers retries.
   - Maintain SLA tiers: hottest shards (recent/small repos) daily, cold shards (ancient repos) weekly/monthly.
   - Surface metrics (Prometheus/OpenTelemetry) for: API cost per token, rows/sec ingested, shard latency, backlog depth.

6. **Resilience & caching**
   - Cache immutable repo metadata (id, owner, name, createdAt) in Redis/KeyDB to avoid re-fetching.
   - Use ETags/If-Modified-Since on REST fallbacks when GraphQL hits schema limits.
   - Implement checksum-based duplicate detection so repeated crawls of the same shard short-circuit quickly.

7. **Cost control & compliance**
   - Throttle concurrency when GitHub signals abuse detection; never exceed published secondary-limits.
   - Log every request with token identifier for audit; provide kill switches per installation/org.
   - Budget API costs per cycle (e.g., 500M repos over 7 days) and dynamically scale worker pool/tokens to stay within the window.

With these safeguards, the GraphQL API can cover hundreds of millions of repositories—albeit with significant operational complexity compared to the dataset-based approach described in the original notes. Retain both plans in your toolbox and pick the right one based on contractual/API constraints.
