# GitLab runner rebuild workflow

Runs **after** a `builder.Containerfile` bump (from [update-base-images.md](update-base-images.md))
has merged and Konflux has published the new `plugin-catalog-builder-rhel10` image.
The runner image is built manually with podman — there is no CI for it — and both
`rhdh` and `rhdh-plugin-catalog` pin it in `.gitlab-ci.yml`, so a builder bump that
does not ripple through leaves every GitLab pipeline running a stale runner.
That staleness is silent: the mutable `:X.Y` runner tag plus the runner pods'
`IfNotPresent` pull policy means nodes keep serving the old image for days, which
presents as intermittent CI failures (seen with RHIDP-19218: `Signature for
identity "registry.access.redhat.com/rhdh/rhdh-operator-bundle:1.1-122" is not
accepted`).

Before any run, follow the write gate in [SKILL.md](../SKILL.md). The commands
below describe what an approved run does; printing one authorizes nothing.

## Prerequisites

- `podman` (logged in to `quay.io` with push rights to `rhdh/gitlab-runner`),
  `skopeo`, `jq`, `git`
- The rhdh checkout and the rhdh-plugin-catalog checkout, both on the stream
  branch (`main` or `release-2.Y`)
- The builder MR for this stream has **merged** and the `plugin-catalog-builder`
  push PipelineRun on that branch has **succeeded** (verify in the Konflux UI or
  with `oc -n rhdh-tenant`, app `rhdh-plugin-catalog-2` for `main`,
  `rhdh-plugin-catalog-2-1` for `release-2.1`), so the new `X.Y-N` tag exists:

  ```bash
  skopeo inspect docker://quay.io/rhdh/plugin-catalog-builder-rhel10:X.Y | jq -r '.Digest'
  ```

## Rebuild and re-pin

**Execute** [scripts/rebuildGitlabRunner.sh](../scripts/rebuildGitlabRunner.sh);
do not reimplement the pin/build/push inline. It resolves the newest published
`X.Y-N` builder tag, pins the runner `FROM` to `tag@sha256`, builds three tags
(`X.Y-<yyyymmdd-hhmm>` dated, `X.Y-yarn4-node24`, `X.Y`), and re-pins
`.gitlab-ci.yml` in every checkout passed with `--bump-ci`.

```bash
SKILL=/path/to/installed/rhdh-base-images

# dry-run first: shows the pin, tags, and .gitlab-ci.yml edits without touching anything
"${SKILL}/scripts/rebuildGitlabRunner.sh" \
  --rhdh /path/to/rhdh -b release-2.1 \
  --catalog /path/to/rhdh-plugin-catalog \
  --bump-ci /path/to/rhdh --bump-ci /path/to/rhdh-plugin-catalog \
  --dry-run

# real run: pin + build + push + re-pin both .gitlab-ci.yml files
"${SKILL}/scripts/rebuildGitlabRunner.sh" \
  --rhdh /path/to/rhdh -b release-2.1 \
  --catalog /path/to/rhdh-plugin-catalog \
  --bump-ci /path/to/rhdh --bump-ci /path/to/rhdh-plugin-catalog \
  --push
```

The dated tag (not the mutable `X.Y`) is what `.gitlab-ci.yml` pins, so runner
nodes pull it fresh instead of serving a cached stale image. Reverting the pin to
`X.Y` later is fine once node caches have turned over; keeping the dated pin is
safer. Dated tags carry `quay.expires-after=150d`, so a stream that stops
rebuilding for months needs its pin refreshed or the tag un-expired in Quay.

### RHDH 1.10 (rhdh-1.10-rhel-9)

The 1.10 stream builds its runner from `plugin-catalog-builder-rhel9`, not the
rhel10 repo, and lives on the `rhdh-1.10-rhel-9` branch in both repos. Use
[scripts/rebuildGitlabRunner110.sh](../scripts/rebuildGitlabRunner110.sh) — a
thin wrapper over the main script that pins the rhel9 builder repo, the
`rhdh-1.10-rhel-9` branch, and stream version `1.10`, and rejects `-b`,
`--version`, and `--builder-repo` overrides. 1.9 has no runner rebuild.

```bash
"${SKILL}/scripts/rebuildGitlabRunner110.sh" \
  --rhdh /path/to/rhdh \   # checked out on rhdh-1.10-rhel-9
  --catalog /path/to/rhdh-plugin-catalog \   # same branch
  --bump-ci /path/to/rhdh --bump-ci /path/to/rhdh-plugin-catalog \
  --push
```

Delete the 110 script and this section once RHDH 2.1 is EOL in March 2027 and
the 1.10 stream is closed.

## Land the changes

Each repo with a changed file gets its own MR via `/rhdh-pr-mr` (pass the Jira
key when one is tracked; the runner Containerfile pin and the `.gitlab-ci.yml`
pin can share one MR in rhdh):

- `rhdh`: `build/containerfiles/gitlab-runner.Containerfile` + `.gitlab-ci.yml`
- `rhdh-plugin-catalog`: `.gitlab-ci.yml`

After CI passes, merge both MRs in the same session so the two repos never
disagree on the runner tag. The merge-push itself triggers a pipeline that runs
on the new image.

## Verify

Confirm the next `sync-midstream` run on the stream branch picks up the new
image and passes — for a catalog-render-affecting change, look for
`opm alpha render-template` completing in the job trace. A job that fails with
a signature or tool-not-found error the new image was supposed to fix means a
runner node served a stale cached `:X.Y` again; re-run the job or keep the
dated pin.

## Completion

The run is complete when the dated runner tag exists on
`quay.io/rhdh/gitlab-runner`, both `.gitlab-ci.yml` files pin it, both MRs are
merged, and a post-merge pipeline on the stream branch ran on the new image.
Report the builder `X.Y-N@sha256` used, the dated runner tag, both MR URLs, and
the verifying pipeline or job URL.
