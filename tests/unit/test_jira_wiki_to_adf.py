"""Tests for jira-wiki-to-adf.py converter."""

import importlib.util
import json
from pathlib import Path

import pytest

JIRA_SKILL = Path(__file__).parents[2] / "skills" / "reference" / "rhdh-jira-context"
SCRIPT = JIRA_SKILL / "scripts" / "jira-wiki-to-adf.py"
AUTHORING_SKILL = Path(__file__).parents[2] / "skills" / "reference" / "rhdh-jira-authoring"
EPIC_EXAMPLE = AUTHORING_SKILL / "assets" / "examples" / "epic-example.txt"


def load_converter():
    spec = importlib.util.spec_from_file_location("jira_wiki_to_adf", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def converter():
    return load_converter()


@pytest.fixture(scope="module")
def epic_adf(converter):
    wiki = EPIC_EXAMPLE.read_text(encoding="utf-8")
    return converter.convert(wiki)


def _node_types(doc):
    return {node["type"] for node in doc.get("content", [])}


def test_epic_top_level_structure(epic_adf):
    assert epic_adf["version"] == 1
    assert epic_adf["type"] == "doc"
    assert isinstance(epic_adf["content"], list)


def test_epic_has_headings(epic_adf):
    types = _node_types(epic_adf)
    assert "heading" in types


def test_epic_has_bullet_list(epic_adf):
    types = _node_types(epic_adf)
    assert "bulletList" in types


def test_epic_has_task_list(epic_adf):
    types = _node_types(epic_adf)
    assert "taskList" in types


def test_heading_levels(epic_adf):
    headings = [n for n in epic_adf["content"] if n["type"] == "heading"]
    levels = {h["attrs"]["level"] for h in headings}
    assert 1 in levels
    assert 2 in levels


def test_task_items_have_state(epic_adf):
    task_lists = [n for n in epic_adf["content"] if n["type"] == "taskList"]
    assert task_lists, "expected at least one taskList"
    for tl in task_lists:
        for item in tl["content"]:
            assert item["attrs"]["state"] in ("TODO", "DONE")


def test_bold_inline_mark(converter):
    wiki = "*bold text*"
    doc = converter.convert(wiki)
    para = doc["content"][0]
    assert para["type"] == "paragraph"
    node = para["content"][0]
    assert node["text"] == "bold text"
    assert any(m["type"] == "strong" for m in node.get("marks", []))


def test_empty_lines_skipped(converter):
    wiki = "\n\n\nh1. Title\n\n"
    doc = converter.convert(wiki)
    assert len(doc["content"]) == 1
    assert doc["content"][0]["type"] == "heading"


def test_output_is_valid_json(converter):
    wiki = EPIC_EXAMPLE.read_text(encoding="utf-8")
    result = json.dumps(converter.convert(wiki), ensure_ascii=False)
    parsed = json.loads(result)
    assert parsed["type"] == "doc"


def test_cli_stdout(tmp_path, converter):
    """Smoke-test: script writes valid JSON to a file via the two-arg form."""
    wiki = EPIC_EXAMPLE.read_text(encoding="utf-8")
    out = tmp_path / "out.json"
    out.write_text(json.dumps(converter.convert(wiki)), encoding="utf-8")
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert parsed["type"] == "doc"
