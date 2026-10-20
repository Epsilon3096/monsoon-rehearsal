"""Strict, inert site-data staging. This module never creates an active model.

Schema validity is a statement about a supplied file, not its truth, engineering
adequacy, owner acceptance, physical validation, or permission to dispatch work.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = "monsoon.site/1"
MAX_JSON_BYTES = 5 * 1024 * 1024
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
SI_UNITS = {"length": "m", "area": "m2", "volume": "m3", "flow": "m3/s", "time": "s", "roughness": "s/m^(1/3)"}


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def content_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_json(payload: dict | str | bytes) -> dict:
    """Reject duplicate keys and non-JSON numerics; never read paths or URLs."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def bad_constant(value):
        raise ValueError(f"Non-finite JSON number: {value}")

    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        if len(payload.encode("utf-8")) > MAX_JSON_BYTES:
            raise ValueError("JSON exceeds the 5 MiB staging limit.")
        value = json.loads(payload, object_pairs_hook=pairs, parse_constant=bad_constant)
    elif isinstance(payload, dict):
        value = copy.deepcopy(payload)
    else:
        raise ValueError("Expected a JSON object, UTF-8 bytes, or JSON text.")
    if not isinstance(value, dict):
        raise ValueError("The top-level JSON value must be an object.")
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 64:
            raise ValueError("JSON exceeds the 64-level nesting limit.")
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("JSON object keys must be strings.")
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    encoded = canonical_json(value)
    if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("JSON exceeds the 5 MiB staging limit.")
    return value


def timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo is not None and result.utcoffset() is not None else None
    except ValueError:
        return None


class _Checks:
    def __init__(self):
        self.errors: list[dict] = []
        self.warnings: list[dict] = []

    def error(self, path, code, message):
        self.errors.append({"path": path, "code": code, "message": message})

    def warn(self, path, code, message):
        self.warnings.append({"path": path, "code": code, "message": message})

    def obj(self, value, path, keys):
        if not isinstance(value, dict):
            self.error(path, "object_required", "Expected an object; unknown values cannot be inferred.")
            return {}
        for key in sorted(set(keys) - value.keys()):
            self.error(f"{path}.{key}", "missing_field", "Required field is missing.")
        for key in sorted(value.keys() - set(keys)):
            self.error(f"{path}.{key}", "unknown_field", "Unknown field for this schema version.")
        return value

    def array(self, value, path, minimum=0):
        if not isinstance(value, list):
            self.error(path, "array_required", "Expected an array.")
            return []
        if len(value) < minimum:
            self.error(path, "insufficient_items", f"At least {minimum} item(s) required.")
        return value

    def text(self, value, path):
        if not isinstance(value, str) or not value.strip():
            self.error(path, "text_required", "Nonempty text is required; unknown is not a value.")
            return False
        return True

    def ident(self, value, path):
        if not isinstance(value, str) or not ID_RE.fullmatch(value):
            self.error(path, "invalid_id", "Use a stable ID: initial letter, then at most 63 letters, digits, _, ., :, or -.")
            return False
        return True

    def number(self, value, path, minimum=None, positive=False):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self.error(path, "finite_number_required", "A finite JSON number is required; null means unknown and blocks readiness.")
            return False
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite or abs(value) > 1e12 or (minimum is not None and value < minimum) or (positive and value <= 0):
            self.error(path, "invalid_number", "Number is non-finite or outside the allowed range (absolute software limit: 1e12 SI units).")
            return False
        return True

    def when(self, value, path):
        parsed = timestamp(value)
        if parsed is None:
            self.error(path, "timezone_required", "Use an ISO-8601 timestamp with an explicit UTC offset or Z.")
        return parsed

    def choice(self, value, choices, path):
        if not isinstance(value, str) or value not in choices:
            self.error(path, "unsupported_value", f"Expected one of: {', '.join(sorted(choices))}.")

    def sha(self, value, path):
        if not isinstance(value, str) or not SHA_RE.fullmatch(value):
            self.error(path, "sha256_required", "Expected 64 lowercase hexadecimal SHA-256 characters.")


