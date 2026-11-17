"""
Regression tests for scripts/check_release_safety.py secret rules.

Synthetic tokens are assembled at runtime so this source file never contains a
literal credential-shaped string. The scanner must report each rule by name and
must never echo the matched value.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_safety():
    spec = importlib.util.spec_from_file_location("check_release_safety", ROOT / "scripts" / "check_release_safety.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


safety = _load_safety()


@pytest.mark.parametrize(
    ("rule", "token"),
    [
        ("shopify-token", "shp" + "at_" + "a" * 32),
        ("shopify-token", "shp" + "ss_" + "B" * 40),
        ("llm-api-key", "s" + "k-" + "ant-" + "C" * 40),
        ("llm-api-key", "s" + "k-" + "proj-" + "D" * 40),
        ("google-api-key", "AI" + "za" + "E" * 35),
    ],
)
def test_new_secret_rules_detect_synthetic_tokens(tmp_path, rule, token):
    (tmp_path / "leak.txt").write_text(f"value={token}\n", encoding="utf-8")
    errors = safety.inspect_files(tmp_path, ["leak.txt"])
    assert errors == [f"leak.txt: {rule}"]
    assert token not in repr(errors)


def test_ordinary_identifiers_are_not_flagged(tmp_path):
    benign = "task-runner sk-small and Shopify docs shp_short AIza-short\n"
    (tmp_path / "notes.txt").write_text(benign, encoding="utf-8")
    assert safety.inspect_files(tmp_path, ["notes.txt"]) == []


def test_redaction_fixture_prefix_is_the_only_llm_exclusion(tmp_path):
    """The sk-super- prefix (redaction test fixtures) is excluded; any other sk- key is not."""
    fixture = "s" + "k-super-" + "x" * 40
    real_looking = "s" + "k-proj-" + "x" * 40
    (tmp_path / "fixture.txt").write_text(fixture + "\n", encoding="utf-8")
    (tmp_path / "real.txt").write_text(real_looking + "\n", encoding="utf-8")
    assert safety.inspect_files(tmp_path, ["fixture.txt"]) == []
    assert safety.inspect_files(tmp_path, ["real.txt"]) == ["real.txt: llm-api-key"]
