"""Best-effort RHDH y-stream support lookup via the Product Life Cycles API."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

LIFECYCLE_API_URL = "https://access.redhat.com/product-life-cycles/api/v1/products"
RHDH_PRODUCT_NAME = "Red Hat Developer Hub"


def _phase_end_date(phases: list[dict[str, Any]], phase_name: str) -> str | None:
    for phase in phases:
        if phase.get("name") == phase_name:
            end_date = phase.get("end_date")
            if isinstance(end_date, str) and len(end_date) >= 10:
                return end_date[:10]
    return None


def lookup_rhdh_stream_support(stream: str) -> dict[str, Any]:
    """Return whether an RHDH y-stream (e.g. 1.9) is still vendor-supported."""
    url = f"{LIFECYCLE_API_URL}?name={urllib.parse.quote_plus(RHDH_PRODUCT_NAME)}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "rhdh-release-fixversions"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return {
            "stream": stream,
            "checked": False,
            "supported": None,
            "error": str(exc),
            "source": LIFECYCLE_API_URL,
        }

    versions = payload.get("data", [{}])[0].get("versions", [])
    for entry in versions:
        if entry.get("name") != stream:
            continue
        version_type = entry.get("type", "")
        phases = entry.get("phases", [])
        return {
            "stream": stream,
            "checked": True,
            "supported": version_type != "End of life",
            "type": version_type,
            "ga_date": _phase_end_date(phases, "General availability"),
            "maintenance_end": _phase_end_date(phases, "Maintenance support"),
            "full_support_end": _phase_end_date(phases, "Full support"),
            "error": None,
            "source": LIFECYCLE_API_URL,
        }

    return {
        "stream": stream,
        "checked": True,
        "supported": None,
        "error": f"RHDH stream {stream} not found in lifecycle API",
        "source": LIFECYCLE_API_URL,
    }
