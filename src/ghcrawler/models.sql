-- Current snapshot of repositories
CREATE TABLE IF NOT EXISTS repositories (
    repo_id TEXT PRIMARY KEY,              -- GitHub node_id (opaque, stable)
    owner   TEXT NOT NULL,
    name    TEXT NOT NULL,
    full_name TEXT GENERATED ALWAYS AS (owner || '/' || name) STORED,
    stars   INTEGER NOT NULL,
    html_url TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- when we last updated this row
    first_seen TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Append-only star count history (one row per repo when the value changes)
CREATE TABLE IF NOT EXISTS repo_star_history (
    repo_id TEXT NOT NULL,
    stars   INTEGER NOT NULL,
    captured_at DATE NOT NULL,   -- date of crawl (UTC)
    PRIMARY KEY (repo_id, captured_at),
    FOREIGN KEY (repo_id) REFERENCES repositories(repo_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_repositories_owner_name ON repositories(owner, name);
CREATE INDEX IF NOT EXISTS idx_history_captured_at ON repo_star_history(captured_at);
