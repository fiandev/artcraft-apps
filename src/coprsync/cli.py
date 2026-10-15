"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .config import DEFAULT_CONFIG_PATH, load_config
from .coprclient import CoprPublisher
from .errors import CoprSyncError
from .github import GitHubClient
from .state import State
from .sync import Syncer

STRATEGIES = ("auto", "uploadrpm", "srpm")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)-7s %(message)s")

    dry_run = args.dry_run or args.command == "check"
    try:
        config = load_config(args.config)
        apps = config.select(args.only.split(",") if args.only else None)
        state = State(args.state)
        github = GitHubClient(os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
        publisher = CoprPublisher(config, strategy=args.strategy, dry_run=dry_run)
        syncer = Syncer(config, state, github, publisher, Path(args.workdir),
                        initial=args.initial, fail_fast=args.fail_fast)

        logging.getLogger("coprsync").info(
            "owner=%s copr=%s apps=%d strategy=%s%s",
            config.owner, config.copr_url, len(apps), publisher.resolve_strategy(),
            " (dry run)" if dry_run else "",
        )
        summary = syncer.run(apps)
    except CoprSyncError as exc:
        logging.getLogger("coprsync").error("%s", exc)
        return 2

    leaf = logging.getLogger("coprsync")
    leaf.info("published=%d skipped=%d failed=%d", summary.published, summary.skipped, summary.failed)
    return 0 if summary.ok else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coprsync",
        description="Mirror storytold release RPMs into Copr projects.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("sync", "publish new upstream releases into Copr"),
        ("check", "report what sync would publish, without touching Copr"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), type=Path)
        cmd.add_argument("--state", default="state/state.json", type=Path)
        cmd.add_argument("--workdir", default="work", type=Path,
                         help="scratch space for downloads and RPM builds")
        cmd.add_argument("--strategy", choices=STRATEGIES, default="auto")
        cmd.add_argument("--only", default="",
                         help="comma-separated subset of the apps allowlist")
        cmd.add_argument("--initial", choices=("latest", "all"), default="latest",
                         help="what to do on a first run with no state")
        cmd.add_argument("--dry-run", action="store_true")
        cmd.add_argument("--fail-fast", action="store_true",
                         help="stop at the first failure instead of continuing")
        cmd.add_argument("-v", "--verbose", action="store_true")
    return parser


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
