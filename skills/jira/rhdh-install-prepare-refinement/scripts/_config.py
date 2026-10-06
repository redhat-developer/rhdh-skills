"""Bundled Install team scope for refinement briefing (RHIDP Install)."""

from __future__ import annotations

# Align freeze dates with rhdh-jira-lint when those calendars change.
RELEASE_CALENDAR: dict[str, dict[str, str]] = {
    "2.1.0": {
        "feature_freeze": "2026-09-22",
        "code_freeze": "2026-10-13",
        "ga_push": "2026-10-28",
    },
    "2.2.0": {
        "feature_freeze": "2027-01-05",
        "code_freeze": "2027-01-26",
        "ga_push": "2027-02-17",
    },
    "1.10.6": {
        "code_freeze": "2026-09-29",
        "ga_push": "2026-10-05",
    },
}

SKILL_CONFIG: dict = {
    "team": {
        "id": "ec74d716-af36-4b3c-950f-f79213d08f71-4087",
        "short_name": "Install",
    },
    "queue": {
        "project": "RHIDP",
        "statuses": ["New", "Refinement", "To Do"],
        "use_open_sprint": True,
    },
    "dashboards": {
        "feature_release_planning": {
            "label": "RHDH Feature Release Planning",
        },
        "feature_tracking": {
            "label": "Feature Tracking",
            "url": "https://redhat.atlassian.net/jira/dashboards/17955",
        },
        "team": {
            "label": "RHDH Team Dashboard",
            "url": "https://redhat.atlassian.net/jira/dashboards/22332",
        },
        "hygiene": {
            "label": "RHDH Hygiene",
            "url": "https://redhat.atlassian.net/jira/dashboards/23962",
        },
    },
    "release": {
        "primary_version": "2.1.0",
        "secondary_version": "1.10.6",
        "secondary_ga_label": "GA",
        "plan_feature_key": "RHDHPLAN-1322",
        "secondary_plan_feature_key": "RHDHPLAN-1881",
    },
    "freeze_warning_days": 14,
    "jira_base": "https://redhat.atlassian.net",
}


def load_skill_config() -> dict:
    return SKILL_CONFIG
