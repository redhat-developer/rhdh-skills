"""Unit tests for SoS report markdown rendering."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SOS_SCRIPTS = PROJECT_ROOT / "skills" / "release" / "rhdh-release-sos" / "scripts"

if str(_SOS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SOS_SCRIPTS))

import sos_report_format as format_mod  # noqa: E402

SAMPLE_REPORT = {
    "version": "2.1.0",
    "as_of": "2026-09-02",
    "active_section": {"title": "Feature Freeze", "milestone_key": "feature_freeze"},
    "milestones": [
        {
            "milestone": "Feature Freeze",
            "key": "feature_freeze",
            "date": "2026-09-22",
            "days_until": 20,
        },
        {
            "milestone": "Code Freeze",
            "key": "code_freeze",
            "date": "2026-10-13",
            "days_until": 41,
        },
        {
            "milestone": "Go/No Go",
            "key": "go_no_go",
            "date": "2026-10-26",
            "days_until": 54,
        },
        {
            "milestone": "GA Announce",
            "key": "ga_announce",
            "date": "2026-10-28",
            "days_until": 56,
        },
    ],
    "checks_upcoming": [
        {
            "title": "FF scope outstanding",
            "when": "FF - 7d",
            "resolved_date": "2026-09-15",
        }
    ],
    "results": [
        {
            "title": "FF Stories, Tasks not in a sprint",
            "action_item": "Plan every FF Story and Task into the current or next sprint.",
            "count": 157,
            "status": "ok",
            "jira_url": "https://redhat.atlassian.net/issues/?jql=sprint+is+EMPTY",
            "teams": [
                {
                    "team_name": "RHDH COPE",
                    "count": 12,
                    "status": "ok",
                    "jira_url": "https://redhat.atlassian.net/issues/?jql=sprint+team+cope",
                },
                {
                    "team_name": "RHDH Install Method",
                    "count": 0,
                    "status": "ok",
                    "jira_url": "https://redhat.atlassian.net/issues/?jql=sprint+team+install",
                },
            ],
        },
        {
            "title": "FF Epics, Stories, Tasks in New, To Do, or Backlog",
            "action_item": "Move FF scope out of New, To Do, or Backlog into active work.",
            "count": 0,
            "status": "ok",
            "jira_url": "https://redhat.atlassian.net/issues/?jql=status+in+New",
            "teams": [
                {
                    "team_name": "RHDH COPE",
                    "count": 0,
                    "status": "ok",
                    "jira_url": "https://redhat.atlassian.net/issues/?jql=status+team+cope",
                },
            ],
        },
    ],
}


class TestReportFormat:
    def test_check_summary_values(self):
        assert format_mod.check_summary(SAMPLE_REPORT["results"][0]) == "157 open"
        assert format_mod.check_summary(SAMPLE_REPORT["results"][1]) == "None open"

    def test_fixed_template_shape(self):
        markdown = format_mod.render_report_markdown(SAMPLE_REPORT)
        assert markdown.startswith("# RHDH 2.1.0 — SoS Release Check-in\n")
        assert "| As of | 2026-09-02 00:00:00 UTC |" in markdown
        assert "| Release phase | Feature Freeze |" in markdown
        assert "## Milestones" in markdown
        assert "## Checks" in markdown
        assert "| ↳ COPE | 12 open | [Open in Jira]" in markdown
        assert "| ↳ COPE | None open | [Open in Jira]" in markdown
        assert "| ↳ ℹ Plan every FF Story and Task into the current or next sprint." in markdown
        assert "| Action item |" not in markdown
        assert "Upcoming checks" not in markdown
        assert "Follow-up" not in markdown
        assert "executed" not in markdown.lower()

    def test_team_display_name_strips_rhdh_prefix(self):
        assert format_mod.team_display_name("RHDH COPE") == "COPE"
        assert format_mod.team_display_name("Install Method") == "Install Method"

    def test_enrich_report_adds_summary_and_markdown(self):
        enriched = format_mod.enrich_report(SAMPLE_REPORT)
        assert enriched["results"][0]["summary"] == "157 open"
        assert "executive_summary" not in enriched
        assert "[Open in Jira]" in enriched["report_markdown"]
        assert enriched["report_html"].startswith("<!DOCTYPE html>")
        assert "RHDH 2.1.0 — SoS Release Check-in" in enriched["report_html"]
        assert "<dt>Generated at</dt>" not in enriched["report_html"]
        assert 'class="summary summary-open"' in enriched["report_html"]
        assert 'class="check-row"' in enriched["report_html"]
        assert 'class="check-action-hint"' in enriched["report_html"]
        assert 'class="check-action-popup"' in enriched["report_html"]
        assert ".check-block:has(.check-action-hint:hover)" in enriched["report_html"]
        assert "overflow: visible" in enriched["report_html"]
        assert 'class="check-action-row"' not in enriched["report_html"]
        assert (
            "Plan every FF Story and Task into the current or next sprint."
            in enriched["report_html"]
        )
        assert '<details class="team-breakdown">' in enriched["report_html"]
        assert '<details class="team-breakdown" open>' not in enriched["report_html"]
        assert 'class="team-table"' in enriched["report_html"]
        assert "<style>" in enriched["report_html"]

    def test_html_as_of_uses_calendar_date_not_generated_at(self):
        report = {
            **SAMPLE_REPORT,
            "as_of": "2026-09-08",
            "generated_at": "2026-09-18T15:30:00+00:00",
        }
        html = format_mod.render_report_html(report)
        assert "<dt>As of</dt><dd>2026-09-08 00:00:00 UTC</dd>" in html
        assert "2026-09-18" not in html
        assert "<dt>Generated at</dt>" not in html
        assert "<footer>RHDH release SoS check-in</footer>" in html

    def test_report_as_of_display(self):
        assert (
            format_mod.report_as_of_display({"as_of": "2026-09-02", "generated_at": None})
            == "2026-09-02 00:00:00 UTC"
        )
        assert (
            format_mod.report_as_of_display(
                {"as_of": "2026-09-08", "generated_at": "2026-09-18T15:30:00+00:00"}
            )
            == "2026-09-08 00:00:00 UTC"
        )

    def test_format_generated_at(self):
        assert (
            format_mod.format_generated_at("2026-09-09T08:23:15+00:00") == "2026-09-09 08:23:15 UTC"
        )

    def test_blank_action_item_omits_html_hint_and_markdown_row(self):
        report = {
            **SAMPLE_REPORT,
            "results": [
                {
                    "title": "Feature Freeze day snapshot",
                    "action_item": "",
                    "count": 42,
                    "status": "ok",
                    "jira_url": "https://redhat.atlassian.net/issues/?jql=ff",
                    "teams": [],
                }
            ],
        }
        markdown = format_mod.render_report_markdown(report)
        html = format_mod.render_report_html(report)
        assert "↳ ℹ" not in markdown
        assert 'class="check-action-hint"' not in html

    def test_summary_css_class(self):
        assert format_mod.summary_css_class({"status": "ok", "count": 0}) == "summary-none"
        assert format_mod.summary_css_class({"status": "ok", "count": 3}) == "summary-open"
        assert format_mod.summary_css_class({"status": "unverified"}) == "summary-unverified"
        assert (
            format_mod.summary_css_class(
                {"kind": "ratio", "status": "ok", "numerator": 12, "denominator": 18, "percent": 67}
            )
            == "summary-open"
        )
        assert (
            format_mod.summary_css_class(
                {"kind": "ratio", "status": "ok", "numerator": 4, "denominator": 4, "percent": 100}
            )
            == "summary-none"
        )
        assert (
            format_mod.summary_css_class(
                {
                    "kind": "expect_assignee",
                    "status": "ok",
                    "expect_state": "assigned",
                }
            )
            == "summary-none"
        )
        assert (
            format_mod.summary_css_class(
                {
                    "kind": "expect_assignee",
                    "status": "ok",
                    "expect_state": "unassigned",
                }
            )
            == "summary-open"
        )

    def test_expect_assignee_summary_and_links(self):
        assigned = {
            "kind": "expect_assignee",
            "status": "ok",
            "summary": "Assigned (RHIDP-9)",
            "expect_state": "assigned",
            "issue_key": "RHIDP-9",
            "issue_url": "https://redhat.atlassian.net/browse/RHIDP-9",
            "jira_url": "https://redhat.atlassian.net/browse/RHIDP-9",
            "teams": [],
        }
        assert format_mod.check_summary(assigned) == "Assigned (RHIDP-9)"
        report = {**SAMPLE_REPORT, "results": [{**assigned, "title": "Test Day ticket has owner"}]}
        markdown = format_mod.render_report_markdown(report)
        assert "[RHIDP-9](https://redhat.atlassian.net/browse/RHIDP-9)" in markdown
        html = format_mod.render_report_html(report)
        assert 'class="summary summary-none"' in html
        assert ">RHIDP-9</a>" in html

    def test_testplan_signoff_html_collapsible_list(self):
        report = {
            **SAMPLE_REPORT,
            "results": [
                {
                    "title": "Test Plan sign-off complete",
                    "kind": "testplan_signoff",
                    "status": "ok",
                    "testplan_state": "action_needed",
                    "summary": "1 sign-off task open",
                    "due_by_milestone": "Feature Freeze",
                    "due_by_date": "2026-09-22",
                    "epic_key": "RHIDP-100",
                    "issue_key": "RHIDP-100",
                    "issue_url": "https://redhat.atlassian.net/browse/RHIDP-100",
                    "jira_url": "https://redhat.atlassian.net/browse/RHIDP-100",
                    "issues": [
                        {
                            "key": "RHIDP-101",
                            "summary": "QE sign-off",
                            "status": "In Progress",
                            "url": "https://redhat.atlassian.net/browse/RHIDP-101",
                        }
                    ],
                    "teams": [],
                }
            ],
        }
        html = format_mod.render_report_html(report)
        assert '<details class="issue-breakdown">' in html
        assert "Sign-off ticket open (1)" in html
        assert "RHIDP-101" in html
        assert "Complete by Feature Freeze" in html

    def test_testplan_children_links_unassigned_jira_filter(self):
        report = {
            **SAMPLE_REPORT,
            "results": [
                {
                    "title": "Test Plan tasks assigned",
                    "kind": "testplan_children",
                    "status": "ok",
                    "testplan_state": "action_needed",
                    "summary": "2 unassigned tasks",
                    "due_by_milestone": "Feature Freeze",
                    "due_by_date": "2026-09-22",
                    "jira_url": "https://redhat.atlassian.net/issues/?jql=parent+%3D+RHIDP-100+AND+assignee+is+EMPTY",
                    "teams": [],
                }
            ],
        }
        markdown = format_mod.render_report_markdown(report)
        assert "2 unassigned tasks" in markdown
        assert (
            "[Open in Jira](https://redhat.atlassian.net/issues/?jql=parent+%3D+RHIDP-100+AND+assignee+is+EMPTY)"
            in markdown
        )

    def test_ratio_check_summary(self):
        result = {
            "kind": "ratio",
            "status": "ok",
            "numerator": 12,
            "denominator": 18,
            "percent": 67,
        }
        assert format_mod.check_summary(result) == "67% (12/18)"
        assert (
            format_mod.check_summary({"kind": "ratio", "status": "ok", "denominator": 0}) == "None"
        )

    def test_due_static_markdown_in_checks_table(self):
        report = {
            **SAMPLE_REPORT,
            "results": [
                {
                    "title": "FF work remaining for Feature Freeze",
                    "action_item": "Close or defer all FF-scope work before Feature Freeze.",
                    "kind": "due",
                    "due_by_date": "2026-09-22",
                    "count": 2,
                    "status": "ok",
                    "jira_url": "https://redhat.atlassian.net/issues/?jql=ff",
                    "teams": [
                        {
                            "team_name": "RHDH COPE",
                            "count": 1,
                            "status": "ok",
                            "jira_url": "https://redhat.atlassian.net/issues/?jql=team",
                        }
                    ],
                }
            ],
        }
        markdown = format_mod.render_report_markdown(report)
        assert "## Remaining for Feature Freeze" not in markdown
        assert "FF work remaining for Feature Freeze | 2 open |" in markdown
        assert "Close or defer all FF-scope work before Feature Freeze." in markdown
        assert "| ↳ COPE | 1 open |" in markdown

    def test_due_static_html_check_row_only(self):
        report = {
            **SAMPLE_REPORT,
            "results": [
                {
                    "title": "FF work remaining for Feature Freeze",
                    "kind": "due",
                    "due_by_date": "2026-09-22",
                    "count": 1,
                    "status": "ok",
                    "jira_url": "https://redhat.atlassian.net/issues/?jql=ff",
                    "teams": [
                        {
                            "team_name": "RHDH COPE",
                            "count": 1,
                            "status": "ok",
                            "jira_url": "https://redhat.atlassian.net/issues/?jql=team",
                        }
                    ],
                }
            ],
        }
        html = format_mod.render_report_html(report)
        assert 'class="issue-panel"' not in html
        assert 'class="issue-table"' not in html
        assert "Complete by Feature Freeze" in html
        assert "1 open" in html
        assert "Open in Jira" in html
        assert '<details class="team-breakdown">' in html
        assert "RHIDP-1" not in html

    def test_code_freeze_due_static_html_due_line(self):
        report = {
            **SAMPLE_REPORT,
            "active_section": {"title": "Code Freeze", "milestone_key": "code_freeze"},
            "results": [
                {
                    "title": "CF work remaining for Code Freeze",
                    "kind": "due",
                    "due_by_milestone": "Code Freeze",
                    "due_by_date": "2026-10-13",
                    "count": 3,
                    "status": "ok",
                    "jira_url": "https://redhat.atlassian.net/issues/?jql=cf",
                    "teams": [],
                }
            ],
        }
        html = format_mod.render_report_html(report)
        assert "Complete by Code Freeze · 2026-10-13" in html
        assert "3 open" in html
