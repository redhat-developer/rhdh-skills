---
name: rhdh-base-images
description: >-
  Analyzes and updates the `FROM` base images, Node headers, Go toolchain, and
  `rpms.lock.yaml` files in rhdh, rhdh-operator, and rhdh-must-gather; pin
  plugin-catalog `builder.Containerfile` / `.nvm/` / `konflux.additional-tags`;
  and bump overlays `versions.json` `node` on `main` or a `release-1.10` branch.
  Use for weekly base-image maintenance, a UBI or RHEL bump, an RPM lockfile
  refresh, "which base images are out of date", node-v*-headers.tar.gz, catalog
  builder FROM, builder PipelineRun BASE_IMAGES, catalog release suffix,
  overlays Node version, UBI minor skew inside a Containerfile,
  or an OpenShift clients `N-el9-beta` / `4.21-el9-beta` RPM 404.
compatibility: "bash, jq, skopeo, curl, git, python3; podman or docker for toolchain detection; gh or glab for PR/MR creation."
---

# RHDH base images

Use the bundled scripts instead of reconstructing their repository-specific logic.

Repository checkouts are explicit inputs the user names. This skill never
discovers another skill's paths.

## Route

| Intent | Load or run |
|---|---|
| Read-only current/latest image scan | `workflows/update-base-images.md`, then `scripts/base-images-and-rpms.sh --analyze ...` |
| Explain repository rules | `references/repos.md` |
| Preview an update | `workflows/update-base-images.md`, then `scripts/base-images-and-rpms.sh --dry-run ...` |
| Update images, lockfiles, Node headers, catalog builder, overlays node, or Go toolchain | `workflows/update-base-images.md` |

A scan reports, per repository: every `FROM` image with its current and latest
tag, UBI minor skew within a file, Node or Go toolchain drift, the registries and
branches it read, and anything it could not read.

## Writing rules

Any checkout, branch, file edit, dependency install, commit, push, or PR is a
write. Run read-only discovery or `--dry-run` first, then follow
`/mutation-gate`: state each operation with its target repository and branch
(`rhdh:release-1.10`), the exact command, the change it will land, and what
happens to the remaining operations if it fails; get approval for that stated
set; execute; then report every operation as completed, failed, or skipped, with
the resources it changed and the risks that remain.

Installing `rpm-lockfile-prototype`, logging into registries, using `--push`, and
opening PRs are each their own operation. Default to local, no-push behavior; do
not push directly to protected branches. Verify the branch exists and the working
tree is clean before writing.

When the user asks to push and open a PR/MR after approval, invoke `/rhdh-pr-mr`
by name (or its `create-pr-mr.sh`) instead of hand-rolling `gh pr create` /
`glab mr create`. Pass `--issue` and `--assisted-by`; stop before pushing when
no Jira key is known. Midstream `updateBaseImages.sh` still uses distgit
`createPR.sh` until that path is migrated.

## Repository invariants

- Accepted branch selectors are `main` or `release-*`; map them to the documented
  GitLab scripts branch in `references/repos.md`.
- Keep base-image UBI minors aligned with RPM repository URLs.
- Before regenerating `rpms.lock.yaml`, bump OpenShift clients `N-el9-beta`
  `baseurl` values and matching `rhocp-N-for-rhel-9-$basearch-rpms` repoids in
  `rpms.in.yaml` to the latest **released** 4.y stream that still exists on
  mirror.openshift.com (for example `4.21-el9-beta` → `4.22-el9-beta`). Released
  4.y names come from the product life cycle API linked from
  https://access.redhat.com/support/policy/updates/openshift#dates. Do not move
  to an unreleased directory such as `4.23-el9-beta` or `5.1-el9-beta`. If the
  life cycle fetch fails, or no released 4.y directory is on the mirror, leave
  `rpms.in.yaml` unchanged. Skip when the file has no such repo.
- When a plugin-catalog checkout is in the run, rewrite
  `build/containerfiles/builder.Containerfile` `/rhocp/4.N/` path segments to
  that same latest released 4.y (for example `/rhocp/4.21/` → `/rhocp/4.22/`).
  Leave `ocp-tools` URLs unchanged. Do not rewrite when the life cycle fetch
  fails.
