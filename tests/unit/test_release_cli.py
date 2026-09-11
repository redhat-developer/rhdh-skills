"""Unit tests for the rhdh-release scripts."""

import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

from conftest import git_env

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RELEASE_SCRIPTS = PROJECT_ROOT / "skills" / "release" / "rhdh-release-status" / "scripts"
_NO_RICH_FILTER = PROJECT_ROOT / ".test-no-rich-filter.json"
if str(_RELEASE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_RELEASE_SCRIPTS))

import jql  # noqa: E402
import release  # noqa: E402
import rich_filter  # noqa: E402
import slack_templates  # noqa: E402

# =========================================================================
# jql.py
# =========================================================================


class TestJqlLoadTemplates:
    def setup_method(self):
        jql._TEMPLATE_CACHE = None
        jql._RICH_FILTER_PATH = _NO_RICH_FILTER
        rich_filter.reset_cache()

    def teardown_method(self):
        jql._TEMPLATE_CACHE = None
        jql._RICH_FILTER_PATH = None
        rich_filter.reset_cache()

    def test_loads_9_markdown_templates(self):
        templates = jql.load_templates()
        assert len(templates) == 9

    def test_known_markdown_template_names(self):
        names = jql.list_templates()
        assert "active_release" in names
        assert "open_issues" in names
        assert "open_issues_by_type" in names
        assert "epics" in names
        assert "cves" in names
        assert "feature_subtasks" in names
        assert "features_added_to_release" in names
        assert "blockers" in names
        assert "open_issues_by_team" in names

    def test_rich_filter_templates_not_in_markdown(self):
        names = jql.list_templates()
        assert "feature_freeze_issues" not in names
        assert "feature_freeze_issues_by_team" not in names
        assert "code_freeze_issues" not in names
        assert "code_freeze_issues_by_team" not in names
        assert "release_notes" not in names
        assert "feature_demos" not in names
        assert "test_day_features" not in names
        assert "post_code_freeze_issues" not in names
        assert "release_notes_proposed" not in names
        assert "release_notes_done" not in names
        assert "release_notes_with_text" not in names


class TestJqlGetTemplate:
    def test_get_existing(self):
        tpl = jql.get_template("active_release")
        assert "rhdhplan" in tpl.lower()

    def test_get_nonexistent_raises(self):
        try:
            jql.get_template("nonexistent_query")
            assert False, "Expected KeyError"
        except KeyError as e:
            assert "nonexistent_query" in str(e)


class TestJqlRender:
    def test_render_version(self):
        rendered = jql.render("open_issues", version="1.9.0")
        assert '"1.9.0"' in rendered
        assert "{{RELEASE_VERSION}}" not in rendered

    def test_render_version_and_type(self):
        rendered = jql.render("open_issues_by_type", version="1.9.0", issue_type="Bug")
        assert '"1.9.0"' in rendered
        assert '"Bug"' in rendered
        assert "{{RELEASE_VERSION}}" not in rendered
        assert "{{ISSUE_TYPE}}" not in rendered

    def test_render_no_substitution(self):
        rendered = jql.render("active_release")
        assert "{{" not in rendered


class TestJqlUrl:
    def test_url_encoding(self):
        jql_str = "project = RHIDP AND status != closed"
        url = jql.jira_url(jql_str)
        assert url.startswith("https://redhat.atlassian.net/issues/?jql=")
        assert "%20" in url or "+" in url
        assert "project" not in url.split("jql=")[1].split("%")[0] or quote(jql_str, safe="") in url

    def test_url_encodes_special_chars(self):
        jql_str = 'fixVersion = "1.9.0" AND issuetype IN (Bug, Feature)'
        url = jql.jira_url(jql_str)
        encoded_part = url.split("jql=")[1]
        assert " " not in encoded_part
        assert '"' not in encoded_part
        assert "(" not in encoded_part

    def test_render_with_url(self):
        rendered, url = jql.render_with_url("open_issues", version="1.9.0")
        assert '"1.9.0"' in rendered
        assert url.startswith("https://redhat.atlassian.net/issues/?jql=")
        assert quote(rendered, safe="") in url


# =========================================================================
# slack_templates.py
# =========================================================================


class TestSlackLoadTemplates:
    def test_loads_4_templates(self):
        templates = slack_templates.load_templates()
        assert len(templates) == 4

    def test_known_template_keys(self):
        keys = slack_templates.list_templates()
        assert "feature_freeze_update" in keys
        assert "feature_freeze" in keys
        assert "code_freeze_update" in keys
        assert "code_freeze" in keys


class TestSlackGetTemplate:
    def test_get_existing(self):
        tpl = slack_templates.get_template("feature_freeze")
        assert "{{RELEASE_VERSION}}" in tpl

    def test_get_nonexistent_raises(self):
        try:
            slack_templates.get_template("nonexistent")
            assert False, "Expected KeyError"
        except KeyError as e:
            assert "nonexistent" in str(e)


