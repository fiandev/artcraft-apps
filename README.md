# artcraft-apps

**A personal mirror, not a distribution.** This repo exists so updates to
ArtCraft's apps land in my own Copr namespace and a plain `dnf upgrade` picks
them up. The packages are not mine — I did not write them, I do not support
them, and bugs belong upstream. See [Credit](#credit) and
[Disclaimer](#disclaimer).

Point `dnf` at one project and you are done:

```sh
sudo dnf copr enable alfiansa/photocraft
sudo dnf install photocraft
```

From then on this repo keeps it current on its own. Every hour a GitHub Actions
job lists the releases of
[github.com/storytold](https://github.com/storytold), and when the original repo
publishes a new one it pulls the `.rpm` assets from that latest release and
pushes them into the Copr project of the same name, `alfiansa/<repo>`.

## Why it repackages instead of just uploading

`copr-cli uploadrpm` would be the obvious tool: it publishes a prebuilt binary
RPM and skips the source build. Public Copr does not allow it.

- `copr.fedorainfracloud.org/api_3/swagger.json` exposes `/build/create/upload`
  (SRPM) but not `/build/create/rpm-upload`.
- `DIRECT_RPM_UPLOAD` defaults to `False` in Copr's frontend config and is off
  on the public instance ([fedora-copr/copr#4365](https://github.com/fedora-copr/copr/issues/4365)).

So the default path is `srpm`: coprsync reads the upstream RPM's own metadata,
generates a spec that carries that RPM as `Source0`, unpacks it in `%prep` and
installs the existing payload in `%install` — no compiler, no rebuild from
source. Copr then builds those files for each configured chroot. The result is
the same payload with identical runtime dependencies, rebuilt and signed by
Copr, so it is not bit-identical to the upstream file.

`--strategy uploadrpm` is available for a self-hosted Copr with
`DIRECT_RPM_UPLOAD = True`. `--strategy auto` (the default) probes the
instance's API and picks whichever it offers.

## How updates work

Upstream ships by tagging a release and attaching prebuilt Linux packages. You
do not have to watch for it:

1. Hourly, the job lists the releases of every repo in `config/apps.yaml`.
2. Releases already mirrored are skipped — that is what `state/state.json` is for.
3. For a release it has not seen, it downloads each `.rpm` asset straight from
   the GitHub release and submits it to Copr, one build per configured chroot.
4. Copr builds it, signs it, and refreshes the repository metadata.

Within the hour, `sudo dnf upgrade` offers the new version. Nothing runs on your
machine and there is no daemon or timer to maintain — the release you get is
upstream's, re-published.

If upstream goes quiet, nothing happens and nothing breaks. The last mirrored
release just stays installed.

## What gets watched

`config/apps.yaml` holds the allowlist. Today that is the 14 upstream repos
that ship `.rpm`: photocraft, pdfcraft, filmcraft, vectorcraft, lightcraft,
designcraft, effectcraft, gridcraft, cadcraft, deckcraft, soundcraft, wordcraft,
figcraft and craft-launcher.

Each release is published per architecture (`x86_64`, `aarch64`, `riscv64`) to
the chroots listed for that architecture. Assets with an architecture that has
no configured chroots are skipped and counted.

## Credit

**All credit for these applications belongs to the ArtCraft team at
[storytold](https://github.com/storytold).** They design, build, package and
release every one of them. Nothing here is my work; I only re-publish their own
release binaries so that `dnf` can keep them up to date.

Most of these repos are staffed by the same handful of people, and issues,
pull requests and donations — whatever the upstream project asks for — should go
to them:

- Org: <https://github.com/storytold>
- Website: <https://getartcraft.com>
- YouTube: [@OfficialArtCraftStudios](https://www.youtube.com/@OfficialArtCraftStudios)
- X: [@get_artcraft](https://x.com/get_artcraft)

ArtCraft, PhotoCraft, FilmCraft and the rest are their names and marks. The code
is theirs under their licences (MIT / Apache-2.0); the licence files ship inside
each package under `/usr/share/doc/<package>/`.

## Disclaimer

This Copr namespace is an unofficial, unaffiliated personal mirror. It is not
endorsed by, supported by, or connected to the ArtCraft team in any way.

**Report problems upstream, not here.** A crash, a missing dependency or a bad
build has to be fixed in their repo — I can only mirror what they release.

## Setup

1. **Copr account.** `owner` in `config/apps.yaml` is the Fedora account name,
   not the GitHub one — it is currently `alfiansa`. Two projects already exist
   there (`snapmit`, `postman`) and neither collides with the names this creates.

2. **API token.** Get it from <https://copr.fedorainfracloud.org/api/> and store
   it as the repository secret `COPR_CONFIG`:

   ```sh
   gh secret set COPR_CONFIG --repo <owner>/artcraft-apps < ~/.config/copr
   ```

   The secret is the block the API page tells you to paste into `~/.config/copr`
   (INI), and the same fields as YAML are also accepted, nested or flat:

   ```ini
   [copr-cli]
   login = <login hash>
   username = <username>
   token = <token>
   copr_url = https://copr.fedorainfracloud.org
   ```

   ```yaml
   copr-cli:
     login: <login hash>
     username: <username>
     token: <token>
     copr_url: https://copr.fedorainfracloud.org
   ```

   `username` must match `owner` in `config/apps.yaml`, or Copr rejects the
   builds. The instance URL comes from `config/apps.yaml`; if `copr_url` in the
   secret disagrees, the run logs a warning and uses the config. Tokens expire
   after 180 days, after which authentication fails with a clear error.

3. **Let Actions write.** `Settings → Actions → General → Workflow permissions`
   must allow read **and write**, because the job commits `state/` back to
   `main`.

4. Run **Sync Copr** once with `dry_run` enabled to see the plan.

## Running locally

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
GH_TOKEN=$(gh auth token) .venv/bin/coprsync check          # plan only
GH_TOKEN=$(gh auth token) .venv/bin/coprsync sync --only photocraft
```

`check` never writes to Copr and never downloads assets. `sync` needs
`rpmbuild` and `rpm2cpio` on `PATH` (Fedora: `rpm-build`; Debian/Ubuntu:
`rpm` + `cpio`).

| Flag | Meaning |
| --- | --- |
| `--strategy auto\|uploadrpm\|srpm` | How to publish; `auto` probes the instance |
| `--only a,b` | Subset of the allowlist, rejected if not listed |
| `--initial latest\|all` | First run with no state: newest release, or backfill everything fetched |
| `--dry-run` | Report only |
| `--fail-fast` | Stop at the first failure |

## State

`state/state.json` records, per repo, the newest release the scan stops at and
which assets of it reached Copr. It is committed by the workflow.

The boundary tag stays *inside* the scan window, so a release that failed
halfway is retried on the next run without re-publishing the assets that
already succeeded. Records for older tags are dropped once the boundary moves
past them.

## Layout

```
config/apps.yaml        owner, Copr URL, chroots per arch, allowlist
state/state.json        last published tag + assets per repo
src/coprsync/
  config.py             config loading and validation
  github.py             GitHub REST client (urllib, retries)
  releases.py           tags, .rpm assets, arch extraction, scan window
  rpmmeta.py            rpm -qp metadata, requires and file list
  repack.py             spec generation + rpmbuild -bs
  coprclient.py         capability probe, project setup, build submission
  state.py              resume bookkeeping
  sync.py               orchestration
  cli.py                sync / check
```

## Notes and limits

- Upstream RPMs are unsigned; Copr signs what it builds.
- Only files are listed in `%files`; parent directories are created implicitly
  and therefore not owned by the package, matching Fedora packaging practice.
- `Requires` from the upstream RPM are copied verbatim (`AutoReqProv: no`),
  because upstream lists `dlopen`ed libraries that a dependency scan would
  miss.
- A release with no `.rpm` assets still advances the boundary so it is not
  re-examined every hour.