- When that Containerfile changes in the same run, increment its `release="N"`
  label and the matching `X.Y-N` token in `konflux.additional-tags` once
  (`release="3"` and `2.2-3` become `release="4"` and `2.2-4`). Leave
  `version=`, `rhdh.version=`, and `node-v*` to the node-header rewrite.
  Set `BASE_IMAGES` on every `.tekton/plugin-catalog-builder*.yaml`
  `build-source-image` task to the Containerfile `FROM` image, inserting the
  param when it is missing. Do not bump `release` when the Containerfile is
  unchanged.
- When the RPM Containerfile uses `dnf`/`microdnf install --installroot`
  (operator empty rootfs), regenerate the lockfile with
  `rpm-lockfile-prototype --bare` so the full closure (glibc, coreutils, bash)
  is locked. Do not pass `-f`; that loads the UBI rpmdb and omits those
  packages. Layered installs onto the base image still use `-f`. If the solve
  fails (`nothing provides`, `conflicting requests`), restore
  `rpms.lock.yaml` / `rpms.in.yaml` and do not push.
- On RHDH, update Node headers when the builder image changes Node. Then, when
  those checkouts are in scope, pin plugin-catalog
  `build/containerfiles/builder.Containerfile` FROM to the same UBI Node
  `tag@sha256`. Catalog headers follow the Node version that Containerfile
  will run: image `node --version`, or the newer `nodejs` RPM from
  `dnf repoquery` when the file `dnf`-installs `nodejs` before the headers
  `RUN`. Do not copy an older rhdh `.nvm/` over that version. Rewrite
  `konflux.additional-tags` `node-v*` to match the catalog `.nvmrc`, and set
  overlays `versions.json` `node` to the rhdh `.nvmrc` value.
  Catalog maps `release-1.Y` → GitLab `rhdh-1.Y-rhel-9` and
  `release-2.Y` → GitLab `release-2.Y` (using UBI10 / RHEL10). Catalog has no
  `rpms.lock.yaml`. Do not `[skip-build]` the catalog builder commit.
- On rhdh-operator `main`, raise `go.mod` to the Go toolset image when the
  image is newer. On rhdh-must-gather `main` and `release-2.*`, do the same
  from the root `Containerfile` `ubi9/go-toolset` or `ubi10/go-toolset` image,
  inserting a `toolchain` line when `go.mod` has none. Skip must-gather
  `release-1.*` (no Go module). Never lower `go` or `toolchain` to match an
  older image; a newer pin (for example from Renovate) is valid.
- Exclude RHDH `e2e-tests/` and `.ci/` from image scans.
- Ignore `rpm-lockfile-prototype` lines matching `No sources found for` or
  "no matching sources". Those source RPMs are often unpublished; the binary
  lockfile is still valid. Do not report them as unread, failed, or remaining
  risks.

Another skill invokes `/rhdh-base-images` by name and uses what it reports; it
never reaches for these script paths. `/rhdh-konflux-tasks` does this during a
stream Konflux bump so Node headers match the builder image; it passes named
checkouts and a `main` or `release-*` selector.

## Completion

An analysis is complete when every repository in scope is named with its current
and latest tag, UBI skew and toolchain drift are stated or stated as none, and
every registry, lockfile, or branch the scan could not read is named as unread
instead of reported as current. Filtered `No sources found for` /
"no matching sources" lines are not unread and are omitted from the report.

An update is complete when the target branch was verified to exist against a
clean working tree before any edit, every approved operation has been reported by
target and outcome, and the push and PR state is stated explicitly — including
"not pushed" when the default local behavior was kept. When Node headers /
`.nvmrc` changed, name the plugin-catalog FROM old→new, confirm
`grep konflux.additional-tags build/containerfiles/builder.Containerfile`
contains `node-v` matching `.nvmrc`, and name the overlays `versions.json`
`node` value (or that those checkouts were not in scope). When the catalog
builder Containerfile changed, name the `release` old→new and confirm builder
PipelineRun `BASE_IMAGES` matches that file's `FROM` (or that the Containerfile
did not change).
