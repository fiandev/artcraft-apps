"""Interpret GitHub release payloads into the work coprsync actually needs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

ARCH_RE = re.compile(r"-linux-(?P<arch>[A-Za-z0-9_]+)\.rpm$")


@dataclass(frozen=True)
class RpmAsset:
    name: str
    arch: str
    url: str
    size: int


def release_tag(release: dict[str, Any]) -> str:
    return str(release.get("tag_name") or "").strip()


def is_publishable(release: dict[str, Any], *, include_prereleases: bool) -> bool:
    if release.get("draft"):
        return False
    if release.get("prerelease") and not include_prereleases:
        return False
    return bool(release_tag(release))


def asset_arch(name: str) -> str | None:
    """Pull the architecture out of an upstream asset name, e.g. ...-linux-aarch64.rpm."""
    match = ARCH_RE.search(name)
    return match.group("arch") if match else None


def rpm_assets(release: dict[str, Any]) -> tuple[RpmAsset, ...]:
    """Every arch-specific RPM attached to the release, in asset order."""
    assets: list[RpmAsset] = []
    for asset in release.get("assets") or ():
        name = str(asset.get("name") or "")
        arch = asset_arch(name)
        if arch is None:
            continue
        assets.append(
            RpmAsset(
                name=name,
                arch=arch,
                url=str(asset.get("url") or ""),
                size=int(asset.get("size") or 0),
            )
        )
    return tuple(assets)


def new_releases(
    releases: Iterable[dict[str, Any]],
    last_tag: str | None,
    *,
    include_prereleases: bool,
    initial: str = "latest",
) -> list[dict[str, Any]]:
    """Releases from newest down to `last_tag` inclusive, newest first.

    The boundary tag is kept in the window so a release that was only partly
    published is retried. Without a stored tag this is a first run:
    `initial="latest"` baselines on the newest release only, `initial="all"`
    backfills the whole fetched window.
    """
    publishable = [r for r in releases if is_publishable(r, include_prereleases=include_prereleases)]
    if not publishable:
        return []
    if last_tag is None:
        return publishable if initial == "all" else publishable[:1]

    fresh: list[dict[str, Any]] = []
    for release in publishable:
        fresh.append(release)
        if release_tag(release) == last_tag:
            break
    return fresh
