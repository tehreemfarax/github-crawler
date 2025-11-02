from __future__ import annotations
import os
from datetime import date

import psycopg
from psycopg.rows import dict_row

from .config import SETTINGS

def get_conn():
    return psycopg.connect(SETTINGS.database_url, row_factory=dict_row)

def upsert_repo(conn, repo):
    # repo: dict with keys: id, owner, name, stars, url
    with conn.cursor() as cur:
        cur.execute(
            '''
            INSERT INTO repositories (repo_id, owner, name, stars, html_url, updated_at, first_seen)
            VALUES (%(id)s, %(owner)s, %(name)s, %(stars)s, %(url)s, now(), now())
            ON CONFLICT (repo_id) DO UPDATE
            SET stars = EXCLUDED.stars,
                html_url = EXCLUDED.html_url,
                updated_at = now()
            ''',
            repo
        )
        # Append to history only if changed today not already captured
        cur.execute(
            '''
            INSERT INTO repo_star_history (repo_id, stars, captured_at)
            VALUES (%(id)s, %(stars)s, %(captured_at)s)
            ON CONFLICT (repo_id, captured_at) DO NOTHING
            ''',
            {"id": repo["id"], "stars": repo["stars"], "captured_at": date.today()}
        )

def export_csv(path: str):
    import csv
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT repo_id, owner, name, full_name, stars, html_url, updated_at, first_seen FROM repositories ORDER BY stars DESC")
            rows = cur.fetchall()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys() if rows else ["repo_id","owner","name","full_name","stars","html_url","updated_at","first_seen"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
