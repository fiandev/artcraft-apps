"""Walk the allowlist, find new upstream releases, hand their RPMs to Copr."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import App, Config
from .coprclient import CoprPublisher
from .errors import CoprSyncError
from .github import GitHubClient
from .releases import RpmAsset, new_releases, release_tag, rpm_assets
from .rpmmeta import read_rpm
from .state import State

log = logging.getLogger("coprsync")


@dataclass
class Summary:
    published: int = 0
    skipped: int = 0
    failed: int = 0

    @property
    def ok(self) -> bool:
        return self.failed == 0


class Syncer:
    def __init__(self, config: Config, state: State, github: GitHubClient,
                 publisher: CoprPublisher, workdir: Path, *, initial: str = "latest",
                 fail_fast: bool = False) -> None:
        self.config = config
        self.state = state
        self.github = github
        self.publisher = publisher
        self.workdir = workdir
        self.initial = initial
        self.fail_fast = fail_fast
        self.dry_run = publisher.dry_run

    def run(self, apps: tuple[App, ...]) -> Summary:
        summary = Summary()
        for app in apps:
            try:
                self._sync_app(app, summary)
            except CoprSyncError as exc:
                summary.failed += 1
                log.error("%s: %s", app.repo, exc)
                if self.fail_fast:
                    raise
        return summary

    def _sync_app(self, app: App, summary: Summary) -> None:
        releases = self.github.releases(self.config.github_org, app.repo)
        fresh = new_releases(
            releases,
            self.state.last_tag(app.repo),
            include_prereleases=self.config.include_prereleases,
            initial=self.initial,
        )
        if not fresh:
            log.info("%s: up to date", app.repo)
            return
        log.info("%s: %d release(s) in range", app.repo, len(fresh))

        failed_at_entry = summary.failed
        project_ready = False
        for release in reversed(fresh):  # oldest first, so the boundary moves forward
            tag = release_tag(release)
            pending = [
                asset
                for asset in rpm_assets(release)
                if not self.state.is_published(app.repo, tag, asset.name)
            ]
            if not pending:
                # A release with nothing to publish still has to move the
                # boundary, otherwise it is re-examined every hour. Skipped when
                # an older release in this app failed, so the boundary never
                # jumps past work that is still owed.
                self._advance(app, tag, summary.failed == failed_at_entry)
                continue
            if not project_ready:
                self.publisher.ensure_project(app, self.config.all_chroots)
                project_ready = True
            for asset in pending:
                self._publish_asset(app, release, asset, summary)
            self._advance(app, tag, summary.failed == failed_at_entry)

    def _advance(self, app: App, tag: str, clean: bool) -> None:
        if self.dry_run or not clean:
            return
        self.state.advance(app.repo, tag)
        self.state.save()

    def _publish_asset(self, app: App, release: dict, asset: RpmAsset, summary: Summary) -> None:
        tag = release_tag(release)
        chroots = self.config.chroots_for(asset.arch)
        if not chroots:
            log.info("  %s: no chroots configured for %s; skipping", asset.name, asset.arch)
            summary.skipped += 1
            return

        if self.dry_run:
            self.publisher.plan(app.project, asset.name, chroots)
            summary.published += 1
            return

        log.info("  %s -> %s/%s (%s)", asset.name, self.config.owner, app.project, ", ".join(chroots))
        workdir = self.workdir / f"{app.repo}-{tag}"
        try:
            rpm_path = self.github.download(
                asset.url, workdir / asset.name, expected_size=asset.size or None
            )
            meta = read_rpm(rpm_path)
            build_id = self.publisher.publish(app, rpm_path, meta, chroots, workdir)
            self.state.record(app.repo, tag, asset.name, list(chroots), build_id)
            self.state.save()
            summary.published += 1
        except CoprSyncError as exc:
            summary.failed += 1
            log.error("  %s: %s", asset.name, exc)
            if self.fail_fast:
                raise
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
