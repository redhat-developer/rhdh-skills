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
- Branches: `main`, `release-1.10`, `release-2.*`
- Base images: root `Containerfile`, `.rhdh/docker/Containerfile`
- RPM lock: root `Containerfile` + `rpms.in.yaml` → `rpms.lock.yaml`. RHEL 9 streams that install `openshift-clients` pin `rhocp-N-for-rhel-9-$basearch-rpms` to `https://mirror.openshift.com/pub/openshift-v4/$basearch/dependencies/rpms/N-el9-beta/`; bump N to the latest released 4.y stream that is still on the mirror before regenerating the lockfile. Do not follow unreleased directories (`4.23-el9-beta`, `5.1-el9-beta`). UBI 10 / RHDH 2.y images do not use that repo. See https://access.redhat.com/product-life-cycles/api/v1/products?name=Red%20Hat%20OpenShift%20Container%20Platform
- Go toolchain: on `main`, raise `go.mod` `go` and `toolchain` to the `ubi10/go-toolset` (or `ubi9/go-toolset`) image in the root `Containerfile` when that image is newer. On `release-2.*`, raise the `toolchain` line only — **never the `go` directive**, which is frozen at branch cut and selects the branch's GODEBUG defaults (only a security fix that cannot land without it may raise it, in Renovate's PR for that fix). Insert `toolchain` when the line is missing. Do not downgrade a newer pin. Run `go mod tidy` after any edit and commit `go.mod` with `go.sum`. `release-1.*` has no `go.mod`.
- Markers: `cmd/gather/` directory on a `release-2.*` or `main` branch; `collection-scripts/` directory on a `release-1.10` branch

## redhat-developer/rhdh-operator

- Clone: `https://github.com/redhat-developer/rhdh-operator.git`
- Branches: `main`, `release-1.9`, `release-1.10`, …
- Base images: `.rhdh/docker/Dockerfile`, root `Dockerfile`
- Go toolchain: on every branch, raise `go.mod` `toolchain` to the `ubi10/go-toolset` (or `ubi9/go-toolset`) image in that `Dockerfile` when newer, even across a Go minor — that is how the branch keeps standard-library security fixes. The `go` directive moves on `main` only. Run `go mod tidy` after any edit and commit `go.mod` with `go.sum`.
- RPM lock: root `Dockerfile` or `.rhdh/docker/Dockerfile` + `rpms.in.yaml` → `rpms.lock.yaml`. The `rpm-builder` stage uses `--installroot`; regenerate with `rpm-lockfile-prototype --bare` (not `-f`).
- Workflow reference: `.github/workflows/update-rpm-lockfile.yaml`

## GitLab rhidp/rhdh-plugin-catalog

- Clone: `https://gitlab.cee.redhat.com/rhidp/rhdh-plugin-catalog.git`
- GitHub `-b main` → catalog `main`; `-b release-1.Y` → `rhdh-1.Y-rhel-9`; `-b release-2.Y` → `release-2.Y`
- Pin `build/containerfiles/builder.Containerfile` FROM to the same UBI Node `tag@sha256` as GitHub rhdh. Rewrite `/rhocp/4.N/` in that file to the latest released OpenShift 4.y. Bump N to the latest released 4.y stream that is still on the mirror before regenerating the lockfile. Do not follow unreleased directories (`4.23-el9-beta`, `5.1-el9-beta`). UBI 10 / RHDH 2.y images do not use that repo. See https://access.redhat.com/product-life-cycles/api/v1/products?name=Red%20Hat%20OpenShift%20Container%20Platform
- Headers version is the image `node --version`, or the newer `nodejs` NEVRA from `podman run --user 0` + `dnf module enable nodejs:<major>` + `dnf repoquery -q --latest-limit 1 nodejs`, when the Containerfile `dnf`-installs `nodejs` before the headers `RUN`. Copy rhdh `.nvmrc`, `node-v*-headers.tar.gz`, and `.nvm/releases/README.adoc` only when rhdh is at least that version. Rewrite only the `node-v*` token in `LABEL konflux.additional-tags=...`. When the Containerfile changes, increment `release` and the `X.Y-N` additional tag once, and set `BASE_IMAGES` on `.tekton/plugin-catalog-builder*.yaml` to that FROM image.
- No `rpms.lock.yaml`. Do not `[skip-build]` when FROM or headers change.
- helm: `ENV helm_version=` in `build/containerfiles/builder.Containerfile` installs from `get.helm.sh`; bump in place, never via an RPM repo (RHDHBUGS-4139). Keep it on the same version as rhdh `build/helm/prepare.sh`.
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

`build/helm/prepare.sh` (what the publish-helm Konflux task runs) pins `helm_version=` from `get.helm.sh` on every active branch; bump it together with the plugin-catalog builder pin so chart releases and builder images stay on the same helm.
