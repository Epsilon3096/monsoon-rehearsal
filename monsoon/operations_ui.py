"""Authenticated research intake and shadow records, separate from demo tickets."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import streamlit as st

from monsoon.service import data_root


def _json(text, label):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"{label}: duplicate key {key}")
            value[key] = item
        return value
    def invalid(value):
        raise ValueError(f"{label}: {value} is not a finite JSON value")
    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


def _attempt(call, message):
    try:
        result = call()
        st.success(message)
        return result
    except Exception as exc:
        st.error(str(exc))
        return None


def _select(records, label, key):
    if not records:
        st.caption(f"No {label.lower()} records yet.")
        return None
    by_id = {row["id"]: row for row in records}
    selected = st.selectbox(label, list(by_id), key=key,
                            format_func=lambda value: f'{value[:16]} · version {by_id[value]["version"]}')
    return by_id[selected]


def _attachment_ids(store, token, key):
    records = {row["id"]: row for row in store.list_records(token, kind="attachment")}
    return st.multiselect("Supporting evidence attachments", list(records), key=key,
                          format_func=lambda value: f'{records[value]["data"]["filename"]} · {value[:12]}')


def _authentication(store):
    from monsoon.operations import AuthenticationError
    if store.needs_bootstrap():
        st.subheader("Set up the local research administrator")
        st.write("Choose your own account. There are no default credentials. The administrator manages accounts; separate research accounts perform and review the work.")
        with st.form("ops_bootstrap", clear_on_submit=True):
            username = st.text_input("Administrator username")
            display = st.text_input("Administrator display name")
            password = st.text_input("Administrator password", type="password")
            confirm = st.text_input("Repeat administrator password", type="password")
            submit = st.form_submit_button("Create administrator")
        if submit:
            if password != confirm:
                st.error("Passwords do not match.")
            elif _attempt(lambda: store.bootstrap_admin(username, password, display), "Administrator created. Sign in with your new account.") is not None:
                st.rerun()
        return None
    token = st.session_state.get("ops_token")
    if token:
        try:
            return token, store.whoami(token)
        except AuthenticationError:
            st.session_state.pop("ops_token", None)
            st.info("Your research session ended. Sign in again.")
    with st.form("ops_login", clear_on_submit=True):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Sign in")
    if submit:
        session = _attempt(lambda: store.login(username, password), "Signed in.")
        if session:
            st.session_state["ops_token"] = session["token"]
            st.rerun()
    return None


def _accounts(store, token):
    st.subheader("Research accounts")
    st.caption("Use named accounts for the people performing each role. A site reviewer must be a different account from its submitter. Authentication does not verify professional qualifications.")
    with st.form("ops_create_user", clear_on_submit=True):
        username = st.text_input("New username")
        display = st.text_input("New display name")
        password = st.text_input("New password", type="password")
        roles = st.multiselect("Account roles", ["dispatcher", "reviewer", "observer", "inspector", "admin"])
        submit = st.form_submit_button("Create research account")
    if submit:
        _attempt(lambda: store.create_user(token, username, password, display, roles), "Research account created.")
    accounts = {row["id"]: row for row in store.list_users(token)}
    account_id = st.selectbox("Account to inspect", list(accounts), key="ops_account_to_disable",
                              format_func=lambda value: f'{accounts[value]["username"]} · {"enabled" if accounts[value]["enabled"] else "disabled"}')
    selected = accounts[account_id]
    if st.button("Disable selected account", key="ops_disable_account",
                 disabled=not selected["enabled"] or account_id == store.whoami(token)["id"]):
        _attempt(lambda: store.disable_user(token, account_id, selected["version"]), "Account disabled; its sessions are revoked.")
    st.caption("Private backups include account hashes and evidence. Restore to a separate location using the workflow guide; the live database is never overwritten automatically.")
    if st.button("Create private backup", key="ops_backup"):
        folder = data_root() / "private_backups"
        folder.mkdir(parents=True, exist_ok=True)
        result = _attempt(lambda: store.backup(token, folder / f"operations-{uuid4().hex}.sqlite3"), "Verified private backup created locally.")
        if result is not None:
            st.json(result, expanded=False)


def _site_records(store, token):
    st.subheader("Stage a site version")
    st.caption("The draft contract checks the submitted data. A reviewed package still needs physical validation and an implemented model adapter before operational use.")
    uploaded = st.file_uploader("Site version to stage", type=["json"], key="ops_site_upload")
    text = st.text_area("Or paste the site version JSON", height=150, key="ops_site_text")
    source = uploaded.getvalue() if uploaded is not None else text
    supporting = _attachment_ids(store, token, "ops_site_attachments")
    if st.button("Stage site version", disabled=not source, key="ops_stage"):
        _attempt(lambda: store.stage_site(token, source, supporting), "Site version stored for review; no model activated.")
    selected = _select(store.list_records(token, kind="site"), "Site version", "ops_site_selection")
    if selected:
        st.json(selected, expanded=False)
        notes = st.text_area("Site review findings", key="ops_site_review_notes")
        review_files = _attachment_ids(store, token, "ops_site_review_files")
        if st.button("Record site review", key="ops_review_site"):
            _attempt(lambda: store.review_site(token, selected["id"], selected["version"], notes, review_files), "Site review recorded. This is not hydraulic or pilot approval.")
        if st.button("Inspect readiness gaps", key="ops_readiness"):
            result = _attempt(lambda: store.readiness(token, selected["id"]), "Readiness gaps inspected.")
            if result is not None:
                st.json(result)
        exported = store.export_site(token, selected["id"])
        st.download_button("Download research record export", json.dumps(exported, indent=2, allow_nan=False),
                           file_name="monsoon-research-records.json", key="ops_export")
        with st.expander("Record an evidence review for readiness discussion"):
            category = st.selectbox("Evidence category", ["physical_measurements", "frozen_evaluation", "operating_constraints", "engineer_review"], key="ops_evidence_category")
            assessment = st.selectbox("Review assessment", ["unresolved", "rejected", "accepted_for_discussion"], key="ops_evidence_assessment")
            findings = st.text_area("Evidence findings and limitations", key="ops_evidence_findings")
            files = _attachment_ids(store, token, "ops_evidence_files")
            engineer = st.text_input("Responsible engineer (when reviewing engineering evidence)", key="ops_engineer")
            qualification = st.text_input("Qualification and verification reference", key="ops_qualification")
            if st.button("Record evidence review", key="ops_evidence_review"):
                _attempt(lambda: store.record_evidence_review(token, selected["id"], category, assessment, findings, files,
                    engineer_name=engineer or None, qualification_reference=qualification or None), "Evidence review recorded for discussion. No pilot authority granted.")


def _interviews(store, token):
    st.subheader("Capture the operator's baseline before showing the model")
    site = _select(store.list_records(token, kind="site"), "Interview site version", "ops_interview_site")
    if site:
        with st.form("ops_interview_create", clear_on_submit=True):
            name = st.text_input("Operator's name")
            role = st.text_input("Operator's actual role")
            window = st.text_area("Real maintenance window and decision being reviewed")
            st.caption("Leave an unknown constraint blank. It remains missing evidence; no default is invented.")
            crew = st.text_input("Available crew and equipment")
            authorised = st.text_input("Authorised job IDs (comma-separated)")
            empty_authorisation = st.checkbox("Confirmed: no discretionary jobs are authorised", key="ops_no_authorised_jobs")
            access = st.text_input("Access restrictions and travel requirements")
            deadline = st.text_input("Restoration deadline and its basis")
            stopping = st.text_area("Current stopping and escalation rules")
            closeout = st.text_area("Required restoration and inspection evidence")
            queue = st.text_input("Operator's priority queue", help="Comma-separated authorised job IDs. Leave empty for a no-work decision.")
            rationale = st.text_area("Operator's reasoning and conditional rules")
            no_work = st.text_input("Reason for no work (required for an empty queue)")
            supporting = _attachment_ids(store, token, "ops_interview_attachments")
            submitted = st.form_submit_button("Seal operator baseline")
        if submitted:
            if empty_authorisation and authorised.strip():
                st.error("An explicitly empty authorised-job list cannot also contain job IDs.")
                return
            _attempt(lambda: store.create_interview(token, site["id"], name, role, window,
                {"available_crew": crew or None, "authorised_jobs": [] if empty_authorisation else [x.strip() for x in authorised.split(",") if x.strip()] if authorised.strip() else None,
                 "access": access or None, "restoration_deadline": deadline or None, "stopping_rules": stopping or None, "closeout_evidence": closeout or None},
                {"queue": [x.strip() for x in queue.split(",") if x.strip()], "rationale": rationale, "no_work_reason": no_work or None}, supporting), "Baseline recorded before model disclosure.")
    selected = _select(store.list_records(token, kind="interview"), "Operator interview", "ops_interview_selection")
    if selected:
        st.json(selected, expanded=False)
        st.caption("Reveal the actual frozen model artifact only after capturing the independent baseline. Input hashes and times must match the later shadow record. There is no automatic site simulation behind this form.")
        snapshot = st.text_area("Frozen model snapshot JSON", height=160, key="ops_reveal_snapshot")
        if st.button("Record model disclosure", disabled=not snapshot, key="ops_reveal"):
            _attempt(lambda: store.reveal_model(token, selected["id"], selected["version"], _json(snapshot, "Model snapshot")), "Model disclosure recorded; the earlier baseline is retained.")
        review = st.text_area("Operator's response, disagreements and missing facts", height=130, key="ops_interview_review")
        review_files = _attachment_ids(store, token, "ops_operator_review_attachments")
        if st.button("Record operator review", disabled=not review, key="ops_record_interview_review"):
            _attempt(lambda: store.record_interview_review(token, selected["id"], selected["version"], review, review_files), "Operator review recorded with its stated evidence limits.")


def _shadow(store, token):
    st.subheader("Seal a prospective shadow decision")
    st.write("Shadow records observe decisions without directing maintenance. Capture them at the decision time; the system refuses to backfill old decisions as prospective evidence.")
    interview = _select(store.list_records(token, kind="interview"), "Shadow interview and baseline", "ops_shadow_interview")
    if interview:
        available = st.text_area("Inputs available now — JSON array", height=160, key="ops_shadow_inputs",
                                 help="Each item requires id, source, observed_at, issued_at, available_at and value. Preserve null for unknown.")
        protocol = st.text_area("Frozen shadow protocol JSON", height=130, key="ops_shadow_protocol")
        if st.button("Check decision-input fingerprint", disabled=not available, key="ops_input_hash"):
            from monsoon.operations import input_snapshot_sha256
            value = _attempt(lambda: input_snapshot_sha256(_json(available, "Inputs")), "Input fingerprint calculated; this does not validate the model.")
            if value:
                st.code(value)
        if st.button("Seal shadow decision now", disabled=not available or not protocol, key="ops_shadow_create"):
            _attempt(lambda: store.create_shadow(token, interview["data"]["site_id"], interview["id"],
                _json(available, "Available inputs"), _json(protocol, "Protocol")), "Prospective shadow record sealed. No work authorised.")
    selected = _select(store.list_records(token, kind="shadow"), "Shadow decision", "ops_shadow_selection")
    if selected:
        st.json(selected, expanded=False)
        st.subheader("Append the observed outcome")
        status = st.selectbox("Outcome evidence status", ["observed", "missing", "error"], key="ops_outcome_status")
        observed_at = st.text_input("Observation timestamp with timezone", placeholder="YYYY-MM-DDTHH:MM:SS+08:00", key="ops_outcome_time")
        observations = st.text_area("Actual observations JSON", height=130, key="ops_outcome_json")
        notes = st.text_area("Outcome notes, exceptions and missing evidence", key="ops_outcome_notes")
        files = _attachment_ids(store, token, "ops_outcome_attachments")
        if st.button("Append outcome", key="ops_record_outcome"):
            _attempt(lambda: store.record_outcome(token, selected["id"], selected["version"], status, observed_at,
                _json(observations or "{}", "Observations"), notes, files), "Outcome appended; it does not establish the unobserved alternative outcome.")


def _attachments(store, token):
    st.subheader("Evidence attachments")
    st.caption("Files are retained as evidence bytes with hashes and provenance. They are not executed or accepted as proof of authenticity. Do not include credentials or unnecessary personal information.")
    upload = st.file_uploader("Evidence file", type=["txt", "csv", "json", "pdf", "png", "jpg", "jpeg"], key="ops_attachment")
    provenance = st.text_area("Source, collection method and evidence limitations", key="ops_attachment_provenance")
    observed = st.text_input("Evidence observation timestamp with timezone", key="ops_attachment_observed")
    if st.button("Store evidence attachment", disabled=upload is None or not provenance, key="ops_attachment_save"):
        types = {".txt": "text/plain", ".csv": "text/csv", ".json": "application/json", ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
        result = _attempt(lambda: store.add_attachment(token, upload.name, upload.getvalue(), types.get(Path(upload.name).suffix.lower(), "application/octet-stream"),
                          provenance, observed), "Attachment stored. Select it in the supporting evidence for the relevant record.")
        if result:
            st.json(result)


def render_operations():
    from monsoon.operations import OperationsStore

    st.subheader("Operator review and shadow records")
    st.info("Authenticated local research workspace. Existing synthetic Work tickets use their original named-actor demonstration. Neither workspace is a production dispatch service.")
    store = None
    try:
        store = OperationsStore(data_root() / "operations.sqlite3")
        auth = _authentication(store)
        if not auth:
            return
        token, user = auth
        st.write(f'Signed in as **{user.get("display_name", user.get("username", "research user"))}** · {", ".join(user.get("roles", []))}')
        if st.button("Sign out", key="ops_logout"):
            store.logout(token)
            st.session_state.pop("ops_token", None)
            st.rerun()
        choices = ["Accounts"] if user.get("roles") == ["admin"] else ["Site records", "Operator interview", "Shadow decisions", "Attachments"]
        if "admin" in user.get("roles", []) and "Accounts" not in choices:
            choices.append("Accounts")
        page = st.selectbox("Research activity", choices, key="ops_activity")
        if page == "Accounts":
            _accounts(store, token)
        elif page == "Site records":
            _site_records(store, token)
        elif page == "Operator interview":
            _interviews(store, token)
        elif page == "Shadow decisions":
            _shadow(store, token)
        else:
            _attachments(store, token)
    except Exception as exc:
        st.error(f"Research workspace could not be opened: {exc}")
    finally:
        if store is not None:
            store.disconnect()
