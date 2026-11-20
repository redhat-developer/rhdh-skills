# Bump Dependabot CVE packages in rhdh-plugin-catalog

Dual-repo flow: Dependabot alerts from a GitHub plugins / staging checkout,
lockfile bumps + `dist-dynamic` re-export in GitLab
`rhidp/rhdh-plugin-catalog` on `release-X.Y`.

Human-facing twin (same steps, shell-first): catalog
`docs/SYNC_MIDSTREAM.md` → **CVE / yarn.lock updates without upstream clone**.

Local lockfile / `package.json` / `dist-dynamic` edits and MR open are external
writes. State them through `/mutation-gate` before anything that is not
`--dry-run`. Do not push or open an MR until the user asks; then use
`/rhdh-pr-mr`.

Not for Version Packages → overlays → surgical catalog promote — that is
`/rhdh-plugin-midstream-propagate`.

## When to use

- User asks for a **downstream / catalog Dependabot CVE** bump on
  `workspaces/<name>/` in `rhdh-plugin-catalog`
- Release branch (`release-2.1`, …), especially skip-sync / deny-listed
  workspaces (`backstage`, `roadie-backstage-plugins`, `keycloak`, …)
- Alerts live in another GitHub repo (e.g.
  `redhat-developer/rhdh-upstream-plugin-cve-fixes`) but fixes land in the
  catalog

For upstream-only bumps in `rhdh-plugins` / `community-plugins` / rhdh core,
use [bump-workspace.md](bump-workspace.md) instead.

## Workspace setup

You need **two local checkouts** plus the skill scripts. Layout reference:
[repo-layouts.md](../references/repo-layouts.md) (catalog midstream section).

```text
<alerts-checkout>/                    # GitHub — Dependabot alert host
  workspaces/<name>/yarn.lock         # path prefix for alert discovery
  workspaces/<name>/…                 # may match catalog tree; not the bump target

<catalog-checkout>/                   # GitLab rhidp/rhdh-plugin-catalog — bump target
  build/scripts/reexport-dist-dynamic.sh
  workspaces/<name>/
    package.json
    yarn.lock                         # edit this
    .yarnrc.yml                       # yarnPath → .yarn/releases/yarn-*.cjs
    .yarn/releases/
    plugins/…/dist-dynamic/           # regenerated after bump
  (optional remotes: origin, upstream → GitLab)
```

**Ready checklist** before Step 1:

| Check | Expect |
| --- | --- |
| Catalog branch | On or based from `release-X.Y` tip (`origin/release-X.Y` or `upstream/release-X.Y`) |
| Catalog workspace | `workspaces/$WKSP/yarn.lock` exists |
| Yarn Berry | Workspace `.yarnrc.yml` + `.yarn/releases/yarn-*.cjs` (do **not** commit a repo-root `.yarnrc.yml` or a Corepack `packageManager` pin on `package.json`) |
| Install | `yarn install` succeeds under `workspaces/$WKSP` (`node_modules` present) |
| Alerts checkout | Same `workspaces/$WKSP/` path exists (for `--repo-root` path matching) |
| Alerts GitHub | `ALERTS_GITHUB` is the Dependabot host (`owner/name`) |
| Auth | `GITHUB_TOKEN` or `GH_TOKEN` already in the process environment, **or** an `--alerts-json` snapshot |
| Re-export | `build/scripts/reexport-dist-dynamic.sh` present at catalog root |
| Skill | `SKILL_DIR` points at this skill’s directory |

Optional: resolve catalog path via `/rhdh-context` (`repos.catalog`) when that
skill is installed; otherwise the caller passes absolute paths.

## Inputs

| Variable | Meaning |
|----------|---------|
| `CATALOG` | Local `rhdh-plugin-catalog` checkout (`--repo-root` for bumps) |
| `ALERTS_REPO_ROOT` | Local alerts-host checkout with `workspaces/<name>/` |
| `ALERTS_GITHUB` | `owner/name` for Dependabot REST (e.g. `redhat-developer/rhdh-upstream-plugin-cve-fixes`) |
| `WKSP` | Workspace name (`keycloak`, `backstage`, …) |
| `RELEASE` | Catalog base branch (`release-2.1`) |
| `SKILL_DIR` | This skill directory |

