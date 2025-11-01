from __future__ import annotations

import argparse
import math
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from typing import List, Sequence

from .github import count_for_query, iter_search, fetch_repo, get_rate_limit
from .db import get_conn, upsert_repo, export_csv
from .utils import TransientError

TARGET_REPOS = 100_000
JOB_DIVISOR = 2_100_000


@dataclass(frozen=True)
class Bucket:
    start: date
    end: date
    approx_count: int


def split_buckets(start: date, end: date, threshold: int = 900) -> List[Bucket]:
    """Recursively split creation date ranges so each bucket stays under the threshold."""
    q = f"created:{start.isoformat()}..{end.isoformat()}"
    count = count_for_query(q)
    if count <= threshold or start >= end:
        print(f"Accepted bucket {start.isoformat()}..{end.isoformat()} (≈{count} repos)", flush=True)
        return [Bucket(start, end, count)]
    print(f"Splitting bucket {start.isoformat()}..{end.isoformat()} (≈{count} repos)", flush=True)
    mid = start + (end - start) / 2
    left = split_buckets(start, mid, threshold)
    right = split_buckets(mid + timedelta(days=1), end, threshold)
    return left + right


def build_buckets(start: date, end: date, threshold: int) -> List[Bucket]:
    return split_buckets(start, end, threshold=threshold)


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def plan_jobs_evenly(buckets: Sequence[Bucket], job_count: int) -> List[List[Bucket]]:
    if job_count <= 0:
        job_count = 1
    job_count = min(job_count, len(buckets)) or 1
    jobs: List[List[Bucket]] = []
    base = len(buckets) // job_count
    remainder = len(buckets) % job_count
    idx = 0
    for i in range(job_count):
        take = base + (1 if i < remainder else 0)
        if take <= 0:
            continue
        jobs.append(list(buckets[idx: idx + take]))
        idx += take
    return [job for job in jobs if job]


def _process_job(job_id: int, buckets: Sequence[Bucket], job_target: int):
    collected = []
    if not buckets or job_target <= 0:
        return job_id, collected

    for bucket in buckets:
        if len(collected) >= job_target:
            break
        query = f"created:{bucket.start.isoformat()}..{bucket.end.isoformat()}"
        remaining = job_target - len(collected)
        while True:
            try:
                for repo in iter_search(query, max_items=remaining):
                    collected.append({
                        "id": repo["id"],
                        "owner": repo["owner"]["login"],
                        "name": repo["name"],
                        "stars": repo["stargazerCount"],
                        "url": repo["url"],
                    })
                    if len(collected) >= job_target:
                        break
                break
            except TransientError as exc:
                wait_seconds = 90
                print(f"Job {job_id} hit rate limiting ({exc}); sleeping {wait_seconds}s before retry.", flush=True)
                time.sleep(wait_seconds)
                remaining = job_target - len(collected)
                if remaining <= 0:
                    break
    return job_id, collected


def _write_results(repos: List[dict]):
    if not repos:
        print("No repositories collected; skipping DB write.")
        return
    with get_conn() as conn:
        for repo in repos:
            upsert_repo(conn, repo)