def _records(checks, value, path, minimum=0):
    rows = checks.array(value, path, minimum)
    result = {}
    for i, row in enumerate(rows):
        p = f"{path}[{i}]"
        if not isinstance(row, dict):
            checks.error(p, "object_required", "Each record must be an object.")
            continue
        key = row.get("id")
        if checks.ident(key, f"{p}.id"):
            if key in result:
                checks.error(f"{p}.id", "duplicate_id", f"Duplicate ID {key}.")
            else:
                result[key] = row
    return result


def _section(checks, value, path):
    if not isinstance(value, dict):
        checks.error(path, "cross_section_required", "Measured cross-section geometry is required.")
        return
    shape = value.get("shape")
    fields = {"open_rectangle": {"shape", "width_m", "height_m"},
              "circular": {"shape", "diameter_m"},
              "trapezoid": {"shape", "bottom_width_m", "height_m", "left_slope_h_per_v", "right_slope_h_per_v"}}
    if not isinstance(shape, str) or shape not in fields:
        checks.error(f"{path}.shape", "unsupported_cross_section", "v1 supports open_rectangle, circular, and trapezoid only; other shapes remain draft.")
        return
    checks.obj(value, path, fields[shape])
    for key in fields[shape] - {"shape"}:
        checks.number(value.get(key), f"{path}.{key}", minimum=0, positive="slope" not in key)


def _base_report():
    return {"schema_version": SCHEMA_VERSION, "valid": False, "status": "draft_invalid",
            "contract_status": "draft_pending_operator_acceptance", "evidence_kind": None,
            "package_sha256": None, "operational_activation_allowed": False,
            "physical_validation_established": False, "errors": [], "warnings": []}


