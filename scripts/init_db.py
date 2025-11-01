import os
import psycopg
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres-user-name:postgres-password@localhost:5432/gitcrawler")

def main():
    sql = Path("src/ghcrawler/models.sql").read_text()
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    print("Schema initialized.")

if __name__ == "__main__":
    main()