def run_simple(query: str, target: int):
    print(f"Running simple crawl with query '{query}' (target={target}).")
    collected = []
    for repo in iter_search(query, max_items=target):
        collected.append({
                "id": repo["id"],
                "owner": repo["owner"]["login"],
                "name": repo["name"],
                "stars": repo["stargazerCount"],
                "url": repo["url"],
            })
    _write_results(collected)
    print(f"Done. Inserted/updated {len(collected)} repos.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", choices=["csv"], help="Export mode (reads from DB, no crawling)")
    parser.add_argument("--out", default="data/export.csv", help="Export path")
    parser.add_argument("--repo", help="Fetch a single repository specified as owner/name")
    parser.add_argument("--since", type=parse_date, help="Only crawl repositories created on or after this date (YYYY-MM-DD)")
    parser.add_argument("--recent-days", type=int, help="Shortcut to set --since to N days ago")
    parser.add_argument("--bucket-threshold", type=int, default=900, help="Maximum repo count per bucket before splitting")
    parser.add_argument("--simple", action="store_true", help="Skip bucketing and use a single search query (best with --recent-days)")
    args = parser.parse_args()

    if args.export:
        export_csv(args.out)
        print(f"Exported to {args.out}")
        return

    if args.since and args.recent_days:
        raise SystemExit("Use either --since or --recent-days, not both.")

    if args.recent_days:
        if args.recent_days <= 0:
            raise SystemExit("--recent-days must be positive.")
        since = date.today() - timedelta(days=args.recent_days)
    elif args.since:
        since = args.since
    else:
        since = date(2008, 1, 1)

    if since > date.today():
        raise SystemExit("--since cannot be in the future.")

    if args.repo:
        if "/" not in args.repo:
            raise SystemExit("Use owner/name format for --repo (e.g. octocat/Hello-World).")
        owner, name = args.repo.split("/", 1)
        repo = fetch_repo(owner.strip(), name.strip())
        if not repo:
            print(f"Repository {args.repo} not found or inaccessible.")
            return
        with get_conn() as conn:
            upsert_repo(conn, {
                "id": repo["id"],
                "owner": repo["owner"]["login"],
                "name": repo["name"],
                "stars": repo["stargazerCount"],
                "url": repo["url"],
            })
        print(f"Inserted/updated single repo {repo['owner']['login']}/{repo['name']}.")
        return

    bucket_end = date.today()
    target = TARGET_REPOS
    simple_mode = args.simple

    rate_limit = get_rate_limit()
    rl_limit = rate_limit.get("limit") or rate_limit.get("remaining") or 1
    job_count = max(1, math.ceil(JOB_DIVISOR / rl_limit))
    print(f"Current rate limit: limit={rate_limit.get('limit')} remaining={rate_limit.get('remaining')} resetAt={rate_limit.get('resetAt')}")
    print(f"Planning to create {job_count} job(s) based on 2,100,000 / rate_limit.")

    if simple_mode:
        query = f"created:>={since.isoformat()} sort:stars"
        repo_count = count_for_query(query)
        effective_target = min(target, repo_count)
        if effective_target > 1000:
            print(
                f"Simple search is limited to the first 1000 results (query matched ≈{repo_count}). Switching to bucketed crawl to reach the requested target.",
                flush=True,
            )
            simple_mode = False
        else:
            run_simple(query, effective_target)
            return

    print(f"Building creation date buckets from {since.isoformat()} to {bucket_end.isoformat()} (threshold={args.bucket_threshold})... this may take a minute.")
    buckets = build_buckets(since, bucket_end, threshold=args.bucket_threshold)
    approx_total = sum(max(1, b.approx_count) for b in buckets)
    print(f"Built {len(buckets)} buckets covering ≈{approx_total} repos.")

    jobs = plan_jobs_evenly(buckets, job_count)
    if not jobs:
        print("No jobs to execute; exiting.")
        return

    max_parallel = max(1, min(8, rl_limit // 500 if rl_limit else 1))
    workers = min(len(jobs), max_parallel)

    print(f"Launching {workers} worker process(es) across {len(jobs)} job(s) to reach target {target}.")

    job_target = max(1, math.ceil(target / len(jobs)))
    collected: List[dict] = []
    seen_ids = set()
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = []
        for job_id, job_buckets in enumerate(jobs, start=1):
            futures.append(executor.submit(_process_job, job_id, job_buckets, job_target))

        for future in as_completed(futures):
            job_id, results = future.result()
            print(f"Job {job_id} collected {len(results)} repos.")
            for repo in results:
                if repo["id"] in seen_ids:
                    continue
                seen_ids.add(repo["id"])
                collected.append(repo)
                if len(collected) >= target:
                    break
            if len(collected) >= target:
                break

    if len(collected) > target:
        collected = collected[:target]

    _write_results(collected)
    print(f"Done. Inserted/updated {len(collected)} repos (target {target}).")


if __name__ == "__main__":
    main()
