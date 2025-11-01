# Scaling Notes — 500M repositories

When targeting 500M repositories, the GitHub Search API is not the right discovery mechanism.
Key changes:

1. **Discovery source**: Use GH Archive / BigQuery public datasets to enumerate repositories.
2. **Delta strategy**: Daily/Hourly deltas from events (PushEvent, WatchEvent) to refresh star counts.
3. **Ingestion**: Kafka (topics: repos, stars), N workers (async), exactly-once semantics via idempotent keys.
4. **Storage**:
   - **Postgres** for source of truth (partitioned by hash/date).
   - **COPY** or `psycopg.execute_batch` for bulk upserts.
   - History table partitioned by `crawl_date`.
   - Consider **TimescaleDB** or **ClickHouse** for long-term history/analytics.
5. **API usage**: Only for missing entities or periodic verification; rotate app installations to improve limits.
6. **Orchestration**: Airflow/Argo for scheduled runs; autoscaling per backlog depth.
7. **Observability**: OpenTelemetry tracing, Prometheus metrics (rate-limit hits, rows/s), and alerts.
8. **Cost control**: Batch windows, adaptive polling, and graceful degradation under pressure.
