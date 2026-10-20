import copy
import hashlib
import json
from pathlib import Path

import pytest

from monsoon import site_data

TEMPLATES = Path(__file__).resolve().parents[1] / "data" / "templates"


@pytest.fixture
def site():
    return json.loads((TEMPLATES / "synthetic_site_v1.json").read_text())


def codes(report):
    return {issue["code"] for issue in report["errors"]}


def test_fixture_is_valid_but_never_active_or_measured(site):
    before = copy.deepcopy(site)
    result = site_data.validate_site_package(site)
    assert result["valid"] and result["status"] == "ready_for_review"
    assert result["contract_status"] == "draft_pending_operator_acceptance"
    assert not result["operational_activation_allowed"]
    assert not result["physical_validation_established"]
    assert result["evidence_kind"] == "synthetic_fixture"
    assert site == before
    assert result == site_data.validate_site_package(json.dumps(site).encode())


def test_fixture_source_hash_names_actual_bytes(site):
    raw = (TEMPLATES / "synthetic_source_evidence.txt").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == site["sources"][0]["sha256"]


@pytest.mark.parametrize("value", [True, False, None, "0.1", float("nan"), float("inf"), -float("inf"), 10**400, 1e308, [], {}])
def test_geometry_rejects_non_numbers_and_unsafe_numeric_range(site, value):
    site["nodes"][0]["invert_m"] = value
    assert not site_data.validate_site_package(site)["valid"]


@pytest.mark.parametrize("payload", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '{"a":1e999}', '[]', 'null', b'\xff', '{', 4])
def test_strict_json(payload):
    result = site_data.validate_site_package(payload)
    assert not result["valid"] and "invalid_json" in codes(result)


def test_deeply_nested_and_oversize_json_return_structured_error():
    for payload in ('{"x":' * 1500 + '0' + '}' * 1500, '{"x":"' + 'x' * site_data.MAX_JSON_BYTES + '"}'):
        assert "invalid_json" in codes(site_data.validate_site_package(payload))


@pytest.mark.parametrize("field,value", [("schema_version", "monsoon.site/2"), ("contract_status", "approved"), ("vertical_datum", None), ("site_id", []), ("revision", {}), ("created_at", "2026-10-15T08:00:00")])
def test_top_level_identity_datum_and_version_are_strict(site, field, value):
    site[field] = value
    assert not site_data.validate_site_package(site)["valid"]


def test_unknown_and_missing_fields_are_not_silently_accepted(site):
    site["magic_capacity_multiplier"] = 4
    del site["vertical_datum"]
    result = site_data.validate_site_package(site)
    assert {"unknown_field", "missing_field", "text_required"} <= codes(result)


def test_units_and_horizontal_coordinates_require_metre_definition(site):
    site["units"]["flow"] = "L/s"
    site["crs"]["horizontal_unit"] = "degrees"
    assert {"si_units_required", "unsupported_value"} <= codes(site_data.validate_site_package(site))


def test_duplicate_connectivity_and_missing_outfall_rejected(site):
    site["nodes"].append(copy.deepcopy(site["nodes"][0]))
    site["links"][1]["from_node"] = "MISSING"
    result = site_data.validate_site_package(site)
    assert {"duplicate_id", "unknown_node", "no_outfall_path", "disconnected_network"} <= codes(result)


@pytest.mark.parametrize("target", ["endpoint", "source", "asset", "shape", "boundary", "prerequisite"])
def test_nonhashable_references_fail_without_exception(site, target):
    if target == "endpoint":
        site["links"][0]["to_node"] = {"bad": []}
    elif target == "source":
        site["nodes"][0]["survey_source_id"] = []
    elif target == "asset":
        site["jobs"][0]["asset_id"] = []
    elif target == "shape":
        site["links"][0]["cross_section"]["shape"] = {}
    elif target == "boundary":
        site["boundaries"]["outfall_node_ids"] = [{}]
    else:
        site["jobs"][0]["prerequisites"] = [[]]
    assert not site_data.validate_site_package(site)["valid"]


