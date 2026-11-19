"""Dossiers give each fresh-context investigator one self-contained file; the
corpus command builds the bounded open-and-closed candidate base in one step."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = PROJECT_ROOT / "skills/jira/rhdh-bug-triage/scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bug_triage"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from bugtriage import jira  # noqa: E402
from bugtriage.dossier import render_dossier, write_dossiers  # noqa: E402
from bugtriage.model import load_export, normalize_issue  # noqa: E402
from bugtriage.run import RunError  # noqa: E402


def fixture_tickets():
    return load_export(str(FIXTURES / "issues.json"))


def minimal_sample(tmp_path: Path, key: str) -> Path:
    sample = tmp_path / "sample.json"
    sample.write_text(
        json.dumps(
            {
                "schemaVersion": 3,
                "currentRelease": "2.1.0",
                "scope": "aged",
                "tickets": [{"key": key, "kind": "aged", "stratum": "RHDH Test"}],
            }
        ),
        encoding="utf-8",
    )
    return sample


class TestDossiers:
    def test_one_self_contained_file_per_ticket(self, tmp_path):
        tickets = fixture_tickets()
        key = tickets[0].key
        sample = minimal_sample(tmp_path, key)
        written = write_dossiers(
            input_path=str(FIXTURES / "issues.json"),
            sample_path=str(sample),
            output_dir=str(tmp_path / "dossiers"),
        )
        assert list(written) == [key]
        text = (tmp_path / "dossiers" / f"{key}.md").read_text(encoding="utf-8")
        assert text.startswith(f"# {key} — ")
        assert "## Ticket facts" in text
        assert "## Report" in text
        assert "## Your task (investigator)" in text
        assert "Escalate before recording an unknown" in text
        assert f"assessments/{key}.json" in text

    def test_dossier_includes_collected_leads(self, tmp_path):
        tickets = fixture_tickets()
        ticket = tickets[0]
        evidence = {
            "discovery": {
                "leads": [
                    {
                        "key": "RHDHBUGS-9001",
                        "foundBy": ["defect_search"],
                        "warnings": ["candidate is not older"],
                    }
                ]
            },
            "pullRequests": [{"url": "https://github.com/example/product/pull/1"}],
            "searchMode": "live",
            "unsearchedLinkedKeys": ["RHDHBUGS-9002"],
        }
        text = render_dossier(ticket, evidence, {"kind": "aged", "stratum": "RHDH Test"})
        assert "RHDHBUGS-9001: defect_search" in text
        assert "candidate is not older" in text
        assert "https://github.com/example/product/pull/1" in text
        assert "RHDHBUGS-9002" in text

    def test_refuses_existing_directory(self, tmp_path):
        tickets = fixture_tickets()
        sample = minimal_sample(tmp_path, tickets[0].key)
        existing = tmp_path / "dossiers"
        existing.mkdir()
        with pytest.raises(RunError, match="fresh directory"):
            write_dossiers(
                input_path=str(FIXTURES / "issues.json"),
                sample_path=str(sample),
                output_dir=str(existing),
            )

    def test_sample_key_missing_from_export_fails(self, tmp_path):
        sample = minimal_sample(tmp_path, "RHDHBUGS-9999")
        with pytest.raises(RunError, match="absent from the export"):
            write_dossiers(
                input_path=str(FIXTURES / "issues.json"),
                sample_path=str(sample),
                output_dir=str(tmp_path / "dossiers"),
            )


class TestCorpus:
    def test_merges_parts_with_provenance(self, tmp_path, monkeypatch):
        search_records = [
            {"key": "RHDHBUGS-5001", "fields": {"summary": "Open search hit"}},
            {"key": "RHDHBUGS-5002", "fields": {"summary": "Closed search hit"}},
        ]
        full_issue = {"key": "RHDHBUGS-6001", "fields": {"summary": "Full read"}}
        monkeypatch.setattr(jira, "search_acli", lambda jql, **kw: search_records)
        monkeypatch.setattr(
            jira,
            "export_from_acli",
            lambda jql, **kw: {"issues": [full_issue], "fieldNames": {"customfield_1": "Name"}},
        )
        document = jira.build_corpus(
            search_jqls=["project = RHDHBUGS AND statusCategory != Done"],
            full_jqls=["project = RHDHBUGS AND statusCategory = Done AND fixVersion IS NOT EMPTY"],
        )
        assert [record["key"] for record in document["issues"]] == [
            "RHDHBUGS-5001",
            "RHDHBUGS-5002",
            "RHDHBUGS-6001",
        ]
        assert document["fieldNames"] == {"customfield_1": "Name"}
        parts = document["provenance"]["parts"]
        assert [part["level"] for part in parts] == ["search-level", "full-reads"]
        assert parts[0]["count"] == 2
        assert "lack created" in parts[0]["gaps"]
        assert parts[1]["count"] == 1

    def test_overlapping_parts_are_refused(self, monkeypatch):
        records = [{"key": "RHDHBUGS-5001", "fields": {"summary": "Hit"}}]
        monkeypatch.setattr(jira, "search_acli", lambda jql, **kw: records)
        with pytest.raises(jira.JiraAdapterError, match="overlap"):
            jira.build_corpus(
                search_jqls=["query one", "query two"],
                full_jqls=[],
            )

    def test_search_parts_rank_as_leads_without_chronology(self, monkeypatch):
        monkeypatch.setattr(
            jira,
            "search_acli",
            lambda jql, **kw: [
                {"key": "RHDHBUGS-5001", "fields": {"summary": "Closed search hit"}}
            ],
        )
        document = jira.build_corpus(search_jqls=["closed partition"], full_jqls=[])
        tickets = [normalize_issue(record) for record in document["issues"]]
        assert tickets[0].key == "RHDHBUGS-5001"
        # Search-level records cannot claim chronology or completeness.
        assert not tickets[0].created