def validate_site_package(payload: dict | str | bytes) -> dict:
    """Validate the bounded surveyed-network/job contract without activating it."""
    report = _base_report()
    c = _Checks()
    try:
        package = parse_json(payload)
        report["package_sha256"] = content_sha256(package)
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as exc:
        c.error("$", "invalid_json", str(exc))
        report["errors"] = c.errors
        return report
    p = c.obj(package, "$", {"schema_version", "site_id", "revision", "supersedes_sha256", "title", "evidence_kind", "contract_status", "created_at", "crs", "vertical_datum", "units", "sources", "nodes", "links", "jobs", "boundaries", "notes"})
    c.choice(p.get("schema_version"), {SCHEMA_VERSION}, "$.schema_version")
    c.ident(p.get("site_id"), "$.site_id")
    c.ident(p.get("revision"), "$.revision")
    if p.get("supersedes_sha256") is not None:
        c.sha(p.get("supersedes_sha256"), "$.supersedes_sha256")
    c.text(p.get("title"), "$.title")
    c.text(p.get("notes"), "$.notes")
    c.choice(p.get("evidence_kind"), {"synthetic_fixture", "supplied_survey"}, "$.evidence_kind")
    report["evidence_kind"] = p.get("evidence_kind")
    c.choice(p.get("contract_status"), {"draft_pending_operator_acceptance"}, "$.contract_status")
    created = c.when(p.get("created_at"), "$.created_at")
    crs = c.obj(p.get("crs"), "$.crs", {"identifier", "definition", "axis_order", "horizontal_unit"})
    c.text(crs.get("identifier"), "$.crs.identifier")
    c.text(crs.get("definition"), "$.crs.definition")
    c.choice(crs.get("axis_order"), {"easting_northing"}, "$.crs.axis_order")
    c.choice(crs.get("horizontal_unit"), {"m"}, "$.crs.horizontal_unit")
    c.text(p.get("vertical_datum"), "$.vertical_datum")
    if p.get("units") != SI_UNITS:
        c.error("$.units", "si_units_required", f"Units must equal {SI_UNITS}; conversions are never guessed.")
    sources = _records(c, p.get("sources"), "$.sources", 1)
    for key, row in sources.items():
        q = f"$.sources[{key}]"
        c.obj(row, q, {"id", "kind", "uri", "sha256", "observed_at", "author", "description"})
        c.choice(row.get("kind"), {"synthetic_fixture", "survey", "inspection", "engineering_approval"}, f"{q}.kind")
        for field in ("uri", "author", "description"):
            c.text(row.get(field), f"{q}.{field}")
        c.sha(row.get("sha256"), f"{q}.sha256")
        observed = c.when(row.get("observed_at"), f"{q}.observed_at")
        if created and observed and observed > created:
            c.error(q, "future_source", "Source observation is after package creation.")
        if p.get("evidence_kind") == "supplied_survey" and row.get("kind") == "synthetic_fixture":
            c.error(q, "mixed_evidence", "A supplied-survey package cannot reuse synthetic source evidence.")
        if p.get("evidence_kind") == "synthetic_fixture" and row.get("kind") != "synthetic_fixture":
            c.error(q, "fixture_source_label", "Every source in a synthetic fixture must be labelled synthetic_fixture.")

    def source_ref(value, path, kinds=None):
        if not isinstance(value, str) or value not in sources:
            c.error(path, "missing_source", "Reference an existing source ID.")
        elif kinds and p.get("evidence_kind") != "synthetic_fixture" and sources[value].get("kind") not in kinds:
            c.error(path, "wrong_source_kind", "Source kind does not support this claim.")

    nodes = _records(c, p.get("nodes"), "$.nodes", 2)
    links = _records(c, p.get("links"), "$.links", 1)
    jobs = _records(c, p.get("jobs"), "$.jobs")
    for key, n in nodes.items():
        q = f"$.nodes[{key}]"
        c.obj(n, q, {"id", "kind", "x_m", "y_m", "invert_m", "ground_m", "survey_source_id", "storage_stage_area", "designed_outlet_link_id"})
        c.choice(n.get("kind"), {"junction", "storage", "outfall"}, f"{q}.kind")
        nums = {f: c.number(n.get(f), f"{q}.{f}") for f in ("x_m", "y_m", "invert_m", "ground_m")}
        if nums["invert_m"] and nums["ground_m"] and n["ground_m"] <= n["invert_m"]:
            c.error(q, "invalid_elevations", "Ground level must exceed invert level in the same vertical datum.")
        source_ref(n.get("survey_source_id"), f"{q}.survey_source_id", {"survey"})
        if n.get("kind") == "storage":
            curve = c.array(n.get("storage_stage_area"), f"{q}.storage_stage_area", 2)
            previous = None
            for j, point in enumerate(curve):
                r = f"{q}.storage_stage_area[{j}]"
                point = c.obj(point, r, {"stage_m", "area_m2"})
                good = c.number(point.get("stage_m"), f"{r}.stage_m")
                c.number(point.get("area_m2"), f"{r}.area_m2", positive=True)
                if good:
                    if previous is not None and point["stage_m"] <= previous:
                        c.error(r, "storage_stage_order", "Storage stages must increase strictly.")
                    if nums["invert_m"] and point["stage_m"] < n["invert_m"]:
                        c.error(r, "storage_below_invert", "Storage curve lies below the surveyed invert.")
                    previous = point["stage_m"]
            if curve and isinstance(curve[0], dict) and nums["invert_m"] and curve[0].get("stage_m") != n["invert_m"]:
                c.error(q, "storage_origin", "First storage stage must equal invert; no unobserved lower volume is inferred.")
            if curve and isinstance(curve[-1], dict) and nums["ground_m"] and isinstance(curve[-1].get("stage_m"), (int, float)) and curve[-1]["stage_m"] < n["ground_m"]:
                c.error(q, "storage_extent", "Storage curve must cover the declared ground/overflow level.")
            outlet = n.get("designed_outlet_link_id")
            if not isinstance(outlet, str) or outlet not in links or links[outlet].get("from_node") != key:
                c.error(q, "designed_outlet", "Storage requires an identified outgoing designed outlet link.")
        elif n.get("storage_stage_area") is not None or n.get("designed_outlet_link_id") is not None:
            c.error(q, "storage_fields", "Non-storage nodes must have null storage curve and outlet fields.")
    graph = {key: set() for key in nodes}
    reverse = {key: set() for key in nodes}
    for key, link in links.items():
        q = f"$.links[{key}]"
        c.obj(link, q, {"id", "from_node", "to_node", "length_m", "inlet_invert_m", "outlet_invert_m", "roughness_n", "cross_section", "survey_source_id"})
        for field in ("from_node", "to_node"):
            if not isinstance(link.get(field), str) or link.get(field) not in nodes:
                c.error(f"{q}.{field}", "unknown_node", "Link endpoint must name an existing node.")
        a, b = link.get("from_node"), link.get("to_node")
        if isinstance(a, str) and isinstance(b, str) and a in nodes and b in nodes:
            if a == b:
                c.error(q, "self_link", "A link cannot connect a node to itself.")
            graph[a].add(b)
            graph[b].add(a)
            reverse[b].add(a)
        c.number(link.get("length_m"), f"{q}.length_m", positive=True)
        c.number(link.get("roughness_n"), f"{q}.roughness_n", positive=True)
        for field, endpoint in (("inlet_invert_m", a), ("outlet_invert_m", b)):
            good = c.number(link.get(field), f"{q}.{field}")
            node = nodes.get(endpoint, {}) if isinstance(endpoint, str) else {}
            ni, ng = node.get("invert_m"), node.get("ground_m")
            if good and type(ni) in (int, float) and type(ng) in (int, float) and not ni <= link[field] < ng:
                c.error(f"{q}.{field}", "invert_outside_node", "Link invert must be at or above node invert and below ground in the same datum.")
        _section(c, link.get("cross_section"), f"{q}.cross_section")
        source_ref(link.get("survey_source_id"), f"{q}.survey_source_id", {"survey"})
    outfalls = {key for key, row in nodes.items() if row.get("kind") == "outfall"}
    if not outfalls:
        c.error("$.nodes", "no_outfall", "At least one explicit receiving-water outfall is required.")
    reached = set(outfalls)
    pending = list(outfalls)
    while pending:
        for upstream in reverse[pending.pop()] - reached:
            reached.add(upstream)
            pending.append(upstream)
    for key in sorted(nodes.keys() - reached):
        c.error(f"$.nodes[{key}]", "no_outfall_path", "No declared downstream path reaches an outfall.")
    if graph:
        reached = set()
        pending = [next(iter(graph))]
        while pending:
            key = pending.pop()
            if key not in reached:
                reached.add(key)
                pending.extend(graph[key] - reached)
        if reached != set(nodes):
            c.error("$.links", "disconnected_network", "v1 requires one connected bounded network.")
    boundaries = c.obj(p.get("boundaries"), "$.boundaries", {"inflow_node_ids", "outfall_node_ids", "spill_node_ids", "inventory_source_id"})
    for field in ("inflow_node_ids", "outfall_node_ids", "spill_node_ids"):
        values = c.array(boundaries.get(field), f"$.boundaries.{field}", 1)
        if any(not isinstance(v, str) or v not in nodes for v in values):
            c.error(f"$.boundaries.{field}", "unknown_node", "Boundary IDs must reference nodes.")
        if all(isinstance(v, str) for v in values) and len(set(values)) != len(values):
            c.error(f"$.boundaries.{field}", "duplicate_id", "Boundary IDs must be unique.")
    declared_outfalls = boundaries.get("outfall_node_ids")
    if isinstance(declared_outfalls, list) and all(isinstance(v, str) for v in declared_outfalls) and set(declared_outfalls) != outfalls:
        c.error("$.boundaries.outfall_node_ids", "outfall_inventory", "Boundary outfalls must equal all outfall nodes.")
    source_ref(boundaries.get("inventory_source_id"), "$.boundaries.inventory_source_id", {"survey"})
    targeted = set()
    for key, job in jobs.items():
        q = f"$.jobs[{key}]"
        c.obj(job, q, {"id", "title", "asset_id", "before_cross_section", "after_cross_section", "before_source_id", "after_source_id", "approval", "nominal_seconds", "maximum_seconds", "prerequisites"})
        c.text(job.get("title"), f"{q}.title")
        asset = job.get("asset_id")
        if not isinstance(asset, str) or asset not in links:
            c.error(f"{q}.asset_id", "unknown_asset", "Jobs may reference surveyed links only in v1.")
        else:
            if asset in targeted:
                c.error(f"{q}.asset_id", "overlapping_intervention", "v1 permits one intervention per physical link.")
            targeted.add(asset)
            if job.get("before_cross_section") != links[asset].get("cross_section"):
                c.error(q, "before_state_mismatch", "Before geometry must equal the surveyed current link geometry.")
            if any(n.get("designed_outlet_link_id") == asset for n in nodes.values()):
                c.error(q, "designed_outlet_change", "Designed storage-outlet changes require a separate engineering design; v1 maintenance import excludes them.")
        _section(c, job.get("before_cross_section"), f"{q}.before_cross_section")
        _section(c, job.get("after_cross_section"), f"{q}.after_cross_section")
        if job.get("before_cross_section") == job.get("after_cross_section"):
            c.error(q, "no_geometry_change", "An intervention must declare a measured, approved geometry change.")
        source_ref(job.get("before_source_id"), f"{q}.before_source_id", {"survey", "inspection"})
        source_ref(job.get("after_source_id"), f"{q}.after_source_id", {"survey", "inspection", "engineering_approval"})
        approval = c.obj(job.get("approval"), f"{q}.approval", {"approved", "reviewer", "reviewed_at", "source_id"})
        if approval.get("approved") is not True:
            c.error(f"{q}.approval.approved", "unapproved_intervention", "Before/after geometry requires explicit engineering approval; a draft is not authorisation.")
        c.text(approval.get("reviewer"), f"{q}.approval.reviewer")
        approved_at = c.when(approval.get("reviewed_at"), f"{q}.approval.reviewed_at")
        if created and approved_at and approved_at > created:
            c.error(q, "future_approval", "Approval cannot be after package creation.")
        source_ref(approval.get("source_id"), f"{q}.approval.source_id", {"engineering_approval"})
        nominal = c.number(job.get("nominal_seconds"), f"{q}.nominal_seconds", positive=True)
        maximum = c.number(job.get("maximum_seconds"), f"{q}.maximum_seconds", positive=True)
        if nominal and maximum and job["nominal_seconds"] > job["maximum_seconds"]:
            c.error(q, "duration_bounds", "Nominal on-site duration cannot exceed its complete-occupation upper bound.")
        prereqs = c.array(job.get("prerequisites"), f"{q}.prerequisites")
        if any(not isinstance(v, str) or v not in jobs or v == key for v in prereqs):
            c.error(q, "invalid_prerequisite", "Prerequisites must name other existing jobs.")
        if all(isinstance(v, str) for v in prereqs) and len(prereqs) != len(set(prereqs)):
            c.error(q, "duplicate_prerequisite", "Prerequisite IDs must be unique.")
    # Kahn traversal avoids recursion on an uploaded prerequisite graph.
    remaining = {key: {v for v in row.get("prerequisites", []) if isinstance(v, str) and v in jobs}
                 for key, row in jobs.items() if isinstance(row.get("prerequisites"), list)}
    while remaining:
        ready = {key for key, deps in remaining.items() if not deps}
        if not ready:
            c.error("$.jobs", "prerequisite_cycle", "Job prerequisite graph contains a cycle.")
            break
        remaining = {key: deps - ready for key, deps in remaining.items() if key not in ready}
    c.warn("$", "staging_only", "Draft contract pending operator acceptance. Import cannot activate an engine model or authorise work.")
    c.warn("$.sources", "provenance_unverified", "Source references and checksums are declarations; source bytes, survey truth and reviewer authority are not verified by this importer.")
    if p.get("evidence_kind") == "synthetic_fixture":
        c.warn("$", "synthetic_only", "Synthetic fixture only; no surveyed site, real approval, or physical validation is established.")
    report.update(valid=not c.errors, status="ready_for_review" if not c.errors else "draft_invalid", errors=c.errors, warnings=c.warnings,
                  counts={"nodes": len(nodes), "links": len(links), "jobs": len(jobs), "sources": len(sources)})
    return report


