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

import yaml
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
            f"no Copr credentials at {path}; set the COPR_CONFIG secret (see README)"
        )
    creds = read_credentials(path)
    declared_url = creds.get("copr_url")
    if declared_url and declared_url.rstrip("/") != copr_url:
        log.warning(
            "  %s declares copr_url=%s but config/apps.yaml says %s; using the config",
            path, declared_url, copr_url,
        )
    return Client(
        {
            "username": creds["username"],
            "login": creds["login"],
            "token": creds["token"],
            "copr_url": copr_url,
        }
    )


def read_credentials(path: Path) -> dict[str, str]:
    """Read a Copr credential file as either the INI `~/.config/copr` or YAML.

    The API page prints an INI block to paste into ~/.config/copr, but pasting
    the same fields as YAML is a natural mistake, so both are accepted.
    """
    text = path.read_text()
    creds = _parse_ini(text) or _parse_yaml(text)
    if creds is None:
        raise CoprError(
            f"{path} is neither the INI block from copr's /api/ page nor the same "
            "fields as YAML"
        )
    missing = [key for key in ("username", "login", "token") if not creds.get(key)]
    if missing:
        raise CoprError(f"{path} is missing: {', '.join(missing)}")
    return creds


def _parse_ini(text: str) -> dict[str, str] | None:
    parser = configparser.RawConfigParser()
    try:
        parser.read_string(text)
    except configparser.Error:
        return None
    for section in parser.sections():
        if section.strip().lower() in ("copr-cli", "copr"):
            return {key.lower(): value for key, value in parser.items(section)}
    return None


def _parse_yaml(text: str) -> dict[str, str] | None:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    block = data.get("copr-cli") or data.get("copr_cli") or data
    if not isinstance(block, dict):
        return None
    return {
        str(key).lower(): str(value).strip()
        for key, value in block.items()
        if isinstance(value, (str, int))
    }
