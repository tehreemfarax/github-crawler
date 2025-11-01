from __future__ import annotations
import argparse
from datetime import datetime, timedelta, date
from typing import List, Tuple

from .github import count_for_query, iter_search, fetch_repo
from .db import get_conn, upsert_repo, export_csv
from tqdm import tqdm

# Build dynamic time buckets for 'created:' qualifier
def split_buckets(start: date, end: date, threshold: int = 900) -> List[Tuple[date, date]]:
    q = f"created:{start.isoformat()}..{end.isoformat()}"
    count = count_for_query(q)
    if count <= threshold:
        print(f"Accepted bucket {start.isoformat()}..{end.isoformat()} (≈{count} repos)", flush=True)
        return [(start, end)]
    if start >= end:
        print(
            f"Reached minimal range {start.isoformat()}..{end.isoformat()} with ≈{count} repos; accepting to avoid infinite splitting.",
            flush=True,
        )
        return [(start, end)]
    print(f"Splitting bucket {start.isoformat()}..{end.isoformat()} (≈{count} repos)", flush=True)
    # split into two halves recursively
    mid = start + (end - start) / 2
    left = split_buckets(start, mid, threshold)
    right = split_buckets(mid + timedelta(days=1), end, threshold)
    return left + right

def build_buckets(start: date, end: date, threshold: int) -> List[Tuple[date, date]]:
    return split_buckets(start, end, threshold=threshold)

def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=100000, help="Target number of repos to fetch")
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
    if args.simple:
        query = f"created:>={since.isoformat()} sort:stars"
        print(f"Running simple crawl with query '{query}' (target={args.target}).")
        buckets = [(since, bucket_end)]
        bucket_iter = [(since, bucket_end)]
    else:
        print(f"Building creation date buckets from {since.isoformat()} to {bucket_end.isoformat()} (threshold={args.bucket_threshold})... this may take a minute.")
        buckets = build_buckets(since, bucket_end, threshold=args.bucket_threshold)
        print(f"Built {len(buckets)} buckets. Starting crawl...")
        bucket_iter = buckets

    seen = 0
    repo_progress = tqdm(total=args.target, desc="Repositories", unit="repo")
    with get_conn() as conn:
        bucket_progress = tqdm(bucket_iter, desc="Buckets", unit="bucket")
        for (start, end) in bucket_progress:
            if args.simple:
                q = f"created:>={since.isoformat()} sort:stars"
            else:
                q = f"created:{start.isoformat()}..{end.isoformat()}"
            for repo in iter_search(q):
                upsert_repo(conn, {
                    "id": repo["id"],
                    "owner": repo["owner"]["login"],
                    "name": repo["name"],
                    "stars": repo["stargazerCount"],
                    "url": repo["url"],
                })
                seen += 1
                repo_progress.update(1)
                if seen >= args.target:
                    repo_progress.close()
                    bucket_progress.close()
                    print(f"Reached target {args.target}.")
                    return
    repo_progress.close()
    bucket_progress.close()
    print(f"Done. Inserted/updated {seen} repos.")

if __name__ == "__main__":
    main()
