from __future__ import annotations
import sys
from typing import Optional, Tuple, Dict, Any, Iterable
from .config import SETTINGS
from .utils import http_post_json
import time

GQL_ENDPOINT = "https://api.github.com/graphql"

SEARCH_QUERY = '''
query SearchRepos($q: String!, $cursor: String) {
  rateLimit {
    limit
    cost
    remaining
    resetAt
  }
  search(query: $q, type: REPOSITORY, first: 100, after: $cursor) {
    repositoryCount
    pageInfo { endCursor hasNextPage }
    nodes {
      ... on Repository {
        id
        name
        owner { login }
        stargazerCount
        url
        createdAt
      }
    }
  }
}
'''

COUNT_QUERY = '''
query CountRepos($q: String!) {
  search(query: $q, type: REPOSITORY, first: 1) {
    repositoryCount
  }
}
'''

SINGLE_REPO_QUERY = '''
query Repo($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    id
    name
    owner { login }
    stargazerCount
    url
    createdAt
  }
}
'''

def _headers():
    token = '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' or ""
    if not token:
        raise RuntimeError(
            "Missing GitHub token. Set GITHUB_TOKEN in your environment or .env file."
        )
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": SETTINGS.user_agent,
        "Accept": "application/json",
    }

def gql(query: str, variables: dict) -> dict:
    return http_post_json(GQL_ENDPOINT, _headers(), {"query": query, "variables": variables})

def count_for_query(q: str) -> int:
    data = gql(COUNT_QUERY, {"q": q})
    return data["data"]["search"]["repositoryCount"]

def iter_search(q: str):
    cursor = None
    while True:
        data = gql(SEARCH_QUERY, {"q": q, "cursor": cursor})
        rl = data["data"]["rateLimit"]
        search = data["data"]["search"]
        for n in search["nodes"]:
            yield n
        if not search["pageInfo"]["hasNextPage"]:
            break
        cursor = search["pageInfo"]["endCursor"]
        # simple pacing to be nice
        if rl and rl.get("remaining", 1) < 50:
            # sleep until reset
            time.sleep(5)

def fetch_repo(owner: str, name: str):
    data = gql(SINGLE_REPO_QUERY, {"owner": owner, "name": name})
    return data["data"]["repository"]