class TestSlackFillPlaceholders:
    def test_basic_fill(self):
        template = "Hello {{NAME}}, version {{VERSION}}"
        result = slack_templates.fill_placeholders(
            template,
            {
                "NAME": "World",
                "VERSION": "1.0",
            },
        )
        assert result == "Hello World, version 1.0"

    def test_no_match_preserved(self):
        template = "{{UNKNOWN}} stays"
        result = slack_templates.fill_placeholders(template, {"OTHER": "val"})
        assert "{{UNKNOWN}}" in result


class TestSlackExpandTeamLines:
    def test_expands_team_block(self):
        template = (
            "Header\n"
            "• *{{TEAM_NAME}}* - [{{ISSUE_COUNT}}](url)\n"
            "(repeat for each active engineering team)\n"
            "Footer"
        )
        teams = [
            {"TEAM_NAME": "Alpha", "ISSUE_COUNT": "5"},
            {"TEAM_NAME": "Beta", "ISSUE_COUNT": "3"},
        ]
        result = slack_templates.expand_team_lines(template, teams)
        assert "• *Alpha* - [5](url)" in result
        assert "• *Beta* - [3](url)" in result
        assert "(repeat for each" not in result
        assert "Footer" in result


# =========================================================================
# release.py — CLI parsing
# =========================================================================


class TestReleaseParser:
    def test_no_args_exits_zero(self):
        try:
            release.main([])
        except SystemExit as e:
            assert e.code == 0

    def test_check_subcommand(self):
        parser = release.build_parser()
        args = parser.parse_args(["check"])
        assert args.command == "check"

    def test_status_subcommand(self):
        parser = release.build_parser()
        args = parser.parse_args(["status", "1.9.0"])
        assert args.command == "status"
        assert args.version == "1.9.0"

    def test_slack_subcommand(self):
        parser = release.build_parser()
        args = parser.parse_args(["slack", "feature-freeze", "1.9.0"])
        assert args.command == "slack"
        assert args.slack_command == "feature-freeze"
        assert args.version == "1.9.0"

    def test_global_json_flag(self):
        parser = release.build_parser()
        args = parser.parse_args(["--json", "status", "1.9.0"])
        assert args.output_mode == "json"

    def test_global_human_flag(self):
        parser = release.build_parser()
        args = parser.parse_args(["--human", "status", "1.9.0"])
        assert args.output_mode == "human"

    def test_verbose_flag(self):
        parser = release.build_parser()
        args = parser.parse_args(["--verbose", "check"])
        assert args.verbose is True

    def test_teams_category(self):
        parser = release.build_parser()
        args = parser.parse_args(["teams", "--category", "Engineering"])
        assert args.command == "teams"
        assert args.category == "Engineering"

    def test_all_subcommands_parse(self):
        parser = release.build_parser()
        for cmd in ["check", "dates", "slack"]:
            args = parser.parse_args([cmd])
            assert args.command == cmd
        for cmd in [
            "future-dates",
            "status",
            "team-breakdown",
            "blockers",
            "epics",
            "cves",
            "notes",
            "post-freeze",
        ]:
            args = parser.parse_args([cmd, "1.0.0"])
            assert args.command == cmd
        args = parser.parse_args(["teams"])
        assert args.command == "teams"

    def test_rich_filter_subcommands_parse(self):
        parser = release.build_parser()
        args = parser.parse_args(["rich-filter", "inventory"])
        assert args.rich_filter_command == "inventory"
        args = parser.parse_args(
            [
                "rich-filter",
                "query",
                "smart",
                "AI",
                "--group",
                "Scrum Team",
                "--version",
                "2.1.0",
                "--count",
            ]
        )
        assert args.rich_filter_command == "query"
        assert args.group == "Scrum Team"
        assert args.count is True

    def test_all_slack_subcommands_parse(self):
        parser = release.build_parser()
        for cmd in ["feature-freeze-update", "feature-freeze", "code-freeze-update", "code-freeze"]:
            args = parser.parse_args(["slack", cmd, "1.0.0"])
            assert args.slack_command == cmd


class TestParseAcliCount:
    def test_standard_output(self):
        output = "✓ Number of work items in the search: 42"
        assert release._parse_acli_count(output) == 42

    def test_multiline_with_noise(self):
        output = "Connecting...\nSearching...\n✓ Number of work items in the search: 128\n"
        assert release._parse_acli_count(output) == 128

    def test_zero_count(self):
        output = "✓ Number of work items in the search: 0"
        assert release._parse_acli_count(output) == 0

    def test_large_count(self):
        output = "✓ Number of work items in the search: 12086"
        assert release._parse_acli_count(output) == 12086

    def test_no_count_raises(self):
        try:
            release._parse_acli_count("No numbers here")
            assert False, "Expected ValueError"
        except ValueError:
            pass