Alert REST needs authenticated GitHub access: ensure `GITHUB_TOKEN` or
`GH_TOKEN` is already in the process environment (never commit credentials;
never pass `--token`). Prefer `--alerts-json` for CI / shared runs so no live
token is required. Do not use `gh` inside skill scripts.

## Steps

### 1. Prepare branch

Confirm the [Workspace setup](#workspace-setup) checklist, then:

```bash
node "$SKILL_DIR/scripts/prepare-workspace-bump.js" \
  --repo-root "$CATALOG" --base "$RELEASE" --upstream upstream \
  "$WKSP"
```

If GitLab SSH fetch fails but local/`origin/$RELEASE` already matches the tip,
`git checkout -B chore/<workspace>-cve-bumps-release-X.Y origin/release-X.Y`
is acceptable. Re-run `yarn install` in `workspaces/$WKSP` if `node_modules`
is missing after checkout.

### 2. Assess (required table)

```bash
node "$SKILL_DIR/scripts/list-dependabot-packages.js" \
  --repo-root "$ALERTS_REPO_ROOT" --repo "$ALERTS_GITHUB" \
  "$WKSP" --json | tee "/tmp/${WKSP}-alerts.json"

node "$SKILL_DIR/scripts/check-dependabot-patch-status.js" \
  --repo-root "$CATALOG" --repo "$ALERTS_GITHUB" \
  "$WKSP"
```

Report the markdown classification / patch-status table. Call out
`PLUGIN_PROD` remaining vs dismissable exact `PLUGIN_DEV` /
`WORKSPACE_DEV` / `RUNNER`. Do not dismiss unless the user asks.

### 3. Bulk bump (catalog defaults)

```bash
node "$SKILL_DIR/scripts/bump-workspace-packages.js" \
  --repo-root "$CATALOG" --repo "$ALERTS_GITHUB" \
  --base "$RELEASE" --no-dedupe \
  "$WKSP" --json | tee "/tmp/${WKSP}-bump.json"
```

| Catalog rule | Why |
|--------------|-----|
| Always `--no-dedupe` on release catalog bumps | Full `yarn dedupe` can collapse intentional dual resolves |
| Optional selective `yarn dedupe <cve pkgs…>` after | Safer hygiene; often no-op on non-overlapping majors |
| Skip `@backstage/*` / `@backstage-community/*` | Skill denylist — never override |
| Allowlisted leftovers (e.g. `qs`) | Auto ancestor-bump inside the bump script |
| Other leftovers | Report partial/unchanged; ancestor walk only if user asks |

### 4. Manual complex leftovers

Do **not** automate dual-major cases via the bump script. For
`fast-xml-parser` (and similar):

1. `yarn why -R fast-xml-parser` in `workspaces/$WKSP`
2. Bump the **actual** parents in range (confirm holders — do not assume AWS)
3. `yarn install` and confirm the vulnerable line is gone

Keycloak example: Azure/GCP (`@azure/storage-blob`, `@google-cloud/storage`)
cleared `fast-xml-parser@4.5.7` → `5.12.1`. AWS `xml-builder` already had no
fxp there. Fold manual fixes into the Fully fixed table when formatting the
MR body.

### 5. Re-export dist-dynamic (required)

```bash
cd "$CATALOG"
./build/scripts/reexport-dist-dynamic.sh -w "$WKSP" --debug
```

Shipped impact = diffs under `plugins/*/dist-dynamic/yarn.lock`, not the full
workspace leftover table. Some plugins may regenerate identical to HEAD.

### 6. Format description; commit only when asked

```bash
node "$SKILL_DIR/scripts/format-bump-pr.js" \
  --with-title --base "$RELEASE" "/tmp/${WKSP}-bump.json"
```

Edit Summary bullets for manual parent bumps + re-export. Preview to the user.
Commit with that body when asked (`git add -f` tracked `dist-dynamic` paths as
needed). Open the GitLab MR with `/rhdh-pr-mr` only when the user asks — do not
create a PR/MR in the same turn as a silent default.

## Completion

Done when: [Workspace setup](#workspace-setup) was satisfied, branch exists on
`$RELEASE` tip, patch-status table was shown, bump JSON + optional manual
leftovers are applied, selective dedupe result is noted, re-export ran,
skill-shaped Fully fixed / Partial / Unchanged body was previewed, and
lockfile / `dist-dynamic` edits remain local until a gated commit / push / MR.
