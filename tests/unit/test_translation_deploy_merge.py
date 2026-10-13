"""Unit tests for rhdh-translation-deploy locale merge helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "release"
    / "rhdh-translation-deploy"
    / "scripts"
)
SCRIPT = SCRIPTS / "translation_deploy.py"
SUPPORT = SCRIPTS / "_support.py"


def _load_deploy_module():
    """Load translation_deploy with this skill's _support, not another skill's.

    Several skills ship a scripts/_support.py. Pytest may already have imported
    a different one as ``_support``; insert the deploy skill's copy first.
    """
    prev_support = sys.modules.get("_support")

    support_spec = importlib.util.spec_from_file_location(
        "_support",
        SUPPORT,
    )
    assert support_spec is not None and support_spec.loader is not None
    support_mod = importlib.util.module_from_spec(support_spec)
    sys.modules["_support"] = support_mod
    support_spec.loader.exec_module(support_mod)

    spec = importlib.util.spec_from_file_location(
        "rhdh_translation_deploy",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rhdh_translation_deploy"] = mod
    scripts_dir = str(SCRIPTS)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        spec.loader.exec_module(mod)
    finally:
        if prev_support is not None:
            sys.modules["_support"] = prev_support
        else:
            sys.modules.pop("_support", None)
    return mod


@pytest.fixture(scope="module")
def deploy_mod():
    return _load_deploy_module()


def test_format_ts_string_apostrophe_uses_double_quotes(deploy_mod):
    assert deploy_mod._format_ts_string("l'agent") == '"l\'agent"'


def test_format_ts_string_plain_single_quotes(deploy_mod):
    assert deploy_mod._format_ts_string("Hello") == "'Hello'"


def test_merge_updates_existing_skips_missing(deploy_mod, tmp_path: Path):
    ts = tmp_path / "de.ts"
    ts.write_text(
        "export default {\n"
        "  messages: {\n"
        "    'common.loading': 'Wird geladen',\n"
        "    'common.retry': 'Erneut',\n"
        "  },\n"
        "};\n",
        encoding="utf-8",
    )
    counts = deploy_mod._merge_locale_file(
        ts,
        {
            "common.loading": "Ladevorgang",
            "common.brandNew": "Neu",
        },
    )
    text = ts.read_text(encoding="utf-8")
    assert counts["updated"] == 1
    assert counts["skipped"] == 1
    assert "'common.loading': 'Ladevorgang'" in text
    assert "'common.retry': 'Erneut'" in text
    assert "common.brandNew" not in text


def test_merge_never_removes_keys(deploy_mod, tmp_path: Path):
    ts = tmp_path / "es.ts"
    ts.write_text(
        "const m = {\n  messages: {\n    'a.keep': 'keep',\n    'a.update': 'old',\n  },\n};\n",
        encoding="utf-8",
    )
    deploy_mod._merge_locale_file(ts, {"a.update": "new"})
    text = ts.read_text(encoding="utf-8")
    assert "'a.keep': 'keep'" in text
    assert "'a.update': 'new'" in text


def test_incoming_keys_from_download_flattens_en(deploy_mod):
    data = {
        "plugin.foo": {
            "en": {"page.title": "Título"},
        }
    }
    assert deploy_mod._incoming_keys_from_download(data) == {"plugin.foo": {"page.title": "Título"}}


def test_load_survives_foreign_support_module(monkeypatch):
    """Reproduce CI: another skill's _support is already in sys.modules."""
    foreign = type(sys)("foreign_support")
    monkeypatch.setitem(sys.modules, "_support", foreign)
    mod = _load_deploy_module()
    assert hasattr(mod, "_merge_locale_file")
    assert hasattr(mod, "_format_ts_string")
