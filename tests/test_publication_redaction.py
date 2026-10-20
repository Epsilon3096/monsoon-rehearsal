"""Public-source sanitisation must not alter model code or rainfall values."""
import hashlib
import json
import re

from monsoon.service import ROOT
from monsoon.demo_ui import BENCHMARK, MANIFEST_SHA256
from monsoon.maintenance_benchmark import load_results
from monsoon.decision_review import load_decision_review


def test_public_html_redactions_match_explicit_manifest():
    manifest = json.loads((ROOT / "data/public_evidence/manifest-jps-epa.json").read_text(encoding="utf-8"))
    redacted = [i for i in manifest["items"] if "redaction" in i]
    assert len(redacted) == 2
    for item in redacted:
        raw = (ROOT / item["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        assert len(raw) == item["bytes"]
        assert item["original_response_sha256"] != item["sha256"]
        assert not re.search(rb"AIza[0-9A-Za-z_-]{35}", raw)
        assert b"REDACTED_PUBLIC_PAGE_" in raw
    assert sum(i["redaction"]["replacements"] for i in redacted) == 5


def test_rainfall_csv_and_application_sources_are_unchanged():
    csv = ROOT / "data/public_evidence/jps/jps_selangor_rainfall_snapshot.csv"
    assert hashlib.sha256(csv.read_bytes()).hexdigest() == "3301c505fb8f25c55ca8483c4e389bebbd18fc8c40c30ba1186f4659f5a2afd6"
    freeze = json.loads((ROOT / "evidence/v0.9/release-verification.json").read_text(encoding="utf-8"))
    checked = 0
    for name, expected in freeze["source_sha256"].items():
        if name.startswith("monsoon/") or name == "app.py":
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
            checked += 1
    assert checked > 20


def test_native_benchmark_and_original_decision_evidence_still_verify():
    assert load_results(BENCHMARK, MANIFEST_SHA256)["status"] == "verified"
    assert load_decision_review(ROOT)["status"] == "verified"
