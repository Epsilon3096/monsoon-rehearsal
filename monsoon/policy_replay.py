"""Strict replay of the recorded v0.3 study, without changing its frozen runner.

This adapter accepts only an exact recorded policy and its matching exact event.
It is not an entry point for new policy selection, sites, or evaluation studies.
Local hashes establish record identity, not independent attestation or field
authority. All binding checks finish before the hydraulic callback is reachable.
"""
from __future__ import annotations

from pathlib import Path

from . import planning
from .hydraulics import engine_info
from .observed_policy import (
    ROOT, fingerprint, replay_observed_policy as _replay,
    source_fingerprints, validate_protocol,
)
from .site_data import parse_json

PROTOCOL_SHA256 = "932dca0d0dae352ea7b3b863c796670cc1bfd9c18025fc8bfe60d81b5481fba2"
FREEZE_SHA256 = "411ce36a77f88cdd4b22335617aa7b941973b3c2a7bc7393330fe94925911e03"
RECORDED_POLICIES_SHA256 = "be97da4d0bf25de9012ac31b077841157e2687d299307da0c1d33ffc4c98e749"
_PROTOCOL_PATH = ROOT / "data/policy_v3_protocol.json"
_FREEZE_PATH = ROOT / "evidence/v0.3/policy-freeze.json"
_DEVELOPMENT_PATH = ROOT / "evidence/v0.3/policy-development.json"


def _load_study():
    """Read each record once and check the original local study identities."""
    try:
        protocol = parse_json(Path(_PROTOCOL_PATH).read_bytes())
        freeze = parse_json(Path(_FREEZE_PATH).read_bytes())
        development = parse_json(Path(_DEVELOPMENT_PATH).read_bytes())
        validate_protocol(protocol)
        if protocol.get("protocol_sha256") != PROTOCOL_SHA256:
            raise ValueError("Protocol is not the recorded v0.3 study.")
        if freeze.get("freeze_sha256") != FREEZE_SHA256 or fingerprint({k: v for k, v in freeze.items() if k != "freeze_sha256"}) != FREEZE_SHA256:
            raise ValueError("Implementation freeze identity differs from the recorded study.")
        if freeze.get("protocol_sha256") != PROTOCOL_SHA256 or freeze.get("source_sha256") != source_fingerprints():
            raise ValueError("Frozen source or protocol differs from the recorded study.")
        if freeze.get("engine") != engine_info():
            raise ValueError("Engine differs from the recorded implementation freeze.")
        if development.get("freeze_sha256") != FREEZE_SHA256 or development.get("protocol_sha256") != PROTOCOL_SHA256:
            raise ValueError("Recorded policy lineage differs from the study freeze.")
        if fingerprint(development.get("policies")) != RECORDED_POLICIES_SHA256:
            raise ValueError("Recorded policy identities were changed.")
        return protocol, freeze, development["policies"]
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ValueError(f"Recorded-study binding failed: {exc}") from exc


def replay_frozen_event(snapshot: dict, case: dict, evaluation_event: dict, hydraulic_fn) -> dict:
    """Replay one exact recorded event with its exact matching policy snapshot.

    Inputs are snapshotted once. Missing/altered records, changed source/engine,
    unlisted or edited events, mismatched observations, edited policies and a
    different case raise ValueError before the frozen replay or callback runs.
    The return value is the unchanged frozen runner's original result.
    """
    try:
        policy, supplied_case, event = (parse_json(value) for value in (snapshot, case, evaluation_event))
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ValueError(f"Replay inputs must be finite JSON objects: {exc}") from exc
    if not callable(hydraulic_fn):
        raise ValueError("A hydraulic callback is required for a recorded replay.")
    protocol, freeze, recorded = _load_study()
    event_id = event.get("id")
    expected = [value for value in protocol["evaluation_events"] if value.get("id") == event_id]
    if len(expected) != 1 or fingerprint(event) != fingerprint(expected[0]):
        raise ValueError("Event is not an exact canonical member of the recorded frozen protocol.")
    observation = policy.get("observation")
    observation_id = observation.get("id") if isinstance(observation, dict) else None
    if not isinstance(observation_id, str) or observation_id != event.get("observation_id"):
        raise ValueError("Event observation_id does not match the supplied frozen policy observation.")
    expected_policy = recorded.get(observation_id)
    if expected_policy is None or fingerprint(policy) != fingerprint(expected_policy):
        raise ValueError("Policy snapshot is not the exact recorded policy for this observation.")
    if policy.get("snapshot_sha256") != fingerprint({k: v for k, v in policy.items() if k != "snapshot_sha256"}):
        raise ValueError("Recorded policy snapshot hash is invalid.")
    if policy.get("protocol_sha256") != PROTOCOL_SHA256 or policy.get("source_sha256") != freeze["source_sha256"]:
        raise ValueError("Policy source/protocol binding differs from the recorded freeze.")
    try:
        case_identity = fingerprint(planning._case_snapshot(supplied_case))
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise ValueError(f"Supplied case cannot match the recorded policy: {exc}") from exc
    if policy.get("case_sha256") != case_identity:
        raise ValueError("Supplied case differs from the recorded policy case.")
    return _replay(policy, supplied_case, event, hydraulic_fn, protocol)