def test_ground_invert_and_storage_curve_consistency(site):
    site["nodes"][0]["ground_m"] = 0.01
    site["nodes"][1]["storage_stage_area"][1]["stage_m"] = 0.02
    result = site_data.validate_site_package(site)
    assert {"invalid_elevations", "storage_stage_order", "storage_extent", "invert_outside_node"} <= codes(result)


def test_storage_curve_cannot_infer_unmeasured_bottom_volume(site):
    site["nodes"][1]["storage_stage_area"][0]["stage_m"] = 0.03
    assert "storage_origin" in codes(site_data.validate_site_package(site))


def test_intervention_requires_approved_evidenced_current_geometry(site):
    site["jobs"][0]["before_cross_section"]["width_m"] = 0.07
    site["jobs"][0]["approval"]["approved"] = False
    site["jobs"][0]["after_source_id"] = None
    assert {"before_state_mismatch", "unapproved_intervention", "missing_source"} <= codes(site_data.validate_site_package(site))


def test_designed_storage_outlet_cannot_become_discretionary_restoration(site):
    site["jobs"][0]["asset_id"] = "L2"
    site["jobs"][0]["before_cross_section"] = copy.deepcopy(site["links"][1]["cross_section"])
    assert "designed_outlet_change" in codes(site_data.validate_site_package(site))


def test_overlapping_jobs_and_cycles_are_not_accepted(site):
    another = copy.deepcopy(site["jobs"][0])
    another["id"], another["prerequisites"] = "J2", ["J1"]
    site["jobs"][0]["prerequisites"] = ["J2"]
    site["jobs"].append(another)
    assert {"overlapping_intervention", "prerequisite_cycle"} <= codes(site_data.validate_site_package(site))


def test_synthetic_relabel_is_not_survey_validation(site):
    site["evidence_kind"] = "supplied_survey"
    report = site_data.validate_site_package(site)
    assert "mixed_evidence" in codes(report)
    assert not report["physical_validation_established"]


def test_file_reference_is_inert_and_never_fetches_uri(site):
    site["sources"][0]["uri"] = "https://invalid.example/survey"
    report = site_data.validate_site_package(site)
    assert report["valid"]
    assert any(w["code"] == "provenance_unverified" for w in report["warnings"])


def test_invalid_parsed_draft_can_be_saved_but_not_activated(site, tmp_path):
    site["nodes"][0]["invert_m"] = None
    result = site_data.stage_site_package(site, tmp_path)
    assert not result["valid"] and result["status"] == "draft_invalid"
    assert Path(result["saved_paths"]["package"]).is_file()
    assert not result["operational_activation_allowed"]
    assert site_data.content_sha256(json.loads(Path(result["saved_paths"]["package"]).read_text())) == result["package_sha256"]
    assert "saved_paths" not in site_data.stage_site_package('{', tmp_path)


def test_stage_snapshots_before_validation_even_if_caller_mutates(site, tmp_path, monkeypatch):
    original_validate = site_data.validate_site_package
    original_hash = site_data.content_sha256(site)
    def mutate_caller(snapshot):
        site["nodes"][0]["x_m"] = 999
        return original_validate(snapshot)
    monkeypatch.setattr(site_data, "validate_site_package", mutate_caller)
    report = site_data.stage_site_package(site, tmp_path)
    assert report["package_sha256"] == original_hash
    saved = json.loads(Path(report["saved_paths"]["package"]).read_text())
    assert site_data.content_sha256(saved) == original_hash


def test_version_diff_identifies_change_and_lineage(site):
    revised = copy.deepcopy(site)
    revised["revision"] = "r2"
    revised["supersedes_sha256"] = site_data.content_sha256(site)
    revised["links"][0]["length_m"] = 1.1
    result = site_data.compare_site_versions(site, revised)
    assert not result["errors"]
    assert any(r["path"] == "$.links.L1.length_m" and "1.1" in r["summary"] for r in result["changes"])
    assert result["review_required"] and not result["operational_activation_allowed"]
    revised["supersedes_sha256"] = None
    assert "lineage_mismatch" in codes(site_data.compare_site_versions(site, revised))
