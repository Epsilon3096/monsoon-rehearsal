"""Adversarial local research workflow tests; all identities/data are fixtures."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

import pytest

from monsoon.operations import (
    AuthenticationError, ConflictError, IntegrityError, OperationsError,
    OperationsStore, PermissionDenied, canonical_sha256, input_snapshot_sha256,
)


PASSWORD = "fixture-only-password-123!"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 14, 10, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds=1):
        self.now += timedelta(seconds=seconds)

    def iso(self):
        return self.now.isoformat()


class Harness:
    def __init__(self, path):
        self.clock = Clock()
        self.path = path
        self.store = OperationsStore(path, clock=self.clock)
        self.store.bootstrap_admin("admin", PASSWORD, "Fixture administrator")
        self.admin = self.store.login("admin", PASSWORD)["token"]
        self.users = {}
        for name, roles in (("dispatch", ["dispatcher"]), ("review", ["reviewer"]),
                            ("observe", ["observer"]), ("inspect", ["inspector"])):
            self.users[name] = self.store.create_user(self.admin, name, PASSWORD, "Fixture " + name, roles)
            setattr(self, name, self.store.login(name, PASSWORD)["token"])

    def site(self, valid=False):
        if valid:
            payload = json.loads((Path(__file__).parents[1] / "data/templates/synthetic_site_v1.json").read_text(encoding="utf-8"))
        else:
            payload = {"evidence_kind": "synthetic_fixture", "fixture_only": True}
        return self.store.stage_site(self.dispatch, payload)

    def attachment(self, text="SYNTHETIC TEST EVIDENCE, not an actual participant or measurement.", observed_at=None):
        return self.store.add_attachment(self.observe, "fixture.txt", text.encode(), "text/plain",
                                         {"source": "automated synthetic fixture"}, observed_at or self.clock.iso())

    def interview(self, site=None):
        site = site or self.site()
        constraints = {"available_crew": "synthetic test crew", "authorised_jobs": [],
                       "access": "fixture only", "restoration_deadline": "fixture only",
                       "stopping_rules": "No physical work", "closeout_evidence": "fixture log"}
        baseline = {"queue": [], "rationale": "No authorised fixture jobs", "no_work_reason": "Synthetic test only"}
        return self.store.create_interview(self.dispatch, site["id"], "Fixture operator", "Synthetic test identity",
                                          "Synthetic decision window", constraints, baseline)

    def inputs(self):
        return [{"id": "initial_level", "source": "synthetic fixture", "observed_at": self.clock.iso(),
                 "issued_at": self.clock.iso(), "available_at": self.clock.iso(), "value": None}]

    def reveal(self, interview=None, inputs=None, generated_at=None):
        interview = interview or self.interview()
        inputs = inputs or self.inputs()
        self.clock.advance()
        model = {"model_id": "fixture-model/1", "policy_id": "fixture-abstain/1",
                 "generated_at": generated_at or self.clock.iso(), "inputs_sha256": input_snapshot_sha256(inputs),
                 "site_package_sha256": interview["data"]["site_package_sha256"],
                 "result": {"decision": "abstain", "queue": [], "reasons": ["Synthetic missing-input test."]}}
        result = self.store.reveal_model(self.dispatch, interview["id"], interview["version"], model)
        return result, inputs

    def shadow(self):
        interview, inputs = self.reveal()
        return self.store.create_shadow(self.dispatch, interview["data"]["site_id"], interview["id"], inputs, protocol())


def protocol():
    return {"protocol_id": "synthetic-shadow-test/1", "objective": "Test records only",
            "stopping_rules": "Never direct real work", "exception_rules": "Keep failures unresolved",
            "outcome_plan": "Later synthetic test assertions, never field claims"}


def observed_data():
    return {"executed_plan": [], "completed_jobs": [], "exceptions": [], "measured_response": None,
            "planning_minutes": None, "crew_minutes": None}


@pytest.fixture
def h(tmp_path):
    harness = Harness(tmp_path / "operations.sqlite3")
    try:
        yield harness
    finally:
        harness.store.close()


def test_bootstrap_credentials_and_sensitive_records_are_not_exposed(h):
    assert not h.store.needs_bootstrap()
    with pytest.raises(PermissionDenied):
        h.store.bootstrap_admin("hijack", PASSWORD, "Not allowed")
    with pytest.raises(AuthenticationError):
        h.store.login("admin", "wrong-password-123")
    with pytest.raises(AuthenticationError):
        h.store.login("not-an-account", PASSWORD)
    with pytest.raises(PermissionDenied):
        h.store.get_record(h.observe, h.users["dispatch"]["id"])
    with pytest.raises(PermissionDenied):
        h.store.list_records(h.observe, kind="session")
    assert h.store.verify_integrity(h.admin)["valid"]
    # Include the WAL: the plaintext token/password must not be persisted there.
    for path in h.path.parent.glob("operations.sqlite3*"):
        raw = path.read_bytes()
        assert PASSWORD.encode() not in raw
        assert h.admin.encode() not in raw


@pytest.mark.parametrize("token", [None, "", "dispatcher", "x" * 44])
def test_unauthenticated_calls_cannot_read_or_write(h, token):
    with pytest.raises(AuthenticationError):
        h.store.list_records(token)
    with pytest.raises(AuthenticationError):
        h.store.stage_site(token, {})
    with pytest.raises(AuthenticationError):
        h.store.create_user(token, "another", PASSWORD, "Unauthorized", ["admin"])


def test_roles_are_enforced_by_methods_and_admin_is_not_dispatcher(h):
    for token in (h.observe, h.review, h.inspect, h.admin):
        with pytest.raises(PermissionDenied):
            h.store.stage_site(token, {})
    with pytest.raises(PermissionDenied):
        h.store.create_user(h.dispatch, "escalate", PASSWORD, "Role escalation", ["admin"])
    with pytest.raises(PermissionDenied):
        h.store.list_users(h.observe)
    with pytest.raises(PermissionDenied):
        h.store.backup(h.observe, h.path.parent / "forbidden.sqlite3")


def test_expiry_logout_disable_and_password_change_revoke(h):
    h.store.logout(h.observe)
    with pytest.raises(AuthenticationError):
        h.store.whoami(h.observe)
    h.store.disable_user(h.admin, h.users["review"]["id"], h.users["review"]["version"])
    with pytest.raises(AuthenticationError):
        h.store.whoami(h.review)
    with pytest.raises(AuthenticationError):
        h.store.login("review", PASSWORD)
    h.store.change_password(h.dispatch, PASSWORD, "different-fixture-password!")
    with pytest.raises(AuthenticationError):
        h.store.whoami(h.dispatch)
    fresh = h.store.login("dispatch", "different-fixture-password!")["token"]
    assert h.store.whoami(fresh)["roles"] == ["dispatcher"]
    h.clock.advance(3601)
    with pytest.raises(AuthenticationError):
        h.store.whoami(fresh)


def test_bootstrap_is_atomic_across_connections(tmp_path):
    first = OperationsStore(tmp_path / "shared.sqlite3")
    second = OperationsStore(tmp_path / "shared.sqlite3")
    def attempt(store, name):
        try:
            store.bootstrap_admin(name, PASSWORD, "Fixture admin")
            return "created"
        except PermissionDenied:
            return "denied"
    try:
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(attempt, first, "first"), pool.submit(attempt, second, "second")]
            assert sorted(f.result() for f in futures) == ["created", "denied"]
    finally:
        first.close()
        second.close()


def test_invalid_site_remains_draft_and_duplicate_json_is_rejected(h):
    site = h.site()
    assert not site["data"]["validation"]["valid"]
    assert not site["data"]["operational_activation_allowed"]
    with pytest.raises(OperationsError):
        h.store.review_site(h.review, site["id"], site["version"], "Cannot review as valid")
    with pytest.raises(OperationsError, match="unique keys"):
        h.store.stage_site(h.dispatch, '{"evidence_kind":"synthetic_fixture","evidence_kind":"supplied_survey"}')
    assert not h.store.readiness(h.observe, site["id"])["pilot_authorised"]


def test_real_site_validator_and_independent_review(h):
    site = h.site(valid=True)
    assert site["data"]["validation"]["valid"]
    h.store.create_user(h.admin, "bothroles", PASSWORD, "Fixture combined roles", ["dispatcher", "reviewer"])
    both = h.store.login("bothroles", PASSWORD)["token"]
    own_site = h.store.stage_site(both, site["data"]["package"])
    with pytest.raises(PermissionDenied, match="different account"):
        h.store.review_site(both, own_site["id"], own_site["version"], "Own review refused")
    reviewed = h.store.review_site(h.review, site["id"], site["version"], "Contract shape only")
    assert reviewed["data"]["status"] == "reviewed_for_research"
    assert not reviewed["data"]["operational_activation_allowed"]
    with pytest.raises(ConflictError):
        h.store.review_site(h.review, site["id"], site["version"], "Stale review")


def test_baseline_revisions_only_before_disclosure_and_concurrent_writes(h):
    interview = h.interview()
    other = OperationsStore(h.path, clock=h.clock)
    def revise(store, reason):
        baseline = dict(interview["data"]["baseline_plan"], rationale=reason)
        try:
            return store.revise_interview(h.dispatch, interview["id"], interview["version"], interview["data"]["constraints"], baseline, reason)
        except ConflictError:
            return "conflict"
    try:
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(revise, h.store, "Revision A"), pool.submit(revise, other, "Revision B")]
            results = [f.result() for f in futures]
        assert sum(r == "conflict" for r in results) == 1
        current = h.store.get_record(h.dispatch, interview["id"])
        revealed, _ = h.reveal(current)
        with pytest.raises(OperationsError, match="cannot change after"):
            h.store.revise_interview(h.dispatch, revealed["id"], revealed["version"], revealed["data"]["constraints"],
                                     dict(revealed["data"]["baseline_plan"], rationale="Post-reveal tuning"), "Denied")
        assert h.store.verify_integrity(h.admin)["valid"]
    finally:
        other.close()


def test_operator_review_requires_documented_feedback_after_disclosure(h):
    interview = h.interview()
    evidence = h.attachment()
    with pytest.raises(OperationsError):
        h.store.record_interview_review(h.review, interview["id"], interview["version"], "Premature", [evidence["id"]])
    revealed, _ = h.reveal(interview)
    with pytest.raises(OperationsError, match="requires at least one"):
        h.store.record_interview_review(h.review, revealed["id"], revealed["version"], "Unsupported participation claim")
    reviewed = h.store.record_interview_review(h.review, revealed["id"], revealed["version"], "Fixture disagreement retained", [evidence["id"]])
    assert reviewed["data"]["baseline_plan"] == interview["data"]["baseline_plan"]
    assert "not_independently_verified" in reviewed["data"]["operator_review"]["status"]


@pytest.mark.parametrize("field", ["observed_at", "issued_at", "available_at"])
def test_later_available_information_cannot_enter_model_snapshot(h, field):
    interview = h.interview()
    generated = h.clock.iso()
    inputs = h.inputs()
    h.clock.advance(1)
    inputs[0][field] = h.clock.iso()
    # Availability must also be >= issue/observation for the non-target checks.
    inputs[0]["available_at"] = h.clock.iso()
    revealed, inputs = h.reveal(interview, inputs, generated_at=generated)
    with pytest.raises(OperationsError, match="Future-dated|later-issued"):
        h.store.create_shadow(h.dispatch, interview["data"]["site_id"], revealed["id"], inputs, protocol())


def test_future_issued_forecast_cannot_hide_behind_past_availability(h):
    interview = h.interview()
    inputs = h.inputs()
    inputs[0]["issued_at"] = (h.clock.now + timedelta(hours=1)).isoformat()
    inputs[0]["valid_at"] = (h.clock.now + timedelta(hours=3)).isoformat()
    revealed, _ = h.reveal(interview, inputs)
    with pytest.raises(OperationsError):
        h.store.create_shadow(h.dispatch, interview["data"]["site_id"], revealed["id"], inputs, protocol())


def test_forecast_valid_time_can_be_future_but_no_naive_timestamps(h):
    inputs = h.inputs()
    inputs[0]["valid_at"] = (h.clock.now + timedelta(hours=1)).isoformat()
    revealed, _ = h.reveal(inputs=inputs)
    shadow = h.store.create_shadow(h.dispatch, revealed["data"]["site_id"], revealed["id"], inputs, protocol())
    assert shadow["data"]["mode"] == "SHADOW"
    with pytest.raises(OperationsError, match="timezone"):
        h.store.add_attachment(h.observe, "fixture.txt", b"fixture", "text/plain", "fixture", "2026-10-14T10:00:00")


def test_input_fingerprint_and_copies_are_bound(h):
    interview, inputs = h.reveal()
    kwargs = (h.dispatch, interview["data"]["site_id"], interview["id"], inputs, protocol())
    with pytest.raises(OperationsError, match="baseline"):
        h.store.create_shadow(*kwargs, operator_plan={"queue": [], "rationale": "Changed after model", "no_work_reason": "Changed"})
    altered = deepcopy(interview["data"]["model_reveal"]["snapshot"])
    altered["result"]["reasons"] = ["Changed snapshot"]
    with pytest.raises(OperationsError, match="snapshot differs"):
        h.store.create_shadow(*kwargs, model_snapshot=altered)
    altered_inputs = deepcopy(inputs)
    altered_inputs[0]["value"] = 999
    with pytest.raises(OperationsError, match="fingerprint"):
        h.store.create_shadow(h.dispatch, interview["data"]["site_id"], interview["id"], altered_inputs, protocol())
    saved = h.store.create_shadow(*kwargs)
    inputs[0]["value"] = "Caller mutation"
    assert h.store.get_record(h.observe, saved["id"])["data"]["available_inputs"][0]["value"] is None


def test_backfill_future_and_live_transition_are_rejected(h):
    interview, inputs = h.reveal()
    args = (h.dispatch, interview["data"]["site_id"], interview["id"], inputs, protocol())
    for mode in ("LIVE", "PILOT", "SUPERVISED_PILOT", "shadow", True):
        with pytest.raises(OperationsError, match="Only SHADOW"):
            h.store.create_shadow(*args, mode=mode)
    for timestamp in ((h.clock.now - timedelta(minutes=6)).isoformat(), (h.clock.now + timedelta(seconds=1)).isoformat()):
        with pytest.raises(OperationsError, match="Prospective"):
            h.store.create_shadow(*args, decision_at=timestamp)
    shadow = h.store.create_shadow(*args)
    assert not shadow["data"]["pilot_authorised"]
    with pytest.raises(OperationsError, match="already been used"):
        h.store.create_shadow(*args)


def test_empty_recommendation_is_not_a_valid_model_result(h):
    interview = h.interview()
    model = {"model_id": "fixture", "policy_id": "fixture", "generated_at": h.clock.iso(),
             "inputs_sha256": input_snapshot_sha256(h.inputs()),
             "site_package_sha256": interview["data"]["site_package_sha256"],
             "result": {"decision": "recommend", "queue": [], "reasons": []}}
    with pytest.raises(OperationsError, match="non-empty queue"):
        h.store.reveal_model(h.dispatch, interview["id"], interview["version"], model)


def test_outcomes_are_later_separate_immutable_and_missing_is_unresolved(h):
    shadow = h.shadow()
    seal = shadow["data"]["decision_seal_sha256"]
    with pytest.raises(OperationsError, match="after the decision"):
        h.store.record_outcome(h.observe, shadow["id"], shadow["version"], "missing", h.clock.iso(), {}, "Too soon")
    h.clock.advance()
    missing = h.store.record_outcome(h.observe, shadow["id"], shadow["version"], "missing", h.clock.iso(), {}, "Instrument absent")
    assert missing["data"]["status"] == "missing"
    shadow = h.store.get_record(h.observe, shadow["id"])
    assert shadow["data"]["outcome_status"] == "unresolved_missing"
    assert h.store.readiness(h.observe, shadow["data"]["site_id"])["unresolved_shadow_count"] == 1
    evidence = h.attachment()
    h.clock.advance()
    outcome = h.store.record_outcome(h.observe, shadow["id"], shadow["version"], "observed", h.clock.iso(),
                                    observed_data(), "Synthetic automated observation only", [evidence["id"]])
    assert not outcome["data"]["counterfactual_benefit_established"]
    shadow = h.store.get_record(h.observe, shadow["id"])
    assert shadow["data"]["decision_seal_sha256"] == seal
    assert len(shadow["data"]["outcome_ids"]) == 2
    with pytest.raises(OperationsError, match="immutable"):
        h.store.record_outcome(h.observe, shadow["id"], shadow["version"], "error", h.clock.iso(), {}, "Cannot replace")
    readiness = h.store.readiness(h.observe, shadow["data"]["site_id"])
    assert readiness["recorded_observed_status_count"] == 1
    assert readiness["synthetic_fixture_count"] == 1
    assert readiness["reported_measured_count"] == 0
    assert not readiness["pilot_authorised"]


def test_observed_outcome_needs_later_evidence_and_declared_actual_plan(h):
    early_evidence = h.attachment()
    shadow = h.shadow()
    h.clock.advance()
    args = (h.observe, shadow["id"], shadow["version"], "observed", h.clock.iso(), observed_data(), "Fixture")
    with pytest.raises(OperationsError, match="requires at least one"):
        h.store.record_outcome(*args)
    with pytest.raises(OperationsError, match="collected after"):
        h.store.record_outcome(*args, attachment_ids=[early_evidence["id"]])
    evidence = h.attachment()
    bad = observed_data()
    bad["executed_plan"] = None
    with pytest.raises(OperationsError, match="actual executed plan"):
        h.store.record_outcome(h.observe, shadow["id"], shadow["version"], "observed", h.clock.iso(), bad, "Fixture", [evidence["id"]])
    earlier_outcome_time = h.clock.iso()
    h.clock.advance()
    later_evidence = h.attachment()
    with pytest.raises(OperationsError, match="postdate"):
        h.store.record_outcome(h.observe, shadow["id"], shadow["version"], "observed", earlier_outcome_time,
                               observed_data(), "Fixture", [later_evidence["id"]])


def test_empty_operating_values_remain_unknown_but_empty_authorised_set_is_known(h):
    record = h.interview()
    constraints = dict(record["data"]["constraints"], access="   ", stopping_rules={}, available_crew=[])
    revised = h.store.revise_interview(h.dispatch, record["id"], record["version"], constraints,
                                       record["data"]["baseline_plan"], "Explicit missing observations")
    assert revised["data"]["constraints"]["access"] is None
    assert revised["data"]["constraints"]["stopping_rules"] is None
    assert revised["data"]["constraints"]["available_crew"] is None
    assert revised["data"]["constraints"]["authorised_jobs"] == []


@pytest.mark.parametrize("value", [-1, True, float("nan"), float("inf"), "unknown"])
def test_outcome_duration_must_be_nonnegative_finite_or_null(h, value):
    shadow = h.shadow()
    h.clock.advance()
    evidence = h.attachment()
    observations = observed_data()
    observations["crew_minutes"] = value
    with pytest.raises(OperationsError):
        h.store.record_outcome(h.observe, shadow["id"], shadow["version"], "observed", h.clock.iso(), observations,
                               "Fixture", [evidence["id"]])


def test_unplanned_actual_work_needs_recorded_exception(h):
    shadow = h.shadow()
    h.clock.advance()
    evidence = h.attachment()
    actual = dict(observed_data(), executed_plan=["UNPLANNED"], completed_jobs=["UNPLANNED"])
    args = (h.observe, shadow["id"], shadow["version"], "observed", h.clock.iso())
    with pytest.raises(OperationsError, match="unplanned_job exception"):
        h.store.record_outcome(*args, actual, "Fixture", [evidence["id"]])
    actual["exceptions"] = [{"type": "unplanned_job", "job_id": "UNPLANNED", "reason": "Synthetic exception test"}]
    saved = h.store.record_outcome(*args, actual, "Fixture only", [evidence["id"]])
    assert saved["data"]["observations"]["executed_plan"] == ["UNPLANNED"]


@pytest.mark.parametrize("filename", ["../evil.txt", "..\\evil.txt", "C:\\temp\\evil.txt", "/evil.txt", "evil.txt:stream", "CON.txt", "evil.html", "evil.svg", "evil.exe", "trailing.txt."])
def test_attachment_paths_and_executable_types_are_rejected(h, filename):
    with pytest.raises(OperationsError):
        h.store.add_attachment(h.observe, filename, b"fixture", "text/plain", "Synthetic fixture", h.clock.iso())


def test_attachment_type_size_and_structured_id_checks(h):
    for filename, content, media in (("bad.png", b"not a png", "image/png"), ("bad.txt", b"\xff", "text/plain"),
                                    ("bad.json", b'{"x": NaN}', "application/json"), ("empty.txt", b"", "text/plain"),
                                    ("huge.txt", b"x" * (5 * 1024 * 1024 + 1), "text/plain")):
        with pytest.raises(OperationsError):
            h.store.add_attachment(h.observe, filename, content, media, "Fixture", h.clock.iso())
    with pytest.raises(OperationsError):
        h.store.stage_site(h.dispatch, {}, attachment_ids=[{}])
    with pytest.raises(OperationsError):
        h.store.stage_site(h.dispatch, {}, attachment_ids=["missing"])


def test_records_and_events_have_sql_immutability_and_tamper_detection(h):
    site = h.site()
    with pytest.raises(sqlite3.IntegrityError):
        h.store._db.execute("UPDATE records SET payload_json='{}' WHERE id=?", (site["id"],))
    with pytest.raises(sqlite3.IntegrityError):
        h.store._db.execute("DELETE FROM events")
    trigger_sql = h.store._db.execute("SELECT sql FROM sqlite_master WHERE name='records_no_update'").fetchone()[0]
    h.store._db.execute("DROP TRIGGER records_no_update")
    h.store._db.execute("UPDATE records SET payload_json='{}' WHERE id=?", (site["id"],))
    h.store._db.execute(trigger_sql)
    with pytest.raises(IntegrityError):
        h.store.get_record(h.observe, site["id"])
    with pytest.raises(IntegrityError):
        h.store.backup(h.admin, h.path.parent / "bad-backup.sqlite3")


def test_attachment_tamper_fails_all_protected_reads(h):
    attachment = h.attachment()
    with pytest.raises(sqlite3.IntegrityError):
        h.store._db.execute("UPDATE attachment_bytes SET content=?", (b"changed",))
    trigger_sql = h.store._db.execute("SELECT sql FROM sqlite_master WHERE name='attachments_no_update'").fetchone()[0]
    h.store._db.execute("DROP TRIGGER attachments_no_update")
    h.store._db.execute("UPDATE attachment_bytes SET content=?", (b"changed",))
    h.store._db.execute(trigger_sql)
    with pytest.raises(IntegrityError, match="Attachment content"):
        h.store.read_attachment(h.observe, attachment["id"])
    with pytest.raises(IntegrityError):
        h.store.whoami(h.admin)


def test_event_alteration_fails_hash_chain(h):
    trigger_sql = h.store._db.execute("SELECT sql FROM sqlite_master WHERE name='events_no_update'").fetchone()[0]
    h.store._db.execute("DROP TRIGGER events_no_update")
    h.store._db.execute("UPDATE events SET action='forged' WHERE sequence=1")
    h.store._db.execute(trigger_sql)
    with pytest.raises(IntegrityError, match="hash chain"):
        h.store.list_records(h.observe)


def test_self_reported_engineer_does_not_become_verified_or_grant_pilot(h):
    site = h.site()
    evidence = h.attachment()
    saved = h.store.record_evidence_review(h.review, site["id"], "engineer_review", "accepted_for_discussion",
                                           "Synthetic identity fixture only", [evidence["id"]],
                                           engineer_name="Fixture Engineer", qualification_reference="Self-entered fixture, not verified")
    assert saved["data"]["qualification_status"] == "reported_not_independently_verified"
    report = h.store.readiness(h.observe, site["id"])
    assert not report["professional_identity_verified"]
    assert not report["operational_activation_allowed"]
    assert not report["pilot_authorised"]
    assert not report["legacy_ticket_authentication_covered"]
    assert "external_engineering_authority_required" in {g["code"] for g in report["documentary_gaps"]}


def test_verified_backup_restore_never_overwrites_and_revokes_restored_sessions(h, tmp_path):
    site = h.site()
    evidence = h.attachment()
    backup = h.store.backup(h.admin, tmp_path / "backup.sqlite3")
    assert backup["integrity"]["valid"]
    assert backup["contains_password_hashes_and_session_hashes"]
    with pytest.raises(OperationsError, match="new path"):
        h.store.backup(h.admin, tmp_path / "backup.sqlite3")
    with pytest.raises(OperationsError, match="new destination"):
        h.store.restore_new(h.admin, tmp_path / "backup.sqlite3", h.path)
    restored = h.store.restore_new(h.admin, tmp_path / "backup.sqlite3", tmp_path / "restored.sqlite3")
    assert not restored["live_database_replaced"]
    assert restored["all_sessions_revoked"]
    assert h.store.whoami(h.admin)["username"] == "admin"
    other = OperationsStore(restored["path"], clock=h.clock)
    try:
        with pytest.raises(AuthenticationError):
            other.whoami(h.admin)
        token = other.login("admin", PASSWORD)["token"]
        assert other.get_record(token, site["id"])["sha256"] == site["sha256"]
        assert other.read_attachment(token, evidence["id"])["content"].startswith(b"SYNTHETIC TEST")
        assert other.verify_integrity(token)["valid"]
    finally:
        other.close()


def test_foreign_or_altered_backup_is_rejected_before_restore(h, tmp_path):
    foreign = tmp_path / "foreign.sqlite3"
    db = sqlite3.connect(foreign)
    db.execute("CREATE TABLE arbitrary (value TEXT)")
    db.close()
    with pytest.raises(IntegrityError):
        h.store.restore_new(h.admin, foreign, tmp_path / "no-restore.sqlite3")
    assert not (tmp_path / "no-restore.sqlite3").exists()
    with pytest.raises(OperationsError, match="separate database"):
        OperationsStore(foreign)
    backup = h.store.backup(h.admin, tmp_path / "altered.sqlite3")
    altered = sqlite3.connect(backup["path"])
    trigger_sql = altered.execute("SELECT sql FROM sqlite_master WHERE name='events_no_update'").fetchone()[0]
    altered.execute("DROP TRIGGER events_no_update")
    altered.execute("UPDATE events SET action='forged' WHERE sequence=1")
    altered.execute(trigger_sql)
    altered.commit()
    altered.close()
    with pytest.raises(IntegrityError):
        h.store.restore_new(h.admin, backup["path"], tmp_path / "altered-restored.sqlite3")
    assert not (tmp_path / "altered-restored.sqlite3").exists()


def test_export_has_no_credentials_and_references_original_evidence(h):
    shadow = h.shadow()
    exported = h.store.export_site(h.observe, shadow["data"]["site_id"])
    assert all(r["kind"] not in ("account", "session") for r in exported["records"])
    assert PASSWORD not in json.dumps(exported)
    assert h.admin not in json.dumps(exported)
    assert not exported["operational_activation_allowed"]
    assert canonical_sha256(exported["records"])


def test_model_artifact_from_another_site_is_rejected(h):
    interview = h.interview()
    model = {"model_id": "fixture", "policy_id": "fixture", "generated_at": h.clock.iso(),
             "inputs_sha256": input_snapshot_sha256(h.inputs()), "site_package_sha256": "f" * 64,
             "result": {"decision": "abstain", "queue": [], "reasons": ["Fixture only"]}}
    with pytest.raises(OperationsError, match="different site package"):
        h.store.reveal_model(h.dispatch, interview["id"], interview["version"], model)


def test_valid_site_rejects_nonexistent_authorised_and_model_jobs(h):
    site = h.site(valid=True)
    interview = h.interview(site)
    constraints = dict(interview["data"]["constraints"], authorised_jobs=["UNKNOWN_JOB"])
    with pytest.raises(OperationsError, match="staged valid site's job IDs"):
        h.store.revise_interview(h.dispatch, interview["id"], interview["version"], constraints,
                                 interview["data"]["baseline_plan"], "Fixture bad job ID")
    model = {"model_id": "fixture", "policy_id": "fixture", "generated_at": h.clock.iso(),
             "inputs_sha256": input_snapshot_sha256(h.inputs()), "site_package_sha256": site["data"]["package_sha256"],
             "result": {"decision": "recommend", "queue": ["UNKNOWN_JOB"], "reasons": ["Invalid fixture"]}}
    with pytest.raises(OperationsError, match="outside the staged valid"):
        h.store.reveal_model(h.dispatch, interview["id"], interview["version"], model)


def test_removed_immutability_guard_fails_closed(h):
    h.store._db.execute("DROP TRIGGER events_no_delete")
    with pytest.raises(IntegrityError, match="guard has been removed"):
        h.store.whoami(h.admin)
    with pytest.raises(IntegrityError, match="guard has been removed"):
        OperationsStore(h.path)


def test_append_order_controls_latest_evidence_review_with_equal_timestamps(h):
    site = h.site()
    evidence = h.attachment()
    for assessment in ("accepted_for_discussion", "rejected"):
        h.store.record_evidence_review(h.review, site["id"], "frozen_evaluation", assessment,
                                       "Synthetic test only", [evidence["id"]])
    assert h.store.readiness(h.observe, site["id"])["evidence_review_statuses"]["frozen_evaluation"] == "rejected"


def test_future_site_package_cannot_supply_earlier_model_snapshot(h):
    payload = h.site(valid=True)["data"]["package"]
    payload["created_at"] = (h.clock.now + timedelta(hours=2)).isoformat()
    for source in payload["sources"]:
        source["observed_at"] = (h.clock.now + timedelta(hours=1)).isoformat()
    for job in payload["jobs"]:
        job["approval"]["reviewed_at"] = (h.clock.now + timedelta(hours=1)).isoformat()
    site = h.store.stage_site(h.dispatch, payload)
    assert site["data"]["validation"]["valid"]
    interview, inputs = h.reveal(h.interview(site))
    with pytest.raises(OperationsError, match="site package created after"):
        h.store.create_shadow(h.dispatch, site["id"], interview["id"], inputs, protocol())


def test_valid_synthetic_contract_completes_documentary_loop_without_field_claim(h):
    payload = h.site(valid=True)["data"]["package"]
    payload["created_at"] = h.clock.iso()
    for source in payload["sources"]:
        source["observed_at"] = h.clock.iso()
    for job in payload["jobs"]:
        job["approval"]["reviewed_at"] = h.clock.iso()
    site = h.store.stage_site(h.dispatch, payload)
    site = h.store.review_site(h.review, site["id"], site["version"], "Synthetic contract checked; no survey occurred")
    baseline_evidence = h.attachment()
    interview, inputs = h.reveal(h.interview(site))
    interview = h.store.record_interview_review(h.review, interview["id"], interview["version"],
                                                "Synthetic feedback only", [baseline_evidence["id"]])
    shadow = h.store.create_shadow(h.dispatch, site["id"], interview["id"], inputs, protocol())
    assert shadow["data"]["contract_coherence"] == "matched_declared_site_contract"
    h.clock.advance()
    evidence = h.attachment()
    h.store.record_outcome(h.observe, shadow["id"], shadow["version"], "observed", h.clock.iso(), observed_data(),
                           "Synthetic recorded outcome only", [evidence["id"]])
    readiness = h.store.readiness(h.observe, site["id"])
    assert readiness["synthetic_fixture_count"] == 1
    assert readiness["observed_shadow_count"] == 0
    assert not readiness["physical_validation_established"]
    assert not readiness["pilot_authorised"]
    assert h.store.verify_integrity(h.admin)["valid"]
