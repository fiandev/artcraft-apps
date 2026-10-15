from pathlib import Path

import pytest

from coprsync.config import App, Config
from coprsync.errors import CoprError
from coprsync.rpmmeta import RpmMeta
from coprsync.state import State
from coprsync.sync import Syncer

META = RpmMeta(
    name="x", epoch="", version="1", release="1", license="MIT", summary="s",
    description="d", vendor="", url="", group="", arch="x86_64",
    requires=(), files=("/usr/bin/x",),
)

CHROOTS = {
    "x86_64": ("fedora-45-x86_64",),
    "aarch64": ("fedora-45-aarch64",),
}


def config(chroots=None):
    return Config(
        owner="tester",
        copr_url="https://copr.example",
        github_org="storytold",
        chroots=chroots if chroots is not None else dict(CHROOTS),
        apps=(App("photocraft", "photocraft"),),
    )


def release(tag, assets, *, prerelease=False):
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": prerelease,
        "assets": [
            {"name": name, "url": f"https://api.example/{name}", "size": 3} for name in assets
        ],
    }


class FakeGitHub:
    def __init__(self, releases):
        self._releases = releases
        self.downloads = []

    def releases(self, org, repo):
        return self._releases

    def download(self, url, dest, expected_size=None):
        self.downloads.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"rpm")
        return dest


class FakePublisher:
    def __init__(self, *, dry_run=False, fail=()):
        self.dry_run = dry_run
        self.fail = set(fail)
        self.published = []
        self.plans = []
        self.projects = []

    def ensure_project(self, app, chroots):
        self.projects.append((app.project, tuple(chroots)))

    def plan(self, project, asset, chroots):
        self.plans.append((project, asset, tuple(chroots)))

    def publish(self, app, rpm_path, meta, chroots, workdir):
        if rpm_path.name in self.fail:
            raise CoprError("upstream blew up")
        self.published.append((rpm_path.name, tuple(chroots)))
        return 42


@pytest.fixture(autouse=True)
def no_rpm_tooling(monkeypatch):
    monkeypatch.setattr("coprsync.sync.read_rpm", lambda path: META)


def build(tmp_path, releases, *, dry_run=False, fail=(), initial="latest"):
    cfg = config()
    github = FakeGitHub(releases)
    publisher = FakePublisher(dry_run=dry_run, fail=fail)
    state = State(tmp_path / "state.json")
    syncer = Syncer(cfg, state, github, publisher, tmp_path / "work", initial=initial)
    return cfg, github, publisher, state, syncer


def test_publishes_each_architecture_and_records_state(tmp_path):
    releases = [release("v1", ["x-1-linux-x86_64.rpm", "x-1-linux-aarch64.rpm"])]
    _, github, publisher, state, syncer = build(tmp_path, releases)

    summary = syncer.run(config().apps)

    assert (summary.published, summary.failed, summary.skipped) == (2, 0, 0)
    assert publisher.projects == [("photocraft", ("fedora-45-x86_64", "fedora-45-aarch64"))]
    assert state.last_tag("photocraft") == "v1"
    assert state.is_published("photocraft", "v1", "x-1-linux-aarch64.rpm")
    assert list((tmp_path / "work").glob("*")) == []


def test_unconfigured_architecture_is_skipped(tmp_path):
    releases = [release("v1", ["x-1-linux-x86_64.rpm", "x-1-linux-riscv64.rpm"])]
    _, github, publisher, state, syncer = build(tmp_path, releases)

    summary = syncer.run(config().apps)

    assert (summary.published, summary.skipped) == (1, 1)
    assert [name for name, _ in publisher.published] == ["x-1-linux-x86_64.rpm"]
    assert state.last_tag("photocraft") == "v1"


def test_download_error_is_reported_not_raised(tmp_path):
    releases = [release("v1", ["x-1-linux-x86_64.rpm", "x-1-linux-aarch64.rpm"])]
    _, github, publisher, state, syncer = build(
        tmp_path, releases, fail=["x-1-linux-aarch64.rpm"]
    )

    summary = syncer.run(config().apps)

    assert (summary.published, summary.failed) == (1, 1)
    assert summary.ok is False
    assert state.is_published("photocraft", "v1", "x-1-linux-x86_64.rpm")
    assert not state.is_published("photocraft", "v1", "x-1-linux-aarch64.rpm")


def test_partial_release_resumes_on_the_next_run(tmp_path):
    releases = [release("v1", ["x-1-linux-x86_64.rpm", "x-1-linux-aarch64.rpm"])]
    _, github, publisher, state, syncer = build(
        tmp_path, releases, fail=["x-1-linux-aarch64.rpm"]
    )
    syncer.run(config().apps)
    assert github.downloads == [
        "https://api.example/x-1-linux-x86_64.rpm",
        "https://api.example/x-1-linux-aarch64.rpm",
    ]

    _, retry_github, retry_publisher, retry_state, retry = build(tmp_path, releases)
    summary = retry.run(config().apps)

    assert summary.published == 1
    assert retry_github.downloads == ["https://api.example/x-1-linux-aarch64.rpm"]
    assert retry_publisher.published == [("x-1-linux-aarch64.rpm", ("fedora-45-aarch64",))]
    assert retry_state.is_published("photocraft", "v1", "x-1-linux-x86_64.rpm")


def test_dry_run_touches_nothing(tmp_path):
    releases = [release("v1", ["x-1-linux-x86_64.rpm"])]
    _, github, publisher, state, syncer = build(tmp_path, releases, dry_run=True)

    summary = syncer.run(config().apps)

    assert summary.published == 1
    assert github.downloads == []
    assert publisher.published == []
    assert publisher.plans == [("photocraft", "x-1-linux-x86_64.rpm", ("fedora-45-x86_64",))]
    assert state.last_tag("photocraft") is None
    assert not (tmp_path / "state.json").exists()


def test_release_without_rpms_advances_the_boundary(tmp_path):
    releases = [release("v1", ["x-1-macos-universal.dmg"])]
    _, github, publisher, state, syncer = build(tmp_path, releases)

    summary = syncer.run(config().apps)

    assert summary.published == 0
    assert state.last_tag("photocraft") == "v1"
    assert publisher.projects == []


def test_prerelease_is_ignored_by_default(tmp_path):
    releases = [release("v2", ["x-2-linux-x86_64.rpm"], prerelease=True)]
    _, github, publisher, state, syncer = build(tmp_path, releases)

    summary = syncer.run(config().apps)

    assert summary.published == 0
    assert state.last_tag("photocraft") is None


def test_upstream_failure_does_not_advance_past_work(tmp_path):
    """A no-op release must not move the boundary over a release that failed."""
    releases = [
        release("v2", ["x-2-macos-universal.dmg"]),
        release("v1", ["x-1-linux-x86_64.rpm"]),
    ]
    _, github, publisher, state, syncer = build(
        tmp_path, releases, fail=["x-1-linux-x86_64.rpm"], initial="all"
    )

    syncer.run(config().apps)

    assert state.last_tag("photocraft") is None
    assert not state.is_published("photocraft", "v2", "x-2-macos-universal.dmg")


def test_workdir_is_cleaned_after_each_asset(tmp_path):
    releases = [release("v1", ["x-1-linux-x86_64.rpm"])]
    _, _, _, _, syncer = build(tmp_path, releases)

    syncer.run(config().apps)

    assert list((tmp_path / "work").glob("*")) == []