class TestFetchTeams:
    ROWS = [
        ["Category", "Team Name", "Status", "Leads", "Slack Handles", "Cloud ID"],
        ["Engineering", "RHDH AI", "Active", "Ada", "@ada", "sheet-ai"],
        ["Engineering", "Cope", "Active", "Grace", "@grace", "sheet-cope"],
    ]

    def test_rich_filter_cloud_ids_override_spreadsheet(self, monkeypatch):
        monkeypatch.setattr(release, "_gog_sheets_get", lambda *_args: self.ROWS)
        monkeypatch.setattr(
            release.rf_mod,
            "scrum_teams",
            lambda: [{"name": "AI", "cloud_id": "rich-filter-ai"}],
        )

        teams = release._fetch_teams(category="Engineering")

        assert teams[0]["cloud_id"] == "rich-filter-ai"
        assert teams[0]["slack_handles"] == ["@ada"]
        assert teams[1]["cloud_id"] == "sheet-cope"

    def test_spreadsheet_cloud_ids_are_fallback(self, monkeypatch):
        monkeypatch.setattr(release, "_gog_sheets_get", lambda *_args: self.ROWS)
        monkeypatch.setattr(release.rf_mod, "scrum_teams", lambda: None)

        teams = release._fetch_teams(category="Engineering")

        assert [team["cloud_id"] for team in teams] == ["sheet-ai", "sheet-cope"]


class TestCommandMapping:
    def test_all_commands_mapped(self):
        expected_commands = {
            "check",
            "dates",
            "future-dates",
            "status",
            "teams",
            "team-breakdown",
            "blockers",
            "epics",
            "cves",
            "notes",
            "post-freeze",
        }
        assert expected_commands == set(release.COMMANDS.keys())

    def test_all_slack_commands_mapped(self):
        expected = {
            "feature-freeze-update",
            "feature-freeze",
            "code-freeze-update",
            "code-freeze",
        }
        assert expected == set(release.SLACK_COMMANDS.keys())

    def test_all_rich_filter_commands_mapped(self):
        assert {"inventory", "query"} == set(release.RICH_FILTER_COMMANDS)


# =========================================================================
# release.py — schedule parsing (inlined from schedule.py)
# =========================================================================


class TestNormalizeTeamName:
    def test_strips_rhdh_prefix(self):
        assert release._normalize_team_name("RHDH AI") == "ai"

    def test_case_insensitive_prefix(self):
        assert release._normalize_team_name("rhdh Cope") == "cope"

    def test_no_prefix(self):
        assert release._normalize_team_name("AI") == "ai"

    def test_whitespace_stripped(self):
        assert release._normalize_team_name("  RHDH AI  ") == "ai"

    def test_exact_match_lowered(self):
        assert release._normalize_team_name("Cope") == "cope"


class TestNormalizeVersion:
    def test_simple_version(self):
        assert release._normalize_version("1.9.0") == "1.9"

    def test_rhdh_prefix(self):
        assert release._normalize_version("RHDH 1.6") == "1.6"

    def test_dash_prefix(self):
        assert release._normalize_version("rhdh-1.6") == "1.6"

    def test_v_prefix(self):
        assert release._normalize_version("v1.6") == "1.6"


class TestParseDate:
    def test_iso_format(self):
        assert release._parse_date("2025-06-15") == "2025-06-15"

    def test_us_format(self):
        assert release._parse_date("06/15/2025") == "2025-06-15"

    def test_long_format(self):
        assert release._parse_date("June 15, 2025") == "2025-06-15"

    def test_unparseable(self):
        assert release._parse_date("not a date") is None


