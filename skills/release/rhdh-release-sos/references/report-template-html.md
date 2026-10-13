# SoS HTML report template

The CLI renders a self-contained HTML page from the same report data as
`report_markdown`. Embedded CSS only — no external assets or JavaScript.

## Structure

1. Header — title and metadata (`As of` = report calendar date at `00:00:00 UTC`,
   `Release phase`, `Next milestone`). Generation time is `generated_at` in JSON only.
2. Milestones — table; highlight the active release phase row
3. Checks — highlighted check rows with summary and Jira link; when an action item
   exists, a small info icon after the check name shows the text on hover or focus
   (CSS tooltip, no JavaScript)
4. Team breakdown — collapsed in `<details>` (HTML only)
5. Footer — report label only (`RHDH release SoS check-in`)

Check rows use bold text and a light background. Issue-list checks show the due date,
count, and Jira link on the check row only — no ticket tables. Team breakdown stays in a
native `<details>` block (collapsed by default, no JavaScript).

Summary badges use the same values as markdown: `None open`, `1 open`, `N open`,
`Unverified`, with color coding (green / amber / gray).

## CLI output

`run` always writes the HTML file and returns:

- `report_markdown` — show unchanged in chat
- `report_html` — full page source (JSON only; do not paste into chat)
- `report_html_path` — absolute path to the written file for download or publishing

Default file name when `--html-output` is omitted:
`reports/rhdh-{version}-sos-{as-of}-{HHMMSS}.html` under this skill directory.

When `--html-output` names a path such as `reports/rhdh-{version}-sos.html`, the CLI
appends `{as-of}-{HHMMSS}` before `.html` so each run gets a unique timestamped file.

The CLI prints `SOS_HTML_REPORT=<path>` on stderr even with `--json`.

Present `report_markdown` in the conversation and give the user the absolute
`report_html_path` so they can open, attach, or publish the HTML file. Do not
complete the skill run unless that file exists on disk.
