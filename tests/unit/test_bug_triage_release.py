"""Release tag parsing and release-notes lookup; no network in these tests."""

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/jira/rhdh-bug-triage/scripts"
sys.path.insert(0, str(SCRIPTS))

from bugtriage import cli, release  # noqa: E402

TAGS = "\n".join(
    [
        "1111111111111111111111111111111111111111\trefs/tags/1.10.7",
        "2222222222222222222222222222222222222222\trefs/tags/2.1",
        "3333333333333333333333333333333333333333\trefs/tags/2.1.0",
        "4444444444444444444444444444444444444444\trefs/tags/2.1.0^{}",
        "5555555555555555555555555555555555555555\trefs/tags/redhat-developer-hub-2.6.0",
        "6666666666666666666666666666666666666666\trefs/tags/v0.2.0",
        "7777777777777777777777777777777777777777\trefs/heads/main",
    ]
)


def test_only_exact_numeric_tags_are_release_candidates():
    assert release.parse_release_tags(TAGS) == ["1.10.7", "2.1.0"]
    row = release.describe_repository("redhat-developer/rhdh", TAGS)
    assert row["latest"] == "2.1.0"
    # 2.1, the peeled companion, the chart tag and v0.2.0 are all ignored.
    assert row["ignoredTagRefs"] == 4


def test_release_notes_urls_cover_both_layouts():
    legacy, current = release.release_notes_urls("1.10.7")["fixedIssues"]
    assert legacy == (
        "https://docs.redhat.com/en/documentation/red_hat_developer_hub/1.10/"
        "html/red_hat_developer_hub_release_notes/fixed-issues"
    )
    assert current.endswith("/1.10/whats_new-fixed_issues")
    security = release.release_notes_urls("2.1.0")["fixedSecurityIssues"]
    assert security[0].endswith(
        "/2.1/html/red_hat_developer_hub_release_notes/fixed-security-issues"
    )
    assert security[1].endswith("/2.1/whats_new-fixed_security_issues")


def test_disagreeing_repositories_do_not_produce_a_latest(monkeypatch):
    outputs = {
        "redhat-developer/rhdh": "a\trefs/tags/2.1.0\n",
        "redhat-developer/rhdh-chart": "b\trefs/tags/2.1.1\n",
    }
    monkeypatch.setattr(release, "read_release_tags", lambda repo, timeout=60: outputs[repo])
    document = release.resolve_release(list(outputs))
    assert document["agreement"] is False
    assert document["latest"] is None
    assert document["releaseNotes"] == {}
    monkeypatch.setattr(
        release, "read_release_tags", lambda repo, timeout=60: "a\trefs/tags/2.1.0\n"
    )
    document = release.resolve_release(["redhat-developer/rhdh"])
    assert document["agreement"] is True
    assert document["latest"] == "2.1.0"


def test_release_command_defaults_to_the_product_repository(monkeypatch, capsys):
    seen = []

    def tags(repository, timeout=60):
        seen.append(repository)
        return TAGS

    monkeypatch.setattr(release, "read_release_tags", tags)
    assert cli.main(["release", "--json"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert seen == ["redhat-developer/rhdh"]
    assert document["latest"] == "2.1.0"
    assert document["agreement"] is True
    assert "not proof of shipment" in document["limits"]


def test_release_rejects_a_non_repository_argument():
    with pytest.raises(ValueError, match="owner/repo"):
        release.read_release_tags("--upload-pack=evil")
