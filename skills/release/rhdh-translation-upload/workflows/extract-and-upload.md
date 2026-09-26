# Workflow: Extract translations and upload to TMS

Collect English translation strings from all four RHDH repos, compute the delta
against the previous-release SOT, upload new/changed keys to TMS, and update
the EN baseline for the next release.

<prerequisites>

All four repos (rhdh-plugins, rhdh, community-plugins, backstage) must be
cloned as siblings. The translations-cli must be built in
rhdh-plugins/workspaces/translations. For upload, `source ~/.memsourcerc`
must have been run to set `MEMSOURCE_TOKEN`.

Run the preflight check first:

```bash
uv run scripts/translation_upload.py --search-root {{SEARCH_ROOT}} preflight
```

Follow `next_steps` to resolve any failures before continuing.

</prerequisites>

<process>

## Step 1: Confirm the sprint

Ask the user for the sprint identifier (e.g., `s4000`). This is used in
filenames: `{repo}-s{sprint}.json`.

## Step 2: Run extraction

```bash
uv run scripts/translation_upload.py --search-root {{SEARCH_ROOT}} extract --sprint {{SPRINT}}
```

This runs `translations-cli i18n generate` in each repo. Backstage is
automatically checked out to the version in `rhdh/backstage.json` (the .0
minor tag, e.g. `v1.54.0`) and restored after extraction.

Check the output:

- Every repo must report `ok: true` and a non-zero key count.
- Zero keys is a hard stop — the source tree may have changed structure.
- The generated reference files land in each repo's `i18n/` directory.

## Step 3: Compute delta

```bash
uv run scripts/translation_upload.py --search-root {{SEARCH_ROOT}} delta --sprint {{SPRINT}}
```

This compares the extracted keys against the translated SOT in
`rhdh/translations/` and the English SOT in
`rhdh-plugins/workspaces/translations/sot/`, and writes files into each
repo's `i18n/` directory:

- `{repo}-s{sprint}-delta.json` — new + changed keys, for TMS upload
- `{repo}-s{sprint}-full.json` — all keys, for archival and EN SOT update
- `backstage-s{sprint}-rhdh-overrides.json` — audit trail of rhdh overrides

The delta includes:
- **New keys** — did not exist in the previous release
- **Changed English values** — key exists but English text changed (compared
  against `{repo}-en.json` in `rhdh-plugins/workspaces/translations/sot/`)
- RHDH-priority overrides for backstage (e.g. "Create" → "Self-service")
- Filtering: `rhdh` keeps only its own plugin; `community-plugins` keeps
  only Red Hat-owned plugins

Present the delta summary to the user as a table:

| Repo | New | Changed | Removed | Unchanged | Delta |
|------|-----|---------|---------|-----------|-------|

## Step 4: Review and confirm

Before uploading, present the delta files to the user and ask for explicit
confirmation. Show:

- Total keys for translation across all repos
- Any repos with zero delta keys (nothing to upload)
- Any repos with removed keys (informational)
- The rhdh override report for backstage

## Step 5: Upload to TMS

Ensure TMS credentials are active: `source ~/.memsourcerc`

Dry-run first to verify:

```bash
uv run scripts/translation_upload.py --search-root {{SEARCH_ROOT}} upload --sprint {{SPRINT}} --dry-run
```

Then upload for real:

```bash
uv run scripts/translation_upload.py --search-root {{SEARCH_ROOT}} upload --sprint {{SPRINT}}
```

This uploads each delta file to the TMS project using `translations-cli i18n
upload`. Repos with zero delta keys are skipped. Default project:
`gO1x9evesBS0qAX7AUPaY0`, default target languages: de, es, fr, it, ja.

## Step 6: Update EN SOT

After upload succeeds, save the English baseline for the next release:

```bash
uv run scripts/translation_upload.py --search-root {{SEARCH_ROOT}} update-sot --sprint {{SPRINT}}
```

This copies each `{repo}-s{sprint}-full.json` to
`rhdh-plugins/workspaces/translations/sot/{repo}-en.json`, creates a branch,
commits with sign-off, and opens a PR to the `rhdh-plugins` repo.

</process>

<completion>

Report:
1. Per-repo delta summary (new/changed/removed/unchanged key counts)
2. Upload status per repo (filename, key count, project ID)
3. EN SOT PR link (if created)
4. Next step: wait for translators, then run `/rhdh-translation-deploy`

</completion>
