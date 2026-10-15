"""Bookkeeping that stops coprsync from re-publishing the same release.

State is per repo, keyed by release tag, and records every asset that has been
handed to Copr. The newest tag that has been dealt with is the boundary the
release scan stops at, so a partially published release is picked up again on
the next run.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import CoprSyncError

STATE_VERSION = 1


class State:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.data = self._load()

    def last_tag(self, repo: str) -> str | None:
        return self._app(repo).get("last_tag")

    def is_published(self, repo: str, tag: str, asset: str) -> bool:
        return asset in self._releases(repo).get(tag, {})

    def record(self, repo: str, tag: str, asset: str, chroots: list[str],
               build_id: int | None) -> None:
        """Note one published asset, then move the boundary to this release."""
        self._releases(repo).setdefault(tag, {})[asset] = {
            "chroots": sorted(chroots),
            "build_id": build_id,
            "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.advance(repo, tag)

    def advance(self, repo: str, tag: str) -> None:
        """Mark `tag` as the newest release the scan should not look past.

        Records for older tags are dropped: the scan never reaches behind the
        boundary again, so keeping them would only grow the file.
        """
        entry = self._app(repo)
        entry["last_tag"] = tag
        kept = self._releases(repo).get(tag)
        entry["releases"] = {tag: kept} if kept is not None else {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n")

    def _releases(self, repo: str) -> dict[str, Any]:
        return self._app(repo).setdefault("releases", {})

    def _app(self, repo: str) -> dict[str, Any]:
        return self.data["apps"].setdefault(repo, {})

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": STATE_VERSION, "apps": {}}
        try:
            loaded = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise CoprSyncError(f"{self.path} is not valid JSON: {exc}") from exc
        if not isinstance(loaded, dict) or not isinstance(loaded.get("apps"), dict):
            raise CoprSyncError(f"{self.path} has an unexpected shape")
        loaded["version"] = STATE_VERSION
        return loaded
