# Workflow: Download translations and deploy to repos

Download completed translations from TMS, merge into translated SOT and
locale `.ts` files, then prepare PRs.

<prerequisites>

Sibling clones of rhdh-plugins, rhdh, community-plugins, and backstage.
translations-cli must be built. TMS credentials available. `gh` authenticated
for PRs. Target repos should have Prettier installed (`node_modules/.bin/prettier`).

```bash
uv run scripts/translation_deploy.py --json preflight
```

Follow `next_steps` before continuing.

</prerequisites>

<process>

## Step 1: Confirm readiness

Ask the user:
- TMS project ID (or confirm `.i18n.config.json`)
- Languages to download (default: de, es, fr, it, ja)
- Sprint identifier (branch / changeset naming)

## Step 2: Download from TMS

```bash
uv run scripts/translation_deploy.py --json download \
  --project-id {{PROJECT_ID}} \
  --output-dir i18n/downloads
```

Confirm files for the expected repos and languages. If the CLI returns only
the first page of jobs, list job IDs with `memsource job list` and download
by job id.

## Step 3: Validate downloads

```bash
uv run scripts/translation_deploy.py --json validate \
  --source-dir i18n/downloads
```

Stop if JSON structure checks fail.

## Step 4: Update translated SOT (rhdh/translations/)

Merges backstage, community-plugins, and rhdh downloads into
`rhdh/translations/{repo}-{locale}.json`. Fixes the TMS `en` language key to
the real locale. Does **not** write rhdh-plugins into this directory.

```bash
uv run scripts/translation_deploy.py --json update-translated-sot \
  --source-dir i18n/downloads \
  --sprint {{SPRINT}}
```

This opens a PR on **rhdh**. There is **no** PR on the upstream backstage
repo — RHDH overrides Backstage strings from these locale JSON files.

## Step 5: Deploy `.ts` merges (rhdh-plugins + community-plugins only)

```bash
uv run scripts/translation_deploy.py --json deploy \
  --source-dir i18n/downloads
```

For each plugin locale file:

- Update values for keys that already exist
- Skip keys that are not in the file
- Never remove keys or change imports/exports
- Format apostrophe strings with double quotes
- Run Prettier on changed files

Do **not** run `translations-cli i18n deploy`.

## Step 6: Changesets and PRs

```bash
uv run scripts/translation_deploy.py --json pr --sprint {{SPRINT}}
```

Writes changesets under each touched workspace `.changeset/` using the real
`package.json` `name` (never `UNKNOWN`).

Then use `/mutation-gate` per repo with changes:

1. Branch: `translation/{{SPRINT}}`
2. Stage translation files + changesets (not local `i18n/` downloads)
3. Commit with Signed-off-by
4. Push and `gh pr create`

Repos: **rhdh-plugins** and **community-plugins** only for `.ts` PRs.

</process>

<completion>

Report:
1. Translated SOT PR URL (rhdh)
2. Per-repo `.ts` deploy summary (updated / skipped / unchanged)
3. Changeset paths and package names
4. PR URLs for rhdh-plugins and community-plugins
5. Explicit note: no backstage upstream PR

</completion>