def stage_site_package(payload: dict | str | bytes, staging_dir: str | Path) -> dict:
    """Save a canonical content-addressed draft, including invalid parsed files."""
    try:
        package = parse_json(payload)
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        return validate_site_package(payload)
    report = validate_site_package(package)
    if not report["package_sha256"]:
        return report
    destination = Path(staging_dir).resolve() / report["package_sha256"]
    destination.mkdir(parents=True, exist_ok=True)
    package_path, report_path = destination / "site.json", destination / "validation.json"
    package_path.write_text(json.dumps(package, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return {**report, "saved_paths": {"package": str(package_path), "validation": str(report_path)}}


def compare_site_versions(old: dict | str | bytes, new: dict | str | bytes) -> dict:
    """Describe every supplied-field change; no change is auto-accepted."""
    before, after = validate_site_package(old), validate_site_package(new)
    report = {"old_sha256": before["package_sha256"], "new_sha256": after["package_sha256"],
              "old_valid": before["valid"], "new_valid": after["valid"], "changes": [],
              "operational_activation_allowed": False, "review_required": True}
    if not before["package_sha256"] or not after["package_sha256"]:
        report["errors"] = before["errors"] + after["errors"]
        return report
    a, b = parse_json(old), parse_json(new)
    if a.get("site_id") != b.get("site_id"):
        report["errors"] = [{"path": "$.site_id", "code": "different_site", "message": "Versions identify different sites; comparison is informational only."}]
    else:
        report["errors"] = []
    if b.get("supersedes_sha256") != before["package_sha256"]:
        report["errors"].append({"path": "$.supersedes_sha256", "code": "lineage_mismatch", "message": "New revision does not explicitly supersede the supplied old package hash."})

    def walk(left, right, path):
        if type(left) == type(right) and left == right:
            return
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(left.keys() | right.keys()):
                if key not in left:
                    report["changes"].append({"path": f"{path}.{key}", "kind": "added", "before": None, "after": right[key], "summary": f"Added {path}.{key}."})
                elif key not in right:
                    report["changes"].append({"path": f"{path}.{key}", "kind": "removed", "before": left[key], "after": None, "summary": f"Removed {path}.{key}."})
                else:
                    walk(left[key], right[key], f"{path}.{key}")
        elif isinstance(left, list) and isinstance(right, list) and all(isinstance(x, dict) and isinstance(x.get("id"), str) for x in left + right) and len({x["id"] for x in left}) == len(left) and len({x["id"] for x in right}) == len(right):
            walk({x["id"]: x for x in left}, {x["id"]: x for x in right}, path)
        else:
            report["changes"].append({"path": path, "kind": "changed", "before": left, "after": right, "summary": f"Changed {path}: {canonical_json(left)} → {canonical_json(right)}."})
    walk(a, b, "$")
    report["summary"] = f"{len(report['changes'])} field change(s); human review required. No active model was changed."
    return report
