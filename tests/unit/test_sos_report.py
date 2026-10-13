"""Unit tests for SoS report CLI helpers."""

import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SOS_SCRIPTS = PROJECT_ROOT / "skills" / "release" / "rhdh-release-sos" / "scripts"

if str(_SOS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SOS_SCRIPTS))

import sos_report as report_mod  # noqa: E402

GENERATED_AT = datetime(2026, 9, 8, 13, 22, 5, tzinfo=timezone.utc)


class TestTeamJql:
    def test_appends_team_filter(self):
        base = 'fixVersion = "2.1.0" AND sprint is EMPTY'
        assert report_mod._team_jql(base, "abc-123") == (
            'fixVersion = "2.1.0" AND sprint is EMPTY AND "Team[Team]" = "abc-123"'
        )


class TestWriteReportHtml:
    def test_writes_self_contained_file(self, tmp_path):
        report = {
            "version": "2.1.0",
            "as_of": "2026-09-02",
            "report_html": "<!DOCTYPE html><html><body>ok</body></html>",
        }
        path = report_mod.resolve_html_output_path(
            tmp_path / "rhdh-2.1.0-sos.html",
            version=report["version"],
            as_of=report["as_of"],
            generated_at=GENERATED_AT,
        )
        written = report_mod.write_report_html(report, path)
        assert written == path.resolve()
        assert path.read_text(encoding="utf-8") == report["report_html"]
        assert path.name == "rhdh-2.1.0-sos-2026-09-02-132205.html"
        assert path.is_file()

    def test_default_html_path_uses_skill_reports_dir(self):
        path = report_mod.default_html_path("2.1.0", "2026-09-02", generated_at=GENERATED_AT)
        assert path.parent == report_mod.reports_dir()
        assert path.name == "rhdh-2.1.0-sos-2026-09-02-132205.html"

    def test_explicit_html_output_gets_timestamp_suffix(self, tmp_path):
        path = report_mod.resolve_html_output_path(
            tmp_path / "reports/rhdh-2.1.0-sos.html",
            version="2.1.0",
            as_of="2026-09-08",
            generated_at=GENERATED_AT,
        )
        assert path.name == "rhdh-2.1.0-sos-2026-09-08-132205.html"

    def test_attach_html_artifact_sets_path(self, tmp_path):
        report = {
            "version": "2.1.0",
            "as_of": "2026-09-02",
            "report_html": "<!DOCTYPE html><html><body>ok</body></html>",
        }
        report_mod.attach_html_artifact(report, tmp_path / "sos.html")
        path = Path(report["report_html_path"])
        assert path.name.startswith("sos-2026-09-02-")
        assert path.name.endswith(".html")
        assert path.is_file()
