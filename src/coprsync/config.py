"""Load and validate config/apps.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from .errors import ConfigError

DEFAULT_CONFIG_PATH = Path("config/apps.yaml")
DEFAULT_COPR_URL = "https://copr.fedorainfracloud.org"


@dataclass(frozen=True)
class App:
    repo: str
    project: str


@dataclass(frozen=True)
class Config:
    owner: str
    copr_url: str
    github_org: str
    chroots: dict[str, tuple[str, ...]]
    apps: tuple[App, ...]
    include_prereleases: bool = False

    @property
    def all_chroots(self) -> tuple[str, ...]:
        """Every configured chroot, de-duplicated, in declaration order."""
        ordered: list[str] = []
        for chroots in self.chroots.values():
            for chroot in chroots:
                if chroot not in ordered:
                    ordered.append(chroot)
        return tuple(ordered)

    def chroots_for(self, arch: str) -> tuple[str, ...]:
        return self.chroots.get(arch, ())

    def select(self, repos: Iterable[str] | None) -> tuple[App, ...]:
        """Restrict the allowlist to `repos`, rejecting names outside it."""
        wanted = {repo.strip() for repo in repos or () if repo.strip()}
        if not wanted:
            return self.apps
        known = {app.repo for app in self.apps}
        unknown = sorted(wanted - known)
        if unknown:
            raise ConfigError(
                "not in the apps allowlist of config/apps.yaml: " + ", ".join(unknown)
            )
        return tuple(app for app in self.apps if app.repo in wanted)


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> Config:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text())
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a YAML mapping")

    return Config(
        owner=_string(raw, "owner"),
        copr_url=str(raw.get("copr_url") or DEFAULT_COPR_URL).rstrip("/"),
        github_org=_string(raw, "github_org"),
        chroots=_parse_chroots(raw.get("chroots")),
        apps=_parse_apps(raw.get("apps")),
        include_prereleases=bool(raw.get("include_prereleases", False)),
    )


def _string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"'{key}' must be a non-empty string")
    return value.strip()


def _parse_chroots(raw: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(raw, dict) or not raw:
        raise ConfigError("'chroots' must map an architecture to a list of chroots")

    chroots: dict[str, tuple[str, ...]] = {}
    for arch, names in raw.items():
        if not isinstance(arch, str) or not arch.strip():
            raise ConfigError(f"invalid architecture key in 'chroots': {arch!r}")
        arch = arch.strip()
        if not isinstance(names, list) or not names:
            raise ConfigError(f"'chroots.{arch}' must be a non-empty list")
        resolved: list[str] = []
        for name in names:
            if not isinstance(name, str) or not name.strip():
                raise ConfigError(f"'chroots.{arch}' contains a non-string entry")
            name = name.strip()
            if not name.endswith(f"-{arch}"):
                raise ConfigError(
                    f"chroot '{name}' does not belong to architecture '{arch}'"
                )
            if name not in resolved:
                resolved.append(name)
        chroots[arch] = tuple(resolved)
    return chroots


def _parse_apps(raw: Any) -> tuple[App, ...]:
    if not isinstance(raw, list) or not raw:
        raise ConfigError("'apps' must be a non-empty list")

    apps: list[App] = []
    seen_repos: set[str] = set()
    seen_projects: set[str] = set()
    for entry in raw:
        if isinstance(entry, str):
            repo = project = entry.strip()
            enabled = True
        elif isinstance(entry, dict):
            repo = str(entry.get("repo", "")).strip()
            project = str(entry.get("project") or repo).strip()
            enabled = bool(entry.get("enabled", True))
        else:
            raise ConfigError(f"'apps' entry must be a string or mapping: {entry!r}")

        if not repo:
            raise ConfigError(f"'apps' entry has no repo name: {entry!r}")
        if not enabled:
            continue
        if not project:
            raise ConfigError(f"'apps' entry for {repo} has an empty project name")
        if repo in seen_repos:
            raise ConfigError(f"repo '{repo}' is listed more than once")
        if project in seen_projects:
            raise ConfigError(f"Copr project '{project}' is used by more than one app")
        seen_repos.add(repo)
        seen_projects.add(project)
        apps.append(App(repo=repo, project=project))

    if not apps:
        raise ConfigError("'apps' has no enabled entries")
    return tuple(apps)
