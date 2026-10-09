# Upstream repo reference

## redhat-developer/rhdh

- Clone: `https://github.com/redhat-developer/rhdh.git`
- Branches: `main`, `release-1.9`, `release-1.10`, …
- Base images: `build/containerfiles/Containerfile`, `.ci/images/Dockerfile`, and other `Dockerfile`/`Containerfile` paths within `-maxdepth 5`
- RPM lock: `build/containerfiles/Containerfile` + `rpms.in.yaml` → `rpms.lock.yaml`
- Node headers: when builder image Node version changes, update `.nvm/releases/node-v*-headers.tar.gz`, `.nvmrc`, and `.nvm/releases/README.adoc` (see `.nvm/releases/README.adoc`)
- Workflow reference: `.github/workflows/update-rpm-lockfile.yaml`

## redhat-developer/rhdh-must-gather

- Clone: `https://github.com/redhat-developer/rhdh-must-gather.git`
- Branches: `main`, `release-1.10`, …
- Base images: root `Containerfile`, `.rhdh/docker/Containerfile`
- RPM lock: root `Containerfile` + `rpms.in.yaml` → `rpms.lock.yaml`. RHEL 9 streams that install `openshift-clients` pin `rhocp-N-for-rhel-9-$basearch-rpms` to `https://mirror.openshift.com/pub/openshift-v4/$basearch/dependencies/rpms/N-el9-beta/`; bump N to the latest published stream before regenerating the lockfile. UBI 10 / RHDH 2.y images do not use that repo.
- Marker for auto-detection: `collection-scripts/` directory

## redhat-developer/rhdh-operator

- Clone: `https://github.com/redhat-developer/rhdh-operator.git`
- Branches: `main`, `release-1.9`, `release-1.10`, …
- Base images: `.rhdh/docker/Dockerfile`, root `Dockerfile`
- RPM lock: `.rhdh/docker/Dockerfile` + `rpms.in.yaml` → `rpms.lock.yaml`
- Workflow reference: `.github/workflows/update-rpm-lockfile.yaml`

## GitLab rhidp/rhdh-plugin-catalog

- Clone: `https://gitlab.cee.redhat.com/rhidp/rhdh-plugin-catalog.git`
- GitHub `-b main` → catalog `main`; `-b release-1.Y` → `rhdh-1.Y-rhel-9`; `-b release-2.Y` → `release-2.Y`
- Pin `build/containerfiles/builder.Containerfile` FROM to the same UBI Node `tag@sha256` as GitHub rhdh. RHDH 1.y uses RHEL9; RHDH 2.y uses RHEL 10. Prefer `major.minor-buildid`; numeric-only tags often 404.
- Headers version is the image `node --version`, or the newer `nodejs` NEVRA from `podman run --user 0` + `dnf module enable nodejs:<major>` + `dnf repoquery -q --latest-limit 1 nodejs`, when the Containerfile `dnf`-installs `nodejs` before the headers `RUN`. Copy rhdh `.nvmrc`, `node-v*-headers.tar.gz`, and `.nvm/releases/README.adoc` only when rhdh is at least that version. Rewrite only the `node-v*` token in `LABEL konflux.additional-tags=...`.
- No `rpms.lock.yaml`. Do not `[skip-build]` when FROM or headers change.
- Markers: `build/containerfiles/builder.Containerfile`, `.nvmrc`, and `.tekton/updatePLRs.sh` (or deprecated `generatePipelineRunsForPlugins.sh` on 1.9/1.10)

## redhat-developer/rhdh-plugin-export-overlays

- Clone: `https://github.com/redhat-developer/rhdh-plugin-export-overlays.git`
- Branches: `main`, `release-1.10`, … (same selector as GitHub `-b`)
- Node pin: `versions.json` `"node"` — set to the rhdh `.nvmrc` value (no `.nvm/` tree, no `builder.Containerfile`)
- Markers: `versions.json` with a `"node"` field plus `workspaces/` or `catalog-entities/`

## Midstream script source

When `--update-base-images-script` is omitted, the bundled script downloads from:

`https://gitlab.cee.redhat.com/rhidp/rhdh/-/raw/<scripts-branch>/build/scripts/updateBaseImages.sh`

`createPR.sh` is fetched into the same directory when missing.
