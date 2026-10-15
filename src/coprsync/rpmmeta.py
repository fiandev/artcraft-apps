"""Read metadata out of a prebuilt upstream RPM using the `rpm` CLI."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import RpmError

FIELD_SEP = "\x1f"
NONE = "(none)"

QUERY_FORMAT = FIELD_SEP.join(
    [
        "%{NAME}",
        "%{EPOCH}",
        "%{VERSION}",
        "%{RELEASE}",
        "%{LICENSE}",
        "%{SUMMARY}",
        "%{VENDOR}",
        "%{URL}",
        "%{GROUP}",
        "%{DESCRIPTION}",
        "%{ARCH}",
    ]
)


@dataclass(frozen=True)
class RpmMeta:
    name: str
    epoch: str
    version: str
    release: str
    license: str
    summary: str
    description: str
    vendor: str
    url: str
    group: str
    arch: str
    requires: tuple[str, ...]
    files: tuple[str, ...]


def read_rpm(path: Path) -> RpmMeta:
    fields = _run(["rpm", "-qp", "--qf", QUERY_FORMAT, str(path)]).split(FIELD_SEP)
    if len(fields) != 11:
        raise RpmError(f"unexpected rpm query output for {path}")

    name, epoch, version, release, license_, summary, vendor, url, group, desc, arch = [
        _clean(value) for value in fields
    ]
    if not name or not version or not release:
        raise RpmError(f"{path} has no name/version/release")

    return RpmMeta(
        name=name,
        epoch="" if epoch == NONE else epoch,
        version=version,
        release=release,
        license=license_ or "Unlicense",
        summary=summary or name,
        description=desc or summary or name,
        vendor="" if vendor == NONE else vendor,
        url="" if url == NONE else url,
        group="" if group in (NONE, "Unspecified", "Unclassified", "(none)") else group,
        arch=arch,
        requires=_requires(path),
        files=_files(path),
    )


def _requires(path: Path) -> tuple[str, ...]:
    """Runtime deps, minus the rpmlib()/rtld() pseudo-requires rpmbuild re-adds."""
    lines = _run(["rpm", "-qp", "--requires", str(path)]).splitlines()
    return tuple(
        line.strip()
        for line in lines
        if line.strip() and not line.startswith(("rpmlib(", "rtld("))
    )


def _files(path: Path) -> tuple[str, ...]:
    """Regular files and symlinks only; directories are created implicitly.

    rpm's --qf passes FIELD_SEP through as a literal byte (it does not expand
    \\x escapes), so the separator is embedded directly rather than escaped.
    """
    listing = _run(
        ["rpm", "-qp", "--qf", f"[%{{FILENAMES}}{FIELD_SEP}%{{FILEMODES:perms}}\\n]", str(path)]
    )
    files: list[str] = []
    for line in listing.splitlines():
        if FIELD_SEP not in line:
            continue
        filename, perms = line.split(FIELD_SEP, 1)
        if perms.startswith("d") or not filename:
            continue
        files.append(filename)
    if not files:
        raise RpmError(f"{path} contains no files to repackage")
    return tuple(files)


def _run(argv: list[str]) -> str:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise RpmError("the 'rpm' tool is not installed; install the rpm package") from exc
    if result.returncode != 0:
        raise RpmError(f"{' '.join(argv)} failed: {result.stderr.strip()}")
    return result.stdout


def _clean(value: str) -> str:
    return value.strip()
