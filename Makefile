.PHONY: install db-up db-wait db-init crawl export

install:
	python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

db-up:
	docker compose up -d db

db-wait:
	python -c "import time; import sys; import socket; h='localhost'; p=5432; print('Waiting for Postgres on', h, p); s=socket.socket(); [ (time.sleep(1), None) for _ in iter(lambda: s.connect_ex((h,p)), 0) ]; print('Postgres is up')"

db-init:
	python scripts/init_db.py

crawl:
	python -m gitcrawler.crawl_stars --target 100000

export:
	python -m gitcrawler.crawl_stars --export csv --out data/export.csv
