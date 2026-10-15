"""Copr side of the pipeline: capability probe, project setup, build submission."""

from __future__ import annotations

import configparser
import json
import logging
import os
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from copr.v3 import Client
from copr.v3.exceptions import CoprException, CoprNoResultException

from .config import App, Config
from .errors import CoprError
from .repack import build_srpm
from .rpmmeta import RpmMeta

DEFAULT_COPR_CONFIG = Path.home() / ".config" / "copr"
RPM_UPLOAD_PATH = "/build/create/rpm-upload"
log = logging.getLogger("coprsync")


class CoprPublisher:
    def __init__(self, config: Config, *, strategy: str = "auto", dry_run: bool = False,
                 log: Callable[[str], None] = log.info) -> None:
        self.config = config
        self.strategy = strategy
        self.dry_run = dry_run
        self.log = log
        self._client: Client | None = None
        self._paths: set[str] | None = None

    def resolve_strategy(self) -> str:
        """`auto` prefers direct binary upload, but only where Copr offers it."""
        if self.strategy != "auto":
            return self.strategy
        return "uploadrpm" if RPM_UPLOAD_PATH in self.api_paths() else "srpm"

    def api_paths(self) -> set[str]:
        if self._paths is None:
            self._paths = self._fetch_api_paths()
        return self._paths

    def ensure_project(self, app: App, chroots: tuple[str, ...]) -> None:
        project = app.project
        if self.dry_run:
            self.log(f"  [dry-run] would ensure project {self.config.owner}/{project}")
            return

        try:
            existing = self.client.project_proxy.get(self.config.owner, project)
        except CoprNoResultException:
            self.client.project_proxy.add(
                self.config.owner,
                project,
                chroots=list(chroots),
                description=(
                    f"Unofficial builds of {app.repo}, repackaged from the upstream "
                    f"GitHub release binaries."
                ),
                instructions=f"sudo dnf copr enable {self.config.owner}/{project}",
                homepage=f"https://github.com/{self.config.github_org}/{app.repo}",
                exist_ok=True,
            )
            self.log(f"  created project {self.config.owner}/{project}")
            return

        have = set(existing.get("chroots") or ())
        missing = [chroot for chroot in chroots if chroot not in have]
        if missing:
            merged = sorted(have | set(missing))
            self.client.project_proxy.edit(self.config.owner, project, chroots=merged)
            self.log(f"  added chroots to {self.config.owner}/{project}: {', '.join(missing)}")

    def plan(self, project: str, asset: str, chroots: tuple[str, ...]) -> None:
        """Report what `publish` would do, without downloading or submitting."""
        self.log(
            f"  [dry-run] would publish {asset} to {self.config.owner}/{project} "
            f"via {self.resolve_strategy()} for {', '.join(chroots)}"
        )

    def publish(self, app: App, rpm_path: Path, meta: RpmMeta,
                chroots: tuple[str, ...], workdir: Path) -> int:
        strategy = self.resolve_strategy()
        buildopts = {"chroots": list(chroots)}
        try:
            if strategy == "uploadrpm":
                tarball = _make_upload_tarball(rpm_path, workdir)
                build = self.client.build_proxy.create_from_rpm_upload(
                    self.config.owner,
                    app.project,
                    tarball_path=str(tarball),
                    name=meta.name,
                    version=meta.version,
                    release=meta.release,
                    buildopts=buildopts,
                )
            else:
                srpm = build_srpm(rpm_path, meta, workdir)
                build = self.client.build_proxy.create_from_file(
                    self.config.owner,
                    app.project,
                    path=str(srpm),
                    buildopts=buildopts,
                )
        except CoprException as exc:
            raise CoprError(f"publishing {rpm_path.name} failed: {exc}") from exc
        return int(build.id)

    @property
    def client(self) -> Client:
        if self._client is None:
            self._client = _load_client(self.config.copr_url)
        return self._client

    def _fetch_api_paths(self) -> set[str]:
        url = f"{self.config.copr_url}/api_3/swagger.json"
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                spec: dict[str, Any] = json.load(response)
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            self.log(f"  could not read {url} ({exc}); assuming SRPM builds")
            return set()
        return set(spec.get("paths", {}))


def _make_upload_tarball(rpm_path: Path, workdir: Path) -> Path:
    """Copr wants a .tar.gz holding one top-level directory of RPM payloads."""
    staging = Path(tempfile.mkdtemp(prefix="upload-", dir=workdir))
    payload = staging / "payload"
    payload.mkdir()
    shutil.copy2(rpm_path, payload / rpm_path.name)
    tarball = staging / f"{rpm_path.stem}.tar.gz"
    with tarfile.open(tarball, "w:gz") as archive:
        archive.add(payload, arcname="payload")
    return tarball


def _load_client(copr_url: str) -> Client:
    path = Path(os.environ.get("COPR_CONFIG_FILE", DEFAULT_COPR_CONFIG))
    if not path.exists():
        raise CoprError(
            f"no Copr credentials at {path}; export COPR_CONFIG or write your "
            "~/.config/copr (see README)"
        )
    parser = configparser.RawConfigParser()  # tokens contain '%'
    parser.read(path)
    if not parser.has_section("copr-cli"):
        raise CoprError(f"{path} has no [copr-cli] section")
    try:
        return Client(
            {
                "username": parser.get("copr-cli", "username"),
                "login": parser.get("copr-cli", "login"),
                "token": parser.get("copr-cli", "token"),
                "copr_url": copr_url,
            }
        )
    except (configparser.NoOptionError, KeyError) as exc:
        raise CoprError(f"{path} is missing a required key: {exc}") from exc
