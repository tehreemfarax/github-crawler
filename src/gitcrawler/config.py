import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    database_url: str = os.getenv("DATABASE_URL", "postgresql://postgres-user-name:postgres-password@localhost:5432/gitcrawler")
    user_agent: str = "gitcrawler/1.0 (+assignment)"

SETTINGS = Settings()
