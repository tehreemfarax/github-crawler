import time, random
from typing import Callable, Any
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type
import requests

class TransientError(Exception):
    pass

@retry(
    reraise=True,
    stop=stop_after_attempt(8),
    wait=wait_exponential_jitter(initial=1, max=60),
    retry=retry_if_exception_type(TransientError),
)
def http_post_json(url: str, headers: dict, json_body: dict) -> dict:
    r = requests.post(url, headers=headers, json=json_body, timeout=60)
    if r.status_code >= 500:
        raise TransientError(f"Server error {r.status_code}: {r.text[:200]}")
    if r.status_code == 403 and "rate limit" in r.text.lower():
        raise TransientError(f"Rate limited: {r.text[:200]}")
    r.raise_for_status()
    return r.json()
