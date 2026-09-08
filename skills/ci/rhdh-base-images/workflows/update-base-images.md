# Base-image and RPM update workflow

Before any non-analysis run, follow the write gate in [SKILL.md](../SKILL.md): state each operation, get approval, execute, report every outcome. The commands below describe what an approved run does; printing one authorizes nothing.

## Goal

Refresh **base images** and **RPM lockfiles** in the GitHub hub/operator/must-gather repos, then pin **plugin-catalog** Node and **overlays** `versions.json` when those checkouts are named:

| Repo | Node / Go source | RPM containerfile |
|------|------------------|-------------------|
| rhdh | `build/containerfiles/Containerfile` or `docker/Dockerfile` (release-1.9) | `build/containerfiles/Containerfile` or `.rhdh/docker/Dockerfile` |
| rhdh-operator | `go.mod` aligned with `ubi10/go-toolset` on **main** only | `.rhdh/docker/Dockerfile` |
| rhdh-must-gather | — | `Containerfile` |
| rhdh-plugin-catalog | `builder.Containerfile` FROM + `.nvm/` + `konflux.additional-tags` `node-v*` | none |
| rhdh-plugin-export-overlays | `versions.json` `node` | none |

Upstream helper scripts live in GitLab midstream [rhidp/rhdh](https://gitlab.cee.redhat.com/rhidp/rhdh). For RHDH 1.y, branch is `rhdh-<stream>-rhel-9`; for RHDH 2.y, branch is either `main` or `release-2.y`. 

## Prerequisites

- `jq`, `skopeo`, `curl`, `git`
- `podman` for rhdh node header version detection (see `.nvm/releases/README.adoc`)
- `gh` when `updateBaseImages.sh` opens PRs (`--pr`, the default)
- `python3` and `pip` when `rpm-lockfile-prototype` is not already installed
- Registry auth for base image queries: `docker login registry.redhat.io` (or `skopeo login`)

Install `rpm-lockfile-prototype` manually when needed:

```bash
python3 -m pip install --user https://github.com/konflux-ci/rpm-lockfile-prototype/archive/refs/heads/main.zip 2>/dev/null
```

On Fedora/RHEL hosts, `dnf install podman skopeo python3-dnf` may also be required for lockfile generation.

## Branch mapping

Accepted `-b` values: `main` or any `release-*` branch (e.g. `release-1.9`, `release-1.10`, `release-2.1`).

| GitHub branch (`-b`) | GitLab scripts branch (`-sb` for `updateBaseImages.sh`) | plugin-catalog GitLab branch |
|----------------------|---------------------------------------------------------|------------------------------|
| `main` | `main` | `main` |
| `release-2.Y` | `release-2.Y` | `release-2.Y` |
| `release-1.Y` | `rhdh-1.Y-rhel-9` | `rhdh-1.Y-rhel-9` |

Verify the target branch exists in each repo before running.

## Run the bundled script

**Execute** [scripts/base-images-and-rpms.sh](../scripts/base-images-and-rpms.sh); do not reimplement the workflow inline.

```bash
SKILL=/path/to/installed/rhdh-base-images   # under 1-rhdh-skills checkout
chmod +x "${SKILL}/scripts/base-images-and-rpms.sh"

# All three repos under a parent directory
"${SKILL}/scripts/base-images-and-rpms.sh" -b release-1.10 --parent-dir ~/RHDH

# A RHEL 10-based stream
"${SKILL}/scripts/base-images-and-rpms.sh" -b release-2.1 --parent-dir ~/RHDH

# Explicit paths and on-disk tools
"${SKILL}/scripts/base-images-and-rpms.sh" -b main \
  --update-base-images-script ~/RHDH/rhdh/build/scripts/updateBaseImages.sh \
  --rpm-lockfile-prototype ~/.local/bin/rpm-lockfile-prototype \
  ~/RHDH/rhdh \
  ~/RHDH/rhdh-operator \
  ~/RHDH/rhdh-must-gather
```

### Flags

| Flag | Purpose |
|------|---------|
| `-b`, `--branch` | **Required.** `main` or `release-*` |
| `--update-base-images-script PATH` | Use local `updateBaseImages.sh` (expects `createPR.sh` alongside; fetches if missing) |
| `--rpm-lockfile-prototype PATH` | Use local binary; otherwise `~/.local/bin/rpm-lockfile-prototype` or pip install |
| `--parent-dir PATH` | Auto-discover `1-rhdh`, `1-rhdh-operator`, `1-must-gather` (and common aliases) |
| `REPO_DIR ...` | Explicit repo checkouts |
| `--skip-base` / `--skip-rpm` | Run only one half of the workflow |
| `--dirty` | Allow dirty trees for `updateBaseImages.sh` |
| `--push` | Let `updateBaseImages.sh` push when branch policy allows (still uses `--pr` fallback) |
| `--no-pr` | Commit locally with `--no-push` only |
| `--dry-run` | Print commands without executing |
| `--analyze` | Read-only scan via `analyze-base-images.sh` (no `-b` required; defaults scripts to `main`) |

**Default:** base image updates use `--pr --no-push` (local commits + PR creation, no push). RPM lockfile and node header changes are committed and **pushed to the same open `chore/automated-update-base-images-*` PR branch** when one exists; otherwise a `chore/automated-update-rpm-lockfile/<branch>` PR is opened.

## Analyze without updating

Use `--analyze` to scan Containerfiles and Dockerfiles without checkout, commits, or registry writes:

```bash
"${SKILL}/scripts/base-images-and-rpms.sh" --analyze --parent-dir ~/RHDH

# Optional: match GitLab scripts branch to a release line
"${SKILL}/scripts/base-images-and-rpms.sh" --analyze -b release-1.10 --parent-dir ~/RHDH
```

Or run the analyzer directly:

```bash
"${SKILL}/scripts/analyze-base-images.sh" \
  -s /path/to/rhidp/rhdh/build/scripts \
  -w ~/RHDH/rhdh \
  -w ~/RHDH/rhdh-operator
```

The analyzer reports **current vs latest** per `FROM` line, flags malformed tags, and warns on **UBI minor skew** within a file. Tags must be `major.minor-buildid` or `x.y.z-buildid`; bare numeric registry tags are ignored (same rules as `updateBaseImages.sh`). Requires `skopeo login registry.redhat.io`.

Each registry `FROM` needs a comment URL on the line above:

```containerfile
# https://registry.access.redhat.com/ubi10/nodejs-24
FROM registry.access.redhat.com/ubi10/nodejs-24:10.0-...@sha256:... AS skeleton
```

For **rhdh**, paths under `e2e-tests/` and `.ci/` are excluded from scans.

## Workflow

1. Pick branch (`-b`).
2. Ensure local clones are fetched and clean enough for `updateBaseImages.sh` (or pass `--dirty`).
3. Run the script on all three repos.
4. Review open PRs — each should include base image, `rpms.lock.yaml`, and (for rhdh) node header updates when applicable.
5. Human merges PRs; do **not** push directly to protected branches without review.

The bundled script's fixed automation PR title and body are authored artifacts,
not runtime agent prose. Keep them under the repository's static prose linter in
flavored mode. The `gh pr create` call transports those fixed strings and
must not invoke an editor during an automation run.

## What each step does

### Base images (`updateBaseImages.sh`)

Mirrors [weekly-maintenance.sh](https://gitlab.cee.redhat.com/rhidp/rhdh/-/blob/main/build/ci/weekly-maintenance.sh) upstream section:

```bash
updateBaseImages.sh -w REPO_ROOT -b BRANCH -sb SCRIPTS_BRANCH -maxdepth 5 --pr
```

`-maxdepth 5` reaches `.rhdh/docker/Dockerfile` in the operator repo as well as top-level containerfiles.

`updateBaseImages.sh` calls `createPr()` once per image bump; upstream `createPR.sh` runs `gh pr view --web` on **every** call, which re-opens the same PR URL. This skill sets `GITLAB_PIPELINE=true` during `updateBaseImages.sh` to suppress that, then opens each repo's PR once in the browser when `--pr` is in effect.

### RPM lockfiles (`rpm-lockfile-prototype`)

Matches each repo's GitHub Action, then commits and pushes to the automation PR:

```bash
rpm-lockfile-prototype -f CONTAINERFILE rpms.in.yaml
git add rpms.lock.yaml
git commit -s -m "chore: update rpms.lock.yaml [skip-build]"
git push origin <chore/automated-update-base-images-*>   # same PR as base images
```

When no base-images PR exists (e.g. `--skip-base`), the script uses `chore/automated-update-rpm-lockfile/<branch>` and opens a PR.

`rpm-lockfile-prototype` often logs `No sources found for <pkg>` when the matching source RPM is unpublished (commonly `kernel-headers` and `efi-srpm-macros`). The bundled script drops those lines. Never list them as remaining risks; Konflux still consumes the binary lockfile.

### Node headers (rhdh, then catalog and overlays)

When the UBI Node builder image (`ubi9/nodejs-*` today; `ubi10/nodejs-*` when
that line ships) in `build/containerfiles/Containerfile` (or `docker/Dockerfile`
on release-1.9) ships a different Node version than `.nvmrc` / `.nvm/releases/`,
the script:

1. Reads `node --version` from the updated builder image (`podman`/`docker`)
2. Downloads `https://nodejs.org/dist/<version>/node-<version>-headers.tar.gz` into `.nvm/releases/`
3. Updates `.nvmrc` (version without `v` prefix) and `.nvm/releases/README.adoc` (date + version)
4. Removes stale `node-v*-headers.tar.gz` files and pushes to the same automation PR
5. When a plugin-catalog checkout is in the same run, pins
   `builder.Containerfile` FROM to the rhdh UBI Node image, copies `.nvm/`, and
   rewrites `konflux.additional-tags` `node-v*` (no `[skip-build]`)
6. When an overlays checkout is in the same run, sets `versions.json` `node` to
   that `.nvmrc` value

See [rhdh `.nvm/releases/README.adoc`](https://github.com/redhat-developer/rhdh/blob/main/.nvm/releases/README.adoc). On **release-1.9**, headers come from `docker/Dockerfile` (`ubi9/nodejs-22`), not Node 24.

### Go toolchain (rhdh-operator, main only)

On **main** only (not `release-*`), after base image bumps, reads `go version` from the `ubi9/go-toolset` or `ubi10/go-toolset` image in `.rhdh/docker/Dockerfile` and updates `go.mod` **only when that version is newer** than the current `go` / `toolchain` lines:

```text
go 1.26.0
toolchain go1.26.4
```

Do not downgrade. If `go.mod` already pins a newer toolchain (for example `go1.26.6` from Renovate while the image ships `go1.26.5`), leave it. Konflux builds with the local toolchain; matching the image is not required.

## Anti-patterns

- Pushing without human review.
- Running on a branch that does not exist in one of the in-scope repos.
- Omitting `registry.redhat.io` login before base image updates.
- Committing `rpms.lock.yaml` without checking the base image minor (e.g. UBI `9.8`) still matches `rpms.in.yaml` repo URLs.
- Treating `rpm-lockfile-prototype` `No sources found for` / "no matching sources" warnings as a failure or remaining risk. The source RPM is often unpublished; the lockfile is still valid.
- Lowering `go.mod` `toolchain` (or `go`) to match an older UBI Go toolset image. Keep the newer pin.
- Copying plugin-catalog `.nvm/` headers while leaving `builder.Containerfile` FROM on an older UBI Node tag, or leaving a stale `node-v*` in `konflux.additional-tags`.
- Handing catalog FROM / overlays `versions.json` to `/rhdh-konflux-tasks`. That skill invokes this one; it does not pin those files.
- Claiming Node headers / `.nvmrc` are done while plugin-catalog still advertises an old `node-v*` in `konflux.additional-tags`. Name the catalog (and overlays) checkout outcome or that it was out of scope.

## Additional resources

- Per-repo notes: [repos.md](../references/repos.md)
