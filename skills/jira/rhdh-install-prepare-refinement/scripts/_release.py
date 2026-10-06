"""Release window helpers from bundled calendar."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
@dataclass(frozen=True)
class ReleaseContext:
    primary_version: str
    secondary_version: str
    secondary_ga_label: str
    code_freeze_date: date | None
    days_to_code_freeze: int | None
    candidate_label: str
    plan_feature_key: str
    secondary_plan_feature_key: str
    freeze_warning: bool


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def candidate_label_for_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) >= 2:
        return f"rhdh-{parts[0]}.{parts[1]}-candidate"
    return f"rhdh-{version}-candidate"


def build_release_context(
    config: dict,
    releases: dict[str, dict[str, str]],
    today: date | None = None,
) -> ReleaseContext:
    today = today or date.today()
    rel_cfg = config.get("release", {})
    primary = rel_cfg.get("primary_version", "2.1.0")
    secondary = rel_cfg.get("secondary_version", "1.10.6")
    primary_meta = releases.get(primary, {})
    freeze_raw = primary_meta.get("code_freeze")
    freeze_date = _parse_date(freeze_raw) if freeze_raw else None
    days = (freeze_date - today).days if freeze_date else None
    warning_days = int(config.get("freeze_warning_days", 14))
    return ReleaseContext(
        primary_version=primary,
        secondary_version=secondary,
        secondary_ga_label=rel_cfg.get("secondary_ga_label", "GA"),
        code_freeze_date=freeze_date,
        days_to_code_freeze=days,
        candidate_label=candidate_label_for_version(primary),
        plan_feature_key=rel_cfg.get("plan_feature_key", "RHDHPLAN-1322"),
        secondary_plan_feature_key=rel_cfg.get("secondary_plan_feature_key", "RHDHPLAN-1881"),
        freeze_warning=days is not None and days <= warning_days,
    )
