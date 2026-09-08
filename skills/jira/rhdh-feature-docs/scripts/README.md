# Scripts Directory

Utility scripts for the rhdh-feature-docs skill. All scripts use the Python
standard library only (no third-party packages) and target Python 3.7+.

## jira_acli.py

Wraps the Atlassian CLI (`acli`) to fetch Jira issues, their child issues, and the
pull requests linked across a feature tree. This is the primary data source for
the skill (Steps 1–3).

**Prerequisites:** `acli` installed and authenticated (see
`../references/acli-setup.md`). The remote/web-link PR source additionally reads
`JIRA_API_TOKEN` from the environment; it is never printed or logged.

### Usage

```bash
# Issue details enriched with child issues
python3 scripts/jira_acli.py RHDHPLAN-1187 --children

# Remote/web links ("Git Pull Request" panel) for a single issue
python3 scripts/jira_acli.py RHIDP-14170 --remote-links

# Walk the whole feature tree and collect PRs from both sources
# (remote/web links + issue content), deduplicated
python3 scripts/jira_acli.py RHDHPLAN-1187 --pull-requests
```

### Output

JSON on stdout. `--pull-requests` returns a list of nodes, each with `key`,
`type`, `status`, `summary`, `depth`, and `pull_requests` (each PR has `url` and
`sources`, where a source is `web-link`, `comment`, `description`, or `field`).

## fetch_rhdh_docs.py

Fetches existing RHDH product documentation (AsciiDoc) from the
`red-hat-developers-documentation-rhdh` GitHub repository over HTTPS. Used in
Step 4 to check whether a feature already has documentation.

### Usage

```bash
python3 scripts/fetch_rhdh_docs.py --list
python3 scripts/fetch_rhdh_docs.py --search "plugin"
python3 scripts/fetch_rhdh_docs.py --title "extend_installing-and-viewing-plugins-in-rhdh" --with-modules
```

Use `--branch <name>` to target a release branch other than the default.

## setup_acli.py

Verifies that `acli` is installed and authenticated. Run it before using the
skill; all checks should pass.

```bash
python3 scripts/setup_acli.py
```

## Testing

Run the skill's script tests from the repository root:

```bash
uv run pytest
```
