"""Parse JQL templates from references/jql-release.md and Rich Filter JSON.

Reads the markdown file at runtime so the CLI and agent share one source of truth.
Supports placeholder rendering ({{RELEASE_VERSION}}, {{ISSUE_TYPE}}) and
URL-encoded Jira search links.

Eleven templates are sourced exclusively from the Rich Filter JSON export,
including freeze scopes, demo/Test Day filters, and release-note lifecycle
queues. These templates are only available when the Rich Filter is configured.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

JIRA_SEARCH_BASE = "https://redhat.atlassian.net/issues/?jql="

_DATA_DIR = Path(__file__).resolve().parent
_JQL_FILE = _DATA_DIR / "jql-release.md"

_TEMPLATE_CACHE: dict[str, str] | None = None
_RICH_FILTER_PATH: Path | str | None = None


def _parse_jql_file(path: Path | None = None) -> dict[str, str]:
    """Parse ## headings and ```jql code blocks from jql-release.md."""
    path = path or _JQL_FILE
    text = path.read_text()
    templates: dict[str, str] = {}
    current_name: str | None = None
    jql_lines: list[str] | None = None

    for line in text.splitlines():
        heading = re.match(r"^##\s+(\S+)", line)
        if heading:
            current_name = heading.group(1)
            continue

        if current_name and line.strip() == "```jql":
            jql_lines = []
            continue

        if current_name and jql_lines is not None and line.strip() == "```":
            templates[current_name] = " ".join(jql_lines).strip()
            current_name = None
            jql_lines = None
            continue

        if jql_lines is not None:
            jql_lines.append(line.strip())

    return templates


def set_rich_filter_path(path: Path | str | None) -> None:
    """Configure the Rich Filter JSON location.

    Calling this invalidates the template cache so the next load_templates()
    call will re-compose templates with (or without) Rich Filter data.
    """
    global _RICH_FILTER_PATH, _TEMPLATE_CACHE
    _RICH_FILTER_PATH = path
    _TEMPLATE_CACHE = None


def _apply_rich_filter_overlay(templates: dict[str, str]) -> dict[str, str]:
    """Override specific templates with Rich Filter-sourced queries.

    The Rich Filter provides filter fragments (no project scope or fixVersion).
    We compose the full query as: base_scope + fixVersion + fragment.
    """
    import rich_filter as rf_mod

    rf = rf_mod.load(_RICH_FILTER_PATH)
    if rf is None:
        return templates

    result = dict(templates)

    base_scope = rf_mod.base_jql(_RICH_FILTER_PATH)

    def _compose(fragment: str, extra: str = "") -> str:
        return compose_fragment(
            fragment,
            version="{{RELEASE_VERSION}}",
            extra=extra,
            base_scope=base_scope,
        )

    ff_jql = rf_mod.static_filter("Feature Freeze", _RICH_FILTER_PATH)
    if ff_jql:
        result["feature_freeze_issues"] = _compose(ff_jql)
        result["feature_freeze_issues_by_team"] = _compose(ff_jql, '"Team[Team]" = "{{CLOUD_ID}}"')

    cf_jql = rf_mod.static_filter("Code Freeze", _RICH_FILTER_PATH)
    if cf_jql:
        result["code_freeze_issues"] = _compose(cf_jql)
        result["code_freeze_issues_by_team"] = _compose(cf_jql, '"Team[Team]" = "{{CLOUD_ID}}"')

    static_templates = {
        "feature_demos": "demo",
        "test_day_features": "Test Day",
        "post_code_freeze_issues": "Post Code Freeze",
    }
    for template_name, filter_name in static_templates.items():
        fragment = rf_mod.static_filter(filter_name, _RICH_FILTER_PATH)
        if fragment:
            result[template_name] = _compose(fragment)

    queue_templates = {
        "release_notes": "RNs Unclassified",
        "release_notes_proposed": "RNs Proposed",
        "release_notes_done": "RNs Done",
        "release_notes_with_text": "Has RN Text",
    }
    for template_name, queue_name in queue_templates.items():
        fragment = rf_mod.rich_queue(queue_name, _RICH_FILTER_PATH)
        if fragment:
            result[template_name] = _compose(fragment)

    return result


def compose_fragment(
    fragment: str,
    *,
    version: str | None = None,
    extra: str | None = None,
    base_scope: str | None = None,
) -> str:
    """Compose an exported JQL fragment with project and release scope."""
    if base_scope is None:
        import rich_filter as rf_mod

        base = rf_mod.base_jql(_RICH_FILTER_PATH)
        if base:
            base_scope = base

    parts = []
    if base_scope:
        # The base can contain a top-level OR, so group it before adding scope.
        parts.append(f"({base_scope})")
    if version is not None:
        parts.append(f'fixVersion = "{version}"')
    # Exported fragments can contain top-level OR expressions. Group them so
    # every branch remains constrained by the preceding scope.
    parts.append(f"({fragment})")
    if extra:
        parts.append(extra)
    return " AND ".join(parts)


def load_templates(path: Path | None = None) -> dict[str, str]:
    """Load and cache JQL templates from jql-release.md.

    If a Rich Filter path is configured, overlays Rich Filter-sourced
    queries onto the markdown templates for supported template names.
    """
    global _TEMPLATE_CACHE
    if path is not None:
        return _parse_jql_file(path)
    if _TEMPLATE_CACHE is None:
        templates = _parse_jql_file()
        _TEMPLATE_CACHE = _apply_rich_filter_overlay(templates)
    return _TEMPLATE_CACHE


def get_template(name: str, path: Path | None = None) -> str:
    """Get a single JQL template by name. Raises KeyError if not found."""
    templates = load_templates(path)
    if name not in templates:
        available = ", ".join(sorted(templates))
        raise KeyError(f"Unknown JQL template '{name}'. Available: {available}")
    return templates[name]


def render(
    name: str,
    *,
    version: str | None = None,
    issue_type: str | None = None,
    cloud_id: str | None = None,
    path: Path | None = None,
) -> str:
    """Render a JQL template with placeholder substitution."""
    jql = get_template(name, path)
    if version is not None:
        jql = jql.replace("{{RELEASE_VERSION}}", version)
    if issue_type is not None:
        jql = jql.replace("{{ISSUE_TYPE}}", issue_type)
    if cloud_id is not None:
        jql = jql.replace("{{CLOUD_ID}}", cloud_id)
    return jql


def jira_url(jql: str) -> str:
    """Build a Jira search URL from a JQL string."""
    return JIRA_SEARCH_BASE + quote(jql, safe="")


def render_with_url(
    name: str,
    *,
    version: str | None = None,
    issue_type: str | None = None,
    cloud_id: str | None = None,
    path: Path | None = None,
) -> tuple[str, str]:
    """Render a JQL template and return (jql, jira_url)."""
    jql = render(name, version=version, issue_type=issue_type, cloud_id=cloud_id, path=path)
    return jql, jira_url(jql)


def list_templates(path: Path | None = None) -> list[str]:
    """Return sorted list of available template names."""
    return sorted(load_templates(path))
