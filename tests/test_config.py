import pytest

from coprsync.config import load_config
from coprsync.errors import ConfigError

MINIMAL = """
owner: fiandev
github_org: storytold
chroots:
  x86_64: [fedora-rawhide-x86_64]
apps: [photocraft]
"""


def write(tmp_path, text):
    path = tmp_path / "apps.yaml"
    path.write_text(text)
    return path


def test_minimal_config(tmp_path):
    config = load_config(write(tmp_path, MINIMAL))
    assert config.owner == "fiandev"
    assert config.copr_url == "https://copr.fedorainfracloud.org"
    assert config.all_chroots == ("fedora-rawhide-x86_64",)
    assert config.apps[0].repo == config.apps[0].project == "photocraft"
    assert config.include_prereleases is False


def test_long_form_app_and_deduped_chroots(tmp_path):
    config = load_config(
        write(
            tmp_path,
            """
owner: fiandev
github_org: storytold
chroots:
  x86_64: [fedora-45-x86_64, fedora-rawhide-x86_64, fedora-rawhide-x86_64]
  aarch64: [fedora-rawhide-aarch64]
apps:
  - {repo: craft-launcher, project: launcher}
  - pdfcraft
""",
        )
    )
    assert [a.project for a in config.apps] == ["launcher", "pdfcraft"]
    assert config.all_chroots == (
        "fedora-45-x86_64",
        "fedora-rawhide-x86_64",
        "fedora-rawhide-aarch64",
    )
    assert config.chroots_for("riscv64") == ()


def test_select_rejects_unknown_repo(tmp_path):
    config = load_config(write(tmp_path, MINIMAL))
    with pytest.raises(ConfigError, match="not in the apps allowlist"):
        config.select(["nope"])
    assert config.select(["photocraft"])[0].repo == "photocraft"
    assert len(config.select(None)) == 1


def test_chroot_must_match_architecture(tmp_path):
    with pytest.raises(ConfigError, match="does not belong to architecture"):
        load_config(
            write(
                tmp_path,
                "owner: a\ngithub_org: b\nchroots:\n  x86_64: [fedora-rawhide-aarch64]\napps: [x]\n",
            )
        )


def test_duplicate_project_rejected(tmp_path):
    with pytest.raises(ConfigError, match="used by more than one app"):
        load_config(
            write(
                tmp_path,
                "owner: a\ngithub_org: b\nchroots:\n  x86_64: [fedora-rawhide-x86_64]\n"
                "apps:\n  - {repo: x, project: same}\n  - {repo: y, project: same}\n",
            )
        )


def test_disabled_entries_are_dropped(tmp_path):
    config = load_config(
        write(
            tmp_path,
            MINIMAL.replace("apps: [photocraft]", "apps:\n  - {repo: a, enabled: false}\n  - b\n"),
        )
    )
    assert [a.repo for a in config.apps] == ["b"]


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.yaml")
