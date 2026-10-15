"""Minimal GitHub REST client built on urllib, so the job needs no extra deps."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .errors import GitHubError

API_ROOT = "https://api.github.com"
USER_AGENT = "coprsync"
RETRY_STATUS = {429, 500, 502, 503, 504}


class GitHubClient:
    def __init__(self, token: str | None = None, *, api_root: str = API_ROOT,
                 timeout: float = 60.0, retries: int = 3) -> None:
        self.token = token
        self.api_root = api_root.rstrip("/")
        self.timeout = timeout
        self.retries = retries

    def releases(self, org: str, repo: str, per_page: int = 30) -> list[dict[str, Any]]:
        payload = self._get_json(f"{self.api_root}/repos/{org}/{repo}/releases?per_page={per_page}")
        if not isinstance(payload, list):
            raise GitHubError(f"unexpected releases payload for {org}/{repo}")
        return payload

    def download(self, url: str, dest: Path, *, expected_size: int | None = None) -> Path:
        """Stream a release asset to `dest`. Fails if the body is short."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers=self._headers("application/octet-stream"))
        tmp = dest.with_name(dest.name + ".part")
        try:
            with self._open(request) as response, tmp.open("wb") as handle:
                while chunk := response.read(1 << 20):
                    handle.write(chunk)
        except urllib.error.HTTPError as exc:
            tmp.unlink(missing_ok=True)
            raise GitHubError(f"download failed ({exc.code}) for {url}") from exc

        written = tmp.stat().st_size
        if expected_size is not None and written != expected_size:
            tmp.unlink(missing_ok=True)
            raise GitHubError(
                f"short download for {url}: got {written} bytes, expected {expected_size}"
            )
        tmp.replace(dest)
        return dest

    def _get_json(self, url: str) -> Any:
        request = urllib.request.Request(url, headers=self._headers("application/vnd.github+json"))
        try:
            with self._open(request) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise GitHubError(f"GET {url} failed ({exc.code}): {detail}") from exc
        except json.JSONDecodeError as exc:
            raise GitHubError(f"GET {url} returned invalid JSON") from exc

    def _open(self, request: urllib.request.Request):
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                return urllib.request.urlopen(request, timeout=self.timeout)
            except urllib.error.HTTPError as exc:
                if exc.code not in RETRY_STATUS:
                    raise
                last = exc
            except urllib.error.URLError as exc:
                last = exc
            time.sleep(2 ** attempt)
        raise GitHubError(f"request to {request.full_url} failed after {self.retries} attempts: {last}")

    def _headers(self, accept: str) -> dict[str, str]:
        headers = {
            "Accept": accept,
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
