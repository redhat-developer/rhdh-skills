# Determine Target Backstage Version

## For RHDH plugins

RHDH pins a specific Backstage version per release. Use the compatibility
answer established in `SKILL.md`, or invoke `/rhdh-context` by name for the
checked-in matrix.

> **Dependency:** RHDH version alignment needs `/rhdh-context`. If it is not
> installed, say so, name `/setup-rhdh-skills install` as the human's next step, and ask
> the user for the target RHDH and Backstage versions directly.

Ask the user: **"Which RHDH version are you targeting?"**

| RHDH Version | Backstage Version |
|---|---|
| Use the resolved compatibility answer; do not infer from an unrelated release |

Use the Backstage version from the matrix as the `--release` argument for `versions:bump`.

## For standalone Backstage projects

If the plugin isn't targeting a specific RHDH release, ask the user:

- **"Latest stable"** → Use the most recent Backstage release (check `https://versions.backstage.io` or the Backstage GitHub releases page)
- **Specific version** → Use what they specify (e.g., `1.45.3`)

## Version format

The `--release` flag for `backstage-cli versions:bump` accepts:

- `main` — latest monthly release (default)
- `next` — latest weekly pre-release
- `1.45.3` — exact version pin

Validate every target against the accepted forms before passing it to a command.
For RHDH alignment, require the exact stable `X.Y.Z` version from the matrix and
confirm that release exists in the Backstage release feed or npm metadata. For a
standalone plugin or app, accept an exact `X.Y.Z`, or the literal `main` or `next`
only when the user explicitly requests that channel. Resolve "latest stable" to
an exact release. Do not pass free-form request text to `--release`.

## Checking if an upgrade is needed

Compare the current base version (from `discover-versions.md`) against the target. If they match, no upgrade is needed -- tell the user.

If the target is older than current, warn the user -- downgrading is risky and may not be supported by `versions:bump`.
