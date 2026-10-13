# Workflow: SoS release check-in

Build the cumulative Scrum of Scrums release report from `references/sos-checks.md`.

<prerequisites>

Run `uv run scripts/sos_report.py --json check` and require the Rich Filter contract
check to pass. `references/config.md` documents the shared export with
`/rhdh-release-status`. When Jira or the export is unavailable, name what stayed
unverified rather than guessing counts.

</prerequisites>

<process>

## Step 1: Resolve the release version

Ask when the request omits a version. Do not default to the newest release you have
seen elsewhere in the conversation.

## Step 2: Confirm milestone dates

Invoke `/rhdh-release-schedule` for the same version when the CLI cannot find an
active Jira release issue, or when the user asks to reconcile dates. The SoS CLI
reads active-release milestone dates from Jira directly.

## Step 3: Run the check-in CLI

Run from this skill directory. Always pass `--html-output` so the HTML file lands in
a known, downloadable location:

```bash
uv run scripts/sos_report.py --json run {{VERSION}} --html-output reports/rhdh-{{VERSION}}-sos.html
```

The CLI appends the report as-of date and generation time to the file name, for example
`reports/rhdh-2.1.0-sos-2026-09-08-132205.html`. Omit `--html-output` to use the same
pattern under `reports/` in this skill directory.

Use `--date YYYY-MM-DD` only when the user names an as-of date other than today.
Use `plan` instead of `run` only when the user wants due checks listed without Jira
counts — `plan` does not produce HTML.

After the command, require `data.report_html_path` in the JSON and confirm the file
exists on disk before presenting the report. If it is missing, stop and diagnose; do
not show a report without a written HTML file.

The cumulative rule is implemented in the CLI: within the active milestone section,
every check whose resolved date is on or before today runs. See
`references/timeline.md`.

## Step 4: Present the report

Show `report_markdown` exactly as the CLI returns it. The fixed layout is defined
in `references/report-template.md`. Do not add upcoming checks, follow-up lists,
runbook execution counts, or extra narrative around the template.

Tell the user where the HTML file was written (`report_html_path`). Give the absolute
path so they can open, attach, or publish it. The CLI also prints
`SOS_HTML_REPORT=<path>` on stderr. See `references/report-template-html.md`.

Do not treat the run as complete unless `report_html_path` exists on disk.

</process>

<gotchas>

- Section headers in `sos-checks.md` are not checks. Only rows with a **Check** and
  **Query** column execute.
- Feature Freeze filter scope excludes bugs and Features by design.
- Checks in a later milestone section never run early.
- Never paraphrase check summaries or rebuild the Checks table by hand.

</gotchas>

<success_criteria>

- [ ] `report_markdown` is shown unchanged from the CLI
- [ ] `report_html_path` exists on disk and was shared with the user
- [ ] Every due check row has a summary and Jira link per `references/report-template.md`
- [ ] Every due check includes an action item and team sub-rows with summary and Jira link where Cloud ID exists
- [ ] No upcoming-checks section and no runbook execution metadata were added
- [ ] Nothing was posted

</success_criteria>