class TestExtractMilestoneDates:
    @staticmethod
    def _row(label, value):
        value_node = (
            {"type": "date", "attrs": {"timestamp": value}}
            if value != "TBD"
            else {"type": "text", "text": value}
        )
        return {
            "type": "tableRow",
            "content": [
                {"type": "tableCell", "content": [{"type": "text", "text": label}]},
                {"type": "tableCell", "content": [value_node]},
            ],
        }

    def test_extracts_adf_date_nodes_by_milestone_row(self):
        description = {
            "type": "doc",
            "content": [
                {
                    "type": "table",
                    "content": [
                        self._row("Feature Freeze", "1790035200000"),
                        self._row("Code Freeze", "1791849600000"),
                        self._row("Docs Input Freeze", "TBD"),
                        self._row("Docs Freeze", "TBD"),
                        self._row("RHDH 1.10 Go/No Go & Push", "1792972800000"),
                        self._row("RHDH 1.10 GA announce", "1793145600000"),
                    ],
                }
            ],
        }

        dates = release._extract_milestone_dates(description)

        assert dates == {
            "feature_freeze": "2026-09-22",
            "code_freeze": "2026-10-13",
            "doc_freeze": "TBD",
            "go_no_go": "2026-10-26",
            "ga_announce": "2026-10-28",
        }

    def test_supports_legacy_plain_text_descriptions(self):
        dates = release._extract_milestone_dates(
            "Feature Freeze: 2025-05-01\nCode Freeze 2025-05-15"
        )

        assert dates["feature_freeze"] == "2025-05-01"
        assert dates["code_freeze"] == "2025-05-15"
        assert dates["ga_announce"] == "TBD"

    @staticmethod
    def _text_row(label, text, marks=None):
        text_node = {"type": "text", "text": text}
        if marks:
            text_node["marks"] = marks
        return {
            "type": "tableRow",
            "content": [
                {
                    "type": "tableCell",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": label}]}
                    ],
                },
                {
                    "type": "tableCell",
                    "content": [{"type": "paragraph", "content": [text_node]}],
                },
            ],
        }

    def test_extracts_natural_language_dates_from_adf_table(self):
        from datetime import datetime

        year = datetime.now().year
        description = {
            "type": "doc",
            "content": [
                {
                    "type": "table",
                    "content": [
                        self._text_row("Code Freeze", "August 24 (done)"),
                        self._text_row("Go/No Go & Push", "September 2"),
                        self._text_row("GA Announce", "September 2"),
                    ],
                }
            ],
        }

        dates = release._extract_milestone_dates(description)

        assert dates["code_freeze"] == f"{year}-08-24"
        assert dates["go_no_go"] == f"{year}-09-02"
        assert dates["ga_announce"] == f"{year}-09-02"
        assert dates["feature_freeze"] == "TBD"

    def test_skips_strikethrough_text_in_adf(self):
        from datetime import datetime

        year = datetime.now().year
        description = {
            "type": "doc",
            "content": [
                {
                    "type": "table",
                    "content": [
                        {
                            "type": "tableRow",
                            "content": [
                                {
                                    "type": "tableCell",
                                    "content": [
                                        {
                                            "type": "paragraph",
                                            "content": [{"type": "text", "text": "Code Freeze"}],
                                        }
                                    ],
                                },
                                {
                                    "type": "tableCell",
                                    "content": [
                                        {
                                            "type": "paragraph",
                                            "content": [
                                                {"type": "text", "text": "August "},
                                                {
                                                    "type": "text",
                                                    "text": "27",
                                                    "marks": [{"type": "strike"}],
                                                },
                                                {"type": "text", "text": " 31 "},
                                            ],
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ],
        }

        dates = release._extract_milestone_dates(description)

        assert dates["code_freeze"] == f"{year}-08-31"


class TestParseNaturalDate:
    def test_full_month_day(self):
        from datetime import datetime

        year = datetime.now().year
        assert release._parse_natural_date("August 24") == f"{year}-08-24"

    def test_strips_done_annotation(self):
        from datetime import datetime

        year = datetime.now().year
        assert release._parse_natural_date("August 24 (done)") == f"{year}-08-24"

    def test_abbreviated_month(self):
        from datetime import datetime

        year = datetime.now().year
        assert release._parse_natural_date("Sep 2") == f"{year}-09-02"

    def test_full_date_with_year(self):
        assert release._parse_natural_date("August 24, 2025") == "2025-08-24"

    def test_unparseable(self):
        assert release._parse_natural_date("TBD") is None

    def test_empty(self):
        assert release._parse_natural_date("") is None


class TestFindScheduleTab:
    def test_finds_current_year(self):
        from datetime import datetime

        year = str(datetime.now().year)
        tabs = [f"RHDH {year} schedule", "Other", "Archive"]
        assert release._find_schedule_tab(tabs) == f"RHDH {year} schedule"

    def test_fallback_to_schedule(self):
        tabs = ["Other", "Schedule", "Archive"]
        assert release._find_schedule_tab(tabs) == "Schedule"

    def test_no_match(self):
        tabs = ["Sheet1", "Sheet2"]
        assert release._find_schedule_tab(tabs) is None


class TestFindMilestones:
    def test_finds_ga_and_freezes(self):
        rows = [
            ["Date", "Event", "Version"],
            ["2025-05-01", "Feature Freeze", "RHDH 1.9"],
            ["2025-05-15", "Code Freeze", "RHDH 1.9"],
            ["2025-06-01", "GA Announce", "RHDH 1.9"],
        ]
        result = release._find_milestones(rows, "1.9")
        assert result.get("ga_date") == "2025-06-01"
        assert result.get("code_freeze") == "2025-05-15"
        assert result.get("feature_freeze") == "2025-05-01"

    def test_version_not_found(self):
        rows = [
            ["Date", "Event"],
            ["2025-06-01", "GA Announce RHDH 1.8"],
        ]
        assert release._find_milestones(rows, "2.0") == {}


# =========================================================================
# rich_filter.py
# =========================================================================

SAMPLE_RICH_FILTER = {
    "richFilter": {
        "status": "active",
        "name": "RHIDP Operational",
        "jiraFilter": {
            "id": "27716",
            "name": "RHIDP Operational",
            "jql": "project in (rhidp, rhdhplan, rhdhsupp, rhdhbugs) and (resolutiondate >= -365d or status != Closed) ORDER BY priority DESC",
        },
        "staticFilters": [
            {
                "key": "k1",
                "name": "CVE",
                "jql": 'summary ~ "CVE-*"',
            },
            {
                "key": "k2",
                "name": "Feature Freeze",
                "jql": 'resolution is EMPTY AND component not in ("AEM Migration", AI) AND Type not in (Bug, Vulnerability, sub-task) AND status not in ("Dev Complete", "Release Pending", Done, Closed)',
            },
            {
                "key": "k3",
                "name": "Code Freeze",
                "jql": 'issuetype in (bug, Story, task, Vulnerability) AND status not in ("Release Pending", Closed) AND component not in ("AEM Migration", AI)',
            },
            {
                "key": "k4",
                "name": "demo",
                "jql": "labels in (demo)",
            },
            {
                "key": "k5",
                "name": "Test Day",
                "jql": "labels in (rhdh-testday)",
            },
            {
                "key": "k6",
                "name": "Post Code Freeze",
                "jql": "component not in (release, quality)",
            },
        ],
        "smartFilters": [
            {
                "key": "sf1",
                "name": "Scrum Team",
                "andEnabled": False,
                "clauses": [
                    {
                        "key": "c1",
                        "name": "AI",
                        "jql": '"Team[Team]" = ec74d716-af36-4b3c-950f-f79213d08f71-1087',
                    },
                    {
                        "key": "c2",
                        "name": "Cope",
                        "jql": '"Team[Team]" = ec74d716-af36-4b3c-950f-f79213d08f71-4403',
                    },
                ],
            },
            {
                "key": "sf2",
                "name": "Delivery Team",
                "andEnabled": False,
                "clauses": [
                    {
                        "key": "c3",
                        "name": "Engineering",
                        "jql": "Team in (ec74d716-af36-4b3c-950f-f79213d08f71-1087)",
                    },
                ],
            },
        ],
        "richQueues": [
            {
                "key": "rq1",
                "name": "RNs Unclassified",
                "jql": '("Release Note Type" not in ("Release Note Not Required") OR "release note type" is EMPTY) AND summary !~ "CVE-*"',
            },
            {
                "key": "rq2",
                "name": "RNs Proposed",
                "jql": '"Release Note Status" in (Proposed)',
            },
            {
                "key": "rq3",
                "name": "RNs Done",
                "jql": '"Release Note Status" = Done',
            },
            {
                "key": "rq4",
                "name": "Has RN Text",
                "jql": '"Release Note Text" is not EMPTY',
            },
        ],
        "dynamicFilters": [
            {
                "label": "Status",
                "value": "status",
                "handler": {"clauseName": "status"},
            }
        ],
        "richViews": [
            {
                "name": "Release Notes",
                "columns": [{"label": "Key", "value": "issuekey"}],
            }
        ],
        "timeSeries": [{"name": "Last week", "jql": "created >= -7d"}],
        "customRatios": [
            {
                "name": "Plan to Commit",
                "numJql": "labels = planned",
                "denJql": "labels = candidate",
            }
        ],
    }
}


def _write_sample_rf(tmpdir: Path) -> Path:
    """Write sample Rich Filter JSON and return the file path."""
    rf_path = tmpdir / "rf.json"
    rf_path.write_text(json.dumps(SAMPLE_RICH_FILTER))
    return rf_path


class TestRichFilterParser:
    def setup_method(self):
        rich_filter.reset_cache()

    def test_load_returns_rich_filter_dict(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        rf = rich_filter.load(rf_path)
        assert rf is not None
        assert rf["name"] == "RHIDP Operational"

    def test_load_missing_file_returns_none(self, tmp_path):
        rf = rich_filter.load(tmp_path / "nonexistent.json")
        assert rf is None

    def test_load_bad_structure_raises(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text('{"not_richFilter": {}}')
        try:
            rich_filter.load(bad)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "richFilter" in str(e)

    def test_base_jql_strips_order_by(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        base = rich_filter.base_jql(rf_path)
        assert base is not None
        assert "ORDER BY" not in base
        assert "project in" in base.lower()

    def test_static_filter_by_name(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        ff = rich_filter.static_filter("Feature Freeze", rf_path)
        assert ff is not None
        assert "resolution is EMPTY" in ff

    def test_static_filter_case_insensitive(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        ff = rich_filter.static_filter("feature freeze", rf_path)
        assert ff is not None

    def test_static_filter_not_found(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        result = rich_filter.static_filter("Nonexistent", rf_path)
        assert result is None

    def test_smart_filter_clause(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        jql_str = rich_filter.smart_filter_clause("Scrum Team", "AI", rf_path)
        assert jql_str is not None
        assert "ec74d716" in jql_str

    def test_smart_filter_clause_not_found(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        result = rich_filter.smart_filter_clause("Scrum Team", "Missing", rf_path)
        assert result is None

    def test_rich_queue(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        rn = rich_filter.rich_queue("RNs Unclassified", rf_path)
        assert rn is not None
        assert "Release Note Type" in rn

    def test_rich_queue_not_found(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        result = rich_filter.rich_queue("Missing Queue", rf_path)
        assert result is None

    def test_gets_any_fragment_kind(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        assert "demo" in rich_filter.fragment("static", "demo", path=rf_path)
        assert "Proposed" in rich_filter.fragment("queue", "RNs Proposed", path=rf_path)
        assert "Team[Team]" in rich_filter.fragment("smart", "AI", group="Scrum Team", path=rf_path)
        assert "created >= -7d" == rich_filter.fragment("time-series", "Last week", path=rf_path)
        assert "labels = planned" == rich_filter.fragment(
            "ratio-numerator", "Plan to Commit", path=rf_path
        )
        assert "labels = candidate" == rich_filter.fragment(
            "ratio-denominator", "Plan to Commit", path=rf_path
        )

    def test_smart_fragment_requires_group(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        try:
            rich_filter.fragment("smart", "AI", path=rf_path)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "--group" in str(e)

    def test_inventory_covers_queries_and_presentation_metadata(self, tmp_path):
        inventory = rich_filter.inventory(_write_sample_rf(tmp_path))
        assert inventory is not None
        assert "demo" in inventory["static_filters"]
        assert inventory["smart_filters"][0]["name"] == "Scrum Team"
        assert "RNs Done" in inventory["rich_queues"]
        assert inventory["time_series"] == ["Last week"]
        assert inventory["custom_ratios"] == ["Plan to Commit"]
        assert inventory["presentation_metadata"]["dynamic_filter_fields"] == [
            {"label": "Status", "value": "status", "clauses": ["status"]}
        ]
        assert inventory["presentation_metadata"]["rich_views"][0]["columns"] == [
            {"label": "Key", "value": "issuekey"}
        ]

    def test_validate_complete_contract(self, tmp_path):
        assert rich_filter.validate(_write_sample_rf(tmp_path)) == []

    def test_validate_reports_missing_required_entry(self, tmp_path):
        data = json.loads(json.dumps(SAMPLE_RICH_FILTER))
        data["richFilter"]["staticFilters"] = [
            item for item in data["richFilter"]["staticFilters"] if item["name"] != "Test Day"
        ]
        rf_path = tmp_path / "rf.json"
        rf_path.write_text(json.dumps(data))
        assert "required static filter missing: Test Day" in rich_filter.validate(rf_path)

    def test_scrum_teams(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        teams = rich_filter.scrum_teams(rf_path)
        assert teams is not None
        assert len(teams) == 2
        assert teams[0]["name"] == "AI"
        assert "ec74d716" in teams[0]["cloud_id"]
        assert teams[1]["name"] == "Cope"

    def test_scrum_teams_removes_jql_value_quotes(self, tmp_path):
        data = json.loads(json.dumps(SAMPLE_RICH_FILTER))
        data["richFilter"]["smartFilters"][0]["clauses"][0]["jql"] = (
            '"Team[Team]" = "quoted-cloud-id"'
        )
        rf_path = tmp_path / "rf.json"
        rf_path.write_text(json.dumps(data))

        teams = rich_filter.scrum_teams(rf_path)

        assert teams is not None
        assert teams[0]["cloud_id"] == "quoted-cloud-id"

    def test_list_static_filters(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        names = rich_filter.list_static_filters(rf_path)
        assert names is not None
        assert "Feature Freeze" in names
        assert "CVE" in names

    def test_list_smart_filters(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        names = rich_filter.list_smart_filters(rf_path)
        assert names is not None
        assert "Scrum Team" in names
        assert "Delivery Team" in names

    def test_list_rich_queues(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        names = rich_filter.list_rich_queues(rf_path)
        assert names is not None
        assert "RNs Unclassified" in names

    def test_caching(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        rf1 = rich_filter.load(rf_path)
        rf2 = rich_filter.load(rf_path)
        assert rf1 is rf2

    def test_reset_cache(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        rf1 = rich_filter.load(rf_path)
        rich_filter.reset_cache()
        rf2 = rich_filter.load(rf_path)
        assert rf1 is not rf2

    def test_load_none_without_file_returns_none(self):
        result = rich_filter.load()
        # Will return None if no file is discoverable in the default paths
        assert result is None or isinstance(result, dict)


# =========================================================================
# jql.py — Rich Filter integration
# =========================================================================


class TestJqlRichFilterIntegration:
    def setup_method(self):
        jql._TEMPLATE_CACHE = None
        rich_filter.reset_cache()

    def teardown_method(self):
        jql._TEMPLATE_CACHE = None
        jql._RICH_FILTER_PATH = None
        rich_filter.reset_cache()

    def test_adds_feature_freeze_from_rich_filter(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        jql.set_rich_filter_path(rf_path)
        templates = jql.load_templates()
        ff = templates["feature_freeze_issues"]
        assert "resolution is EMPTY" in ff
        assert "resolutiondate >= -365d or status != Closed" in ff
        assert "fixVersion" in ff
        assert "project in" in ff.lower()

    def test_adds_code_freeze_from_rich_filter(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        jql.set_rich_filter_path(rf_path)
        templates = jql.load_templates()
        cf = templates["code_freeze_issues"]
        assert "issuetype in (bug, Story, task, Vulnerability)" in cf
        assert "fixVersion" in cf

    def test_groups_rich_filter_fragment_to_preserve_scope(self, tmp_path):
        data = json.loads(json.dumps(SAMPLE_RICH_FILTER))
        data["richFilter"]["staticFilters"][2]["jql"] = "status = Open OR status = Reopened"
        rf_path = tmp_path / "rf.json"
        rf_path.write_text(json.dumps(data))
        jql.set_rich_filter_path(rf_path)

        rendered = jql.render("code_freeze_issues", version="2.1.0")

        assert rendered.startswith("(project in")
        assert 'fixVersion = "2.1.0" AND (status = Open OR status = Reopened)' in rendered

    def test_adds_release_notes_from_rich_filter(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        jql.set_rich_filter_path(rf_path)
        templates = jql.load_templates()
        rn = templates["release_notes"]
        assert "Release Note Type" in rn
        assert "fixVersion" in rn

    def test_adds_team_filter_from_rich_filter(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        jql.set_rich_filter_path(rf_path)
        templates = jql.load_templates()
        ff_team = templates["feature_freeze_issues_by_team"]
        assert "{{CLOUD_ID}}" in ff_team
        assert "Team[Team]" in ff_team

    def test_preserves_markdown_templates(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        jql.set_rich_filter_path(rf_path)
        templates = jql.load_templates()
        assert "active_release" in templates
        assert "blockers" in templates
        assert "epics" in templates
        assert "rhdhplan" in templates["active_release"].lower()

    def test_total_20_with_rich_filter(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        jql.set_rich_filter_path(rf_path)
        templates = jql.load_templates()
        assert len(templates) == 20

    def test_adds_all_release_note_lifecycle_and_post_freeze_templates(self, tmp_path):
        jql.set_rich_filter_path(_write_sample_rf(tmp_path))
        templates = jql.load_templates()
        assert "Proposed" in templates["release_notes_proposed"]
        assert "Done" in templates["release_notes_done"]
        assert "Release Note Text" in templates["release_notes_with_text"]
        assert "component not in" in templates["post_code_freeze_issues"]
        assert "labels in (demo)" in templates["feature_demos"]
        assert "labels in (rhdh-testday)" in templates["test_day_features"]

    def test_render_with_rich_filter(self, tmp_path):
        rf_path = _write_sample_rf(tmp_path)
        jql.set_rich_filter_path(rf_path)
        rendered = jql.render("feature_freeze_issues", version="2.1.0")
        assert '"2.1.0"' in rendered
        assert "{{RELEASE_VERSION}}" not in rendered


class TestJqlWithoutRichFilter:
    def setup_method(self):
        jql._TEMPLATE_CACHE = None
        jql._RICH_FILTER_PATH = None
        rich_filter.reset_cache()

    def teardown_method(self):
        jql._TEMPLATE_CACHE = None
        jql._RICH_FILTER_PATH = None
        rich_filter.reset_cache()

    def test_only_9_templates_without_rich_filter(self):
        jql.set_rich_filter_path(_NO_RICH_FILTER)
        templates = jql.load_templates()
        assert len(templates) == 9

    def test_only_9_when_path_missing(self, tmp_path):
        jql.set_rich_filter_path(tmp_path / "nonexistent.json")
        templates = jql.load_templates()
        assert len(templates) == 9

    def test_freeze_templates_missing_without_rich_filter(self):
        jql.set_rich_filter_path(_NO_RICH_FILTER)
        templates = jql.load_templates()
        assert "feature_freeze_issues" not in templates
        assert "code_freeze_issues" not in templates
        assert "release_notes" not in templates

    def test_freeze_template_raises_keyerror(self):
        jql.set_rich_filter_path(_NO_RICH_FILTER)
        try:
            jql.get_template("feature_freeze_issues")
            assert False, "Expected KeyError"
        except KeyError as e:
            assert "feature_freeze_issues" in str(e)


class TestRichFilterCliIntegration:
    def test_check_uses_native_cli_capabilities(self, tmp_path, monkeypatch, capsys):
        rf_path = _write_sample_rf(tmp_path)
        monkeypatch.setattr(release.Path, "home", lambda: tmp_path / "home")
        monkeypatch.setattr(release.rf_mod, "discover", lambda: rf_path)
        monkeypatch.setattr(release.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(
            release,
            "_run",
            lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "1", ""),
        )

        release.main(["--json", "check"])

        output = json.loads(capsys.readouterr().out)
        assert ".jira-token" not in {check["name"] for check in output["data"]["checks"]}
        assert (
            next(
                check for check in output["data"]["checks"] if check["name"] == "jira-connectivity"
            )["status"]
            == "pass"
        )
        assert output["data"]["all_pass"] is True
        assert "next_steps" not in output

    def test_epics_uses_search_payload_without_enrichment(self, monkeypatch, capsys):
        raw_issues = [
            {
                "key": "RHIDP-1",
                "fields": {
                    "summary": "An epic",
                    "status": {"name": "In Progress"},
                    "assignee": {"displayName": "Ada"},
                },
            },
            {
                "key": "RHIDP-2",
                "fields": {
                    "summary": "Unassigned epic",
                    "status": {"name": "New"},
                    "assignee": None,
                },
            },
        ]
        monkeypatch.setattr(release, "_init_rich_filter", lambda: None)
        monkeypatch.setattr(
            release,
            "_run",
            lambda *args, **kwargs: subprocess.CompletedProcess(
                args[0], 0, json.dumps(raw_issues), ""
            ),
        )
        monkeypatch.setattr(
            release,
            "_acli_json_enriched",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("EPICs must not use per-issue enrichment")
            ),
        )

        release.main(["--json", "epics", "2.1.0"])

        data = json.loads(capsys.readouterr().out)["data"]
        assert data["count"] == 2
        assert data["epics"] == [
            {
                "key": "RHIDP-1",
                "summary": "An epic",
                "status": "In Progress",
                "assignee": "Ada",
            },
            {
                "key": "RHIDP-2",
                "summary": "Unassigned epic",
                "status": "New",
                "assignee": "Unassigned",
            },
        ]

    def test_check_reports_partial_export_contract(self, tmp_path, monkeypatch, capsys):
        data = json.loads(json.dumps(SAMPLE_RICH_FILTER))
        data["richFilter"]["richQueues"] = [
            queue for queue in data["richFilter"]["richQueues"] if queue["name"] != "RNs Done"
        ]
        rf_path = tmp_path / "partial.json"
        rf_path.write_text(json.dumps(data))
        monkeypatch.setattr(release.rf_mod, "discover", lambda: rf_path)
        monkeypatch.setattr(release.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(
            release,
            "_run",
            lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "1", ""),
        )

        try:
            release.main(["--json", "check"])
            assert False, "Expected SystemExit"
        except SystemExit as error:
            assert error.code == 1

        output = json.loads(capsys.readouterr().out)
        contract = next(
            check for check in output["data"]["checks"] if check["name"] == "rich-filter-contract"
        )
        assert contract["status"] == "fail"
        assert "RNs Done" in contract["message"]

    def test_inventory_command_exposes_catalog(self, monkeypatch, capsys):
        catalog = {
            "name": "RHIDP Operational",
            "static_filters": ["demo"],
            "smart_filters": [{"name": "Scrum Team", "clauses": ["AI"]}],
            "rich_queues": ["RNs Proposed"],
            "presentation_metadata": {"rich_views": ["Default"]},
        }
        monkeypatch.setattr(release, "_init_rich_filter", lambda: None)
        monkeypatch.setattr(release.rf_mod, "inventory", lambda: catalog)

        release.main(["--json", "rich-filter", "inventory"])

        output = json.loads(capsys.readouterr().out)
        assert output["data"] == catalog

    def test_query_command_composes_and_counts_fragment(self, monkeypatch, capsys):
        monkeypatch.setattr(release, "_init_rich_filter", lambda: None)
        monkeypatch.setattr(
            release.rf_mod,
            "fragment",
            lambda kind, name, group=None: 'labels in ("demo")',
        )
        monkeypatch.setattr(release, "_acli_count", lambda jql_value, fmt: 7)

        release.main(
            [
                "--json",
                "rich-filter",
                "query",
                "static",
                "demo",
                "--version",
                "2.1.0",
                "--count",
            ]
        )

        data = json.loads(capsys.readouterr().out)["data"]
        assert 'fixVersion = "2.1.0"' in data["jql"]
        assert 'labels in ("demo")' in data["jql"]
        assert data["count"] == 7

    def test_notes_command_reports_all_lifecycle_stages(self, monkeypatch, capsys):
        counts = {
            "release_notes": 8,
            "release_notes_proposed": 5,
            "release_notes_done": 3,
            "release_notes_with_text": 2,
        }
        monkeypatch.setattr(release, "_init_rich_filter", lambda: None)
        monkeypatch.setattr(
            release.jql_mod,
            "render_with_url",
            lambda name, version=None: (name, f"https://jira/{name}"),
        )
        monkeypatch.setattr(release, "_acli_count", lambda query, fmt: counts[query])

        release.main(["--json", "notes", "2.1.0"])

        data = json.loads(capsys.readouterr().out)["data"]
        assert data["outstanding_count"] == 8
        assert {name: item["count"] for name, item in data["lifecycle"].items()} == {
            "unclassified": 8,
            "proposed": 5,
            "done": 3,
            "with_text": 2,
        }

    def test_post_freeze_command_returns_count_and_link(self, monkeypatch, capsys):
        monkeypatch.setattr(release, "_init_rich_filter", lambda: None)
        monkeypatch.setattr(
            release.jql_mod,
            "render_with_url",
            lambda name, version=None: (name, "https://jira/post-freeze"),
        )
        monkeypatch.setattr(release, "_acli_count", lambda query, fmt: 4)

        release.main(["--json", "post-freeze", "2.1.0"])

        assert json.loads(capsys.readouterr().out)["data"] == {
            "version": "2.1.0",
            "count": 4,
            "jira_url": "https://jira/post-freeze",
        }

    def test_direct_script_discovers_project_config(self, tmp_path):
        private_data = tmp_path / "private-data"
        rf_path = private_data / "jira-rich-filter" / "rhidp-operational-rich-filter.json"
        rf_path.parent.mkdir(parents=True)
        rf_path.write_text(json.dumps(SAMPLE_RICH_FILTER))

        project = tmp_path / "project"
        config_dir = project / ".rhdh"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text(
            json.dumps({"repos": {"private-data": str(private_data)}})
        )
        env = git_env(HOME=str(tmp_path / "home"))
        env.pop("PYTHONPATH", None)
        subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True, env=env)

        code = (
            "import sys; "
            f"sys.path.insert(0, {str(_RELEASE_SCRIPTS)!r}); "
            "import rich_filter; print(rich_filter.discover())"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=project,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )

        assert result.stdout.strip() == str(rf_path)

    def test_missing_rich_filter_is_reported_without_traceback(self, monkeypatch, capsys):
        jql.set_rich_filter_path(_NO_RICH_FILTER)
        monkeypatch.setattr(release, "_init_rich_filter", lambda: None)

        try:
            release.main(["--json", "notes", "2.1.0"])
            assert False, "Expected SystemExit"
        except SystemExit as e:
            assert e.code == 1

        output = json.loads(capsys.readouterr().out)
        assert output["error"]["code"] == "CONFIGURATION_ERROR"
        assert "release_notes" in output["error"]["message"]
