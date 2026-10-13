# Catalog-index OCI smoke

Run **before** Helm and Operator. No cluster, no Guest, no packages API.
Do not reimplement unpack or inspect in chat.

`${CATALOG_REPO}` is an rhdh-plugin-catalog checkout that contains
`build/scripts/checkIndexRefsPullable.sh`. `${INDEX_IMAGE}` is the published
index (default `registry.access.redhat.com/rhdh/plugin-catalog-index:${RC_VER}`).
Do not invent the tag.

```bash
"${CATALOG_REPO}/build/scripts/checkIndexRefsPullable.sh" "${INDEX_IMAGE}"
```

`--index-json` / `--list-only` are for local tests, not this smoke. Pass
`--debug` only when the user wants the full passing table and timeout-retry
messages on stderr.

After the script:

1. Print a live line with real counts and the image tag:
   - `Catalog: inspected N unique refs from plugin-catalog-index:1.10.4`
   - `Catalog: inspected N unique refs from plugin-catalog-index:1.10.4 FAILED M not pullable`
2. Keep the script's **failure** table when present. Do not expect a passing
   table unless the script was run with `--debug`.
3. Exit this agent. Helm and Operator start only after this agent finishes.

Field names are `registryReference` as stored in `index.json` (not `oci://…!package`).
Inspect refs as written (`registry.access.redhat.com`, `ghcr.io`, quay). Do not
rewrite to `registry.redhat.io`. Do not require `tree`. Do not `cd` as a lasting
side effect.
