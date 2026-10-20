"""Authenticated local evidence records for research and prospective SHADOW work.

This store is separate from the legacy, unauthenticated TicketStore.  It neither
activates a hydraulic model nor issues work orders, permits, or pilot authority.
The append-only hash chain detects accidental/casual alteration; a person with
write access to the database and application can replace both data and hashes.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import secrets
import sqlite3
import threading
from uuid import uuid4


class OperationsError(ValueError):
    """An invalid, stale, unsupported, or unauthorised research operation."""


class AuthenticationError(OperationsError):
    """Credentials or a session are missing, invalid, expired, or revoked."""


class PermissionDenied(OperationsError):
    """The authenticated account lacks the required local role."""


class IntegrityError(OperationsError):
    """Saved records, event hashes, or evidence bytes no longer agree."""


class ConflictError(OperationsError):
    """Another change has superseded the supplied record version."""


ROLES = frozenset({"admin", "reviewer", "dispatcher", "observer", "inspector"})
CONSTRAINT_FIELDS = ("available_crew", "authorised_jobs", "access",
                     "restoration_deadline", "stopping_rules", "closeout_evidence")
EVIDENCE_CATEGORIES = ("physical_measurements", "frozen_evaluation",
                       "operating_constraints", "engineer_review")
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_JSON_BYTES = 1024 * 1024
MAX_DECISION_AGE_SECONDS = 300
_ZERO_HASH = "0" * 64
_MIME = {".txt": "text/plain", ".csv": "text/csv", ".json": "application/json",
         ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
         ".jpeg": "image/jpeg"}


def _json(value):
    try:
        result = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False,
                            ensure_ascii=False)
        if len(result.encode("utf-8")) > MAX_JSON_BYTES:
            raise OperationsError("A record may contain at most 1 MiB of JSON.")
        return result
    except (TypeError, ValueError, RecursionError) as exc:
        raise OperationsError("Values must be finite, JSON-serialisable data.") from exc


def canonical_sha256(value):
    """Hash a bounded JSON value using the same canonical form as this store."""
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def input_snapshot_sha256(available_inputs):
    """Hash the exact input list, including its supplied timestamp strings."""
    return canonical_sha256(available_inputs)


def _copy(value):
    return json.loads(_json(value))


def _text(value, label, maximum=8000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise OperationsError(f"{label} must be non-empty text, at most {maximum} characters.")
    return value.strip()


def _time(value, label):
    if not isinstance(value, str):
        raise OperationsError(f"{label} must be an ISO 8601 timestamp with a timezone.")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OperationsError(f"{label} must be an ISO 8601 timestamp with a timezone.") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise OperationsError(f"{label} must include a timezone.")
    return result.astimezone(timezone.utc)


def _iso(value):
    return value.astimezone(timezone.utc).isoformat()


def _sha(value, label):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise OperationsError(f"{label} must be a lowercase SHA-256 digest.")
    return value


def _queue(value, label):
    if not isinstance(value, list) or len(value) > 1000:
        raise OperationsError(f"{label} must be a list of at most 1000 job identifiers.")
    values = [_text(item, label, 120) for item in value]
    if len(set(values)) != len(values):
        raise OperationsError(f"{label} cannot contain duplicate jobs.")
    return values


def _baseline(value):
    if not isinstance(value, dict):
        raise OperationsError("The operator baseline must be an object.")
    result = _copy(value)
    result["queue"] = _queue(result.get("queue"), "Operator queue")
    result["rationale"] = _text(result.get("rationale"), "Operator rationale")
    if not result["queue"]:
        result["no_work_reason"] = _text(result.get("no_work_reason"), "No-work reason")
    elif result.get("no_work_reason") is not None:
        result["no_work_reason"] = _text(result["no_work_reason"], "No-work reason")
    else:
        result["no_work_reason"] = None
    return result


def _constraints(value):
    if not isinstance(value, dict) or any(key not in value for key in CONSTRAINT_FIELDS):
        raise OperationsError("Constraints need explicit values (or null) for: " + ", ".join(CONSTRAINT_FIELDS))
    result = _copy(value)
    for key in CONSTRAINT_FIELDS:
        if key != "authorised_jobs" and (result[key] == "" or isinstance(result[key], str) and not result[key].strip()
                                          or result[key] == {} or result[key] == []):
            result[key] = None
    if result["authorised_jobs"] is not None:
        result["authorised_jobs"] = _queue(result["authorised_jobs"], "Authorised jobs")
    return result


def _validate_plan_constraints(plan, constraints):
    jobs = constraints["authorised_jobs"]
    if jobs is not None and not set(plan["queue"]).issubset(jobs):
        raise OperationsError("The recorded operator queue contains an unauthorised job.")


def _password_hash(password, salt=None):
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise OperationsError("Use a password of 12 to 1024 characters; there are no default credentials.")
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                            n=16384, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)
    return {"algorithm": "scrypt", "n": 16384, "r": 8, "p": 1,
            "salt": salt, "digest": digest.hex()}


def _password_matches(password, stored):
    try:
        return hmac.compare_digest(_password_hash(password, stored["salt"])["digest"], stored["digest"])
    except (OperationsError, KeyError, ValueError):
        return False


class OperationsStore:
    """Small local authenticated store; every public read/write checks its session.

    Only ``needs_bootstrap``, first-run ``bootstrap_admin``, and ``login`` are
    unauthenticated.  Admin is an account-management role, not an automatic
    reviewer/dispatcher role.  All timestamps are stored in UTC.
    """

    SCHEMA_VERSION = 1
    APPLICATION_ID = 0x4D4F5053

    def __init__(self, db_path, *, session_seconds=3600, clock=None):
        if isinstance(session_seconds, bool) or not isinstance(session_seconds, int) or not 60 <= session_seconds <= 43200:
            raise OperationsError("Session lifetime must be 60 to 43200 seconds.")
        self.db_path = str(db_path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.session_seconds = session_seconds
        self._lock = threading.RLock()
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.db_path, timeout=30, isolation_level=None,
                                   check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA busy_timeout=30000")
        tables = self._db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
        appid = self._db.execute("PRAGMA application_id").fetchone()[0]
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if tables and (appid != self.APPLICATION_ID or version != self.SCHEMA_VERSION):
            self._db.close()
            raise OperationsError("This is not a compatible operations database; use a separate database file.")
        if tables:
            try:
                with self._tx(write=False):
                    self._verify()
            except Exception:
                self._db.close()
                raise
            self._db.execute("PRAGMA journal_mode=WAL")
            return
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript("""
          BEGIN IMMEDIATE;
          CREATE TABLE IF NOT EXISTS records (
            kind TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL,
            payload_json TEXT NOT NULL, sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL, actor_id TEXT NOT NULL,
            PRIMARY KEY(id,version));
          CREATE INDEX IF NOT EXISTS records_kind ON records(kind,id,version);
          CREATE TABLE IF NOT EXISTS events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
            entity_id TEXT NOT NULL, version INTEGER NOT NULL, action TEXT NOT NULL,
            actor_id TEXT NOT NULL, created_at TEXT NOT NULL,
            before_sha256 TEXT NOT NULL, after_sha256 TEXT NOT NULL,
            previous_sha256 TEXT NOT NULL, sha256 TEXT NOT NULL,
            UNIQUE(entity_id,version));
          CREATE TABLE IF NOT EXISTS attachment_bytes (
            id TEXT PRIMARY KEY, content BLOB NOT NULL);
          CREATE TRIGGER IF NOT EXISTS records_no_update BEFORE UPDATE ON records
            BEGIN SELECT RAISE(ABORT,'Research records are append-only'); END;
          CREATE TRIGGER IF NOT EXISTS records_no_delete BEFORE DELETE ON records
            BEGIN SELECT RAISE(ABORT,'Research records are append-only'); END;
          CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
            BEGIN SELECT RAISE(ABORT,'Audit events are append-only'); END;
          CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
            BEGIN SELECT RAISE(ABORT,'Audit events are append-only'); END;
          CREATE TRIGGER IF NOT EXISTS attachments_no_update BEFORE UPDATE ON attachment_bytes
            BEGIN SELECT RAISE(ABORT,'Attachment bytes are immutable'); END;
          CREATE TRIGGER IF NOT EXISTS attachments_no_delete BEFORE DELETE ON attachment_bytes
            BEGIN SELECT RAISE(ABORT,'Attachment bytes are immutable'); END;
        """ + f"PRAGMA application_id={self.APPLICATION_ID}; PRAGMA user_version={self.SCHEMA_VERSION}; COMMIT;")

    def disconnect(self):
        with self._lock:
            self._db.close()

    close = disconnect

    def _now(self):
        result = self._clock()
        if not isinstance(result, datetime) or result.tzinfo is None:
            raise OperationsError("The store clock must return a timezone-aware datetime.")
        return result.astimezone(timezone.utc)

    @contextmanager
    def _tx(self, *, write=True):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    @staticmethod
    def _record(row):
        return {"id": row["id"], "kind": row["kind"], "version": row["version"],
                "created_at": row["created_at"], "created_by": row["actor_id"],
                "sha256": row["sha256"], "data": json.loads(row["payload_json"])}

    def _get(self, identifier, kind=None):
        row = self._db.execute("SELECT * FROM records WHERE id=? ORDER BY version DESC LIMIT 1", (identifier,)).fetchone()
        if row is None or (kind and row["kind"] != kind):
            raise OperationsError("Unknown research record.")
        return self._record(row)

    def _latest(self, kind=None):
        rows = self._db.execute("SELECT r.* FROM records r JOIN (SELECT id,MAX(version) v FROM records GROUP BY id) x ON r.id=x.id AND r.version=x.v JOIN events e ON e.entity_id=r.id AND e.version=r.version ORDER BY e.sequence").fetchall()
        return [self._record(row) for row in rows if kind is None or row["kind"] == kind]

    @staticmethod
    def _expected(record, expected_version):
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version != record["version"]:
            raise ConflictError("The record changed; reload it and review the current version before saving.")

    def _save(self, kind, payload, actor_id, action, *, record=None):
        identifier = record["id"] if record else uuid4().hex
        version = record["version"] + 1 if record else 1
        now = _iso(self._now())
        state = {"kind": kind, "id": identifier, "version": version, "data": _copy(payload),
                 "created_at": now, "created_by": actor_id}
        digest = canonical_sha256(state)
        previous = self._db.execute("SELECT sha256 FROM events ORDER BY sequence DESC LIMIT 1").fetchone()
        event = {"kind": kind, "entity_id": identifier, "version": version,
                 "action": action, "actor_id": actor_id, "created_at": now,
                 "before_sha256": record["sha256"] if record else _ZERO_HASH,
                 "after_sha256": digest, "previous_sha256": previous[0] if previous else _ZERO_HASH}
        event_hash = canonical_sha256(event)
        self._db.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?)",
                         (kind, identifier, version, _json(payload), digest, now, actor_id))
        self._db.execute("INSERT INTO events(kind,entity_id,version,action,actor_id,created_at,before_sha256,after_sha256,previous_sha256,sha256) VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (*event.values(), event_hash))
        return dict(state, sha256=digest)

    def _verify(self):
        try:
            required_triggers = {"records_no_update", "records_no_delete", "events_no_update",
                                 "events_no_delete", "attachments_no_update", "attachments_no_delete"}
            triggers = {row[0] for row in self._db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
            if not required_triggers.issubset(triggers):
                raise IntegrityError("An append-only database guard has been removed.")
            rows = self._db.execute("SELECT * FROM records ORDER BY id,version").fetchall()
            records = {}
            shadow_seals = {}
            for row in rows:
                record = self._record(row)
                digest = record.pop("sha256")
                if canonical_sha256(record) != digest:
                    raise IntegrityError("A saved record has been altered.")
                if row["kind"] == "shadow":
                    data = record["data"]
                    seal = data["decision_seal_sha256"]
                    sealed_fields = {key: value for key, value in data.items()
                                     if key not in ("decision_seal_sha256", "outcome_ids", "outcome_status")}
                    if canonical_sha256(sealed_fields) != seal or shadow_seals.get(row["id"], seal) != seal:
                        raise IntegrityError("A sealed shadow decision changed between revisions.")
                    shadow_seals[row["id"]] = seal
                records[(row["id"], row["version"])] = (row, digest)
            previous, latest, seen = _ZERO_HASH, {}, set()
            events = self._db.execute("SELECT * FROM events ORDER BY sequence").fetchall()
            for index, row in enumerate(events, 1):
                event = dict(row)
                sequence, digest = event.pop("sequence"), event.pop("sha256")
                key = (row["entity_id"], row["version"])
                old = latest.get(row["entity_id"])
                if sequence != index or row["previous_sha256"] != previous or canonical_sha256(event) != digest:
                    raise IntegrityError("The immutable event hash chain does not verify.")
                if key not in records or key in seen:
                    raise IntegrityError("An event has no unique matching record revision.")
                saved, saved_hash = records[key]
                if (row["after_sha256"] != saved_hash or row["kind"] != saved["kind"]
                    or row["created_at"] != saved["created_at"] or row["actor_id"] != saved["actor_id"]
                    or row["version"] != (old[0] + 1 if old else 1)
                    or row["before_sha256"] != (old[1] if old else _ZERO_HASH)):
                    raise IntegrityError("An event does not match its record revision.")
                latest[row["entity_id"]] = (row["version"], saved_hash)
                seen.add(key)
                previous = digest
            if seen != set(records):
                raise IntegrityError("A record revision is missing its audit event.")
            blobs = {row["id"]: bytes(row["content"]) for row in self._db.execute("SELECT * FROM attachment_bytes")}
            attachment_ids = set()
            for (identifier, version), (row, _) in records.items():
                if row["kind"] != "attachment":
                    continue
                data = json.loads(row["payload_json"])
                attachment_ids.add(identifier)
                blob = blobs.get(identifier)
                if version != 1 or blob is None or len(blob) != data["size_bytes"] or hashlib.sha256(blob).hexdigest() != data["content_sha256"]:
                    raise IntegrityError("Attachment content is missing or its checksum has changed.")
            if set(blobs) != attachment_ids:
                raise IntegrityError("Untracked attachment bytes were found.")
            return {"valid": True, "record_revisions": len(rows), "events": len(events),
                    "attachments": len(blobs), "head_sha256": previous,
                    "scope": "Local tamper evidence; not an external signature or identity verification."}
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, sqlite3.DatabaseError) as exc:
            if isinstance(exc, IntegrityError):
                raise
            raise IntegrityError("The research store contains malformed or altered evidence.") from exc

    @staticmethod
    def _public_user(record):
        data = record["data"]
        return {"id": record["id"], "version": record["version"], "username": data["username"],
                "display_name": data["display_name"], "roles": data["roles"], "enabled": data["enabled"]}

    def _auth(self, token, roles=()):
        self._verify()
        if not isinstance(token, str) or len(token) < 32:
            raise AuthenticationError("Sign in with an active local research account.")
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        sessions = [r for r in self._latest("session") if hmac.compare_digest(r["data"]["token_sha256"], digest)]
        if len(sessions) != 1:
            raise AuthenticationError("The session is invalid, expired, or revoked.")
        session = sessions[0]
        if session["data"]["revoked"] or self._now() >= _time(session["data"]["expires_at"], "Session expiry"):
            raise AuthenticationError("The session is invalid, expired, or revoked.")
        user = self._get(session["data"]["account_id"], "account")
        if not user["data"]["enabled"] or user["version"] != session["data"]["account_version"]:
            raise AuthenticationError("The account changed or was disabled; sign in again.")
        if roles and not set(roles).intersection(user["data"]["roles"]):
            raise PermissionDenied("This operation requires one of these local roles: " + ", ".join(roles))
        return user, session

    def needs_bootstrap(self):
        with self._tx(write=False):
            self._verify()
            return not self._latest("account")

    def _new_user(self, username, password, display_name, roles, actor_id):
        username = _text(username, "Username", 64).lower()
        if re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,63}", username) is None:
            raise OperationsError("Usernames need 3–64 lowercase letters, numbers, dots, underscores or hyphens.")
        if any(r["data"]["username"] == username for r in self._latest("account")):
            raise OperationsError("That local username already exists.")
        if (not isinstance(roles, (list, tuple)) or not roles or any(not isinstance(role, str) for role in roles)
            or set(roles) - ROLES or len(set(roles)) != len(roles)):
            raise OperationsError("Choose distinct local roles from: " + ", ".join(sorted(ROLES)))
        data = {"username": username, "display_name": _text(display_name, "Display name", 200),
                "roles": sorted(roles), "enabled": True, "password": _password_hash(password),
                "identity_status": "locally_created_account_not_external_identity_verification"}
        return self._save("account", data, actor_id, "account_created")

    def bootstrap_admin(self, username, password, display_name):
        with self._tx():
            self._verify()
            if self._latest("account"):
                raise PermissionDenied("First-run setup has already been completed.")
            return self._public_user(self._new_user(username, password, display_name, ["admin"], "local_first_run"))

    def login(self, username, password):
        with self._tx():
            self._verify()
            candidates = [r for r in self._latest("account") if isinstance(username, str) and r["data"]["username"] == username.strip().lower()]
            if len(candidates) != 1 or not candidates[0]["data"]["enabled"] or not _password_matches(password, candidates[0]["data"]["password"]):
                # Equal-cost password work for unknown/disabled names limits username timing disclosure.
                if not candidates or not candidates[0]["data"]["enabled"]:
                    _password_hash("unavailable-local-account", "00" * 16)
                raise AuthenticationError("Username or password is incorrect.")
            user = candidates[0]
            token = secrets.token_urlsafe(32)
            expiry = _iso(self._now() + timedelta(seconds=self.session_seconds))
            self._save("session", {"account_id": user["id"], "account_version": user["version"],
                                   "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                                   "expires_at": expiry, "revoked": False}, user["id"], "session_opened")
            return {"token": token, "expires_at": expiry, "user": self._public_user(user)}

    def whoami(self, token):
        with self._tx(write=False):
            return self._public_user(self._auth(token)[0])

    def logout(self, token):
        with self._tx():
            user, session = self._auth(token)
            self._save("session", dict(session["data"], revoked=True), user["id"], "session_revoked", record=session)

    def create_user(self, token, username, password, display_name, roles):
        with self._tx():
            user, _ = self._auth(token, ("admin",))
            return self._public_user(self._new_user(username, password, display_name, roles, user["id"]))

    def list_users(self, token):
        with self._tx(write=False):
            self._auth(token, ("admin",))
            return [self._public_user(r) for r in self._latest("account")]

    def disable_user(self, token, account_id, expected_version):
        with self._tx():
            user, _ = self._auth(token, ("admin",))
            record = self._get(account_id, "account")
            self._expected(record, expected_version)
            if record["id"] == user["id"]:
                raise OperationsError("An administrator cannot disable their own active account.")
            return self._public_user(self._save("account", dict(record["data"], enabled=False),
                                               user["id"], "account_disabled", record=record))

    def change_password(self, token, current_password, new_password):
        with self._tx():
            user, _ = self._auth(token)
            if not _password_matches(current_password, user["data"]["password"]):
                raise AuthenticationError("The current password is incorrect.")
            self._save("account", dict(user["data"], password=_password_hash(new_password)),
                       user["id"], "password_changed_sessions_invalidated", record=user)

    def get_record(self, token, record_id):
        with self._tx(write=False):
            self._auth(token)
            record = self._get(record_id)
            if record["kind"] in ("account", "session"):
                raise PermissionDenied("Credential records are not exposed by the research record API.")
            return record

    def list_records(self, token, kind=None, site_id=None):
        with self._tx(write=False):
            self._auth(token)
            if kind in ("account", "session"):
                raise PermissionDenied("Credential records are not exposed by the research record API.")
            return [r for r in self._latest(kind) if r["kind"] not in ("account", "session")
                    and (site_id is None or r["data"].get("site_id") == site_id or r["id"] == site_id)]

    def verify_integrity(self, token):
        with self._tx(write=False):
            self._auth(token)
            return self._verify()

    def add_attachment(self, token, filename, content, media_type, provenance, observed_at):
        with self._tx():
            user, _ = self._auth(token, ("dispatcher", "reviewer", "observer", "inspector"))
            filename = _text(filename, "Attachment filename", 120)
            if (PureWindowsPath(filename).name != filename or PurePosixPath(filename).name != filename
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]*", filename) is None
                or filename.endswith((".", " ")) or ".." in filename
                or filename.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}):
                raise OperationsError("Use a plain safe filename without a path or reserved device name.")
            extension = Path(filename).suffix.lower()
            if extension not in _MIME or media_type != _MIME[extension]:
                raise OperationsError("Only matching TXT, CSV, JSON, PDF, PNG, or JPEG attachment types are supported.")
            if not isinstance(content, bytes) or not 0 < len(content) <= MAX_ATTACHMENT_BYTES:
                raise OperationsError("Attachment content must contain 1 byte to 5 MiB.")
            if extension in (".txt", ".csv", ".json"):
                try:
                    decoded = content.decode("utf-8-sig")
                    if "\x00" in decoded:
                        raise ValueError("NUL byte")
                    if extension == ".json":
                        _json(json.loads(decoded, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON"))))
                except (UnicodeError, ValueError) as exc:
                    raise OperationsError("Text attachments must be UTF-8 and JSON must contain finite valid JSON.") from exc
            elif (extension == ".pdf" and not content.startswith(b"%PDF-")) or (extension == ".png" and not content.startswith(b"\x89PNG\r\n\x1a\n")) or (extension in (".jpg", ".jpeg") and not content.startswith(b"\xff\xd8\xff")):
                raise OperationsError("The attachment header does not match its declared type.")
            observed = _time(observed_at, "Evidence observation time")
            if observed > self._now():
                raise OperationsError("Evidence observation time cannot be in the future.")
            if isinstance(provenance, dict):
                provenance = _copy(provenance)
                _text(provenance.get("source"), "Evidence provenance source")
            else:
                provenance = _text(provenance, "Evidence provenance")
            record = self._save("attachment", {"filename": filename, "media_type": media_type,
                                "size_bytes": len(content), "content_sha256": hashlib.sha256(content).hexdigest(),
                                "provenance": provenance, "observed_at": _iso(observed),
                                "received_at": _iso(self._now()), "verification_status": "content_hash_only_source_not_verified"},
                                user["id"], "attachment_recorded")
            self._db.execute("INSERT INTO attachment_bytes VALUES(?,?)", (record["id"], content))
            return record

    def read_attachment(self, token, attachment_id):
        with self._tx(write=False):
            self._auth(token)
            record = self._get(attachment_id, "attachment")
            blob = bytes(self._db.execute("SELECT content FROM attachment_bytes WHERE id=?", (attachment_id,)).fetchone()[0])
            return {"record": record, "content": blob}

    def _attachments(self, identifiers, *, cutoff=None, required=False):
        if (not isinstance(identifiers, (list, tuple)) or len(identifiers) > 100
            or any(not isinstance(value, str) for value in identifiers)
            or len(set(identifiers)) != len(identifiers)):
            raise OperationsError("Attachment IDs must be a distinct list of at most 100 stored attachments.")
        if required and not identifiers:
            raise OperationsError("This evidence review requires at least one stored attachment.")
        result = []
        for identifier in identifiers:
            record = self._get(identifier, "attachment")
            if cutoff and any(_time(record["data"][key], key) > cutoff for key in ("received_at", "observed_at")):
                raise OperationsError("Decision evidence was not available by its declared cutoff.")
            result.append({"id": identifier, "record_sha256": record["sha256"],
                           "content_sha256": record["data"]["content_sha256"]})
        return result

    def stage_site(self, token, payload, attachment_ids=()):
        with self._tx():
            user, _ = self._auth(token, ("dispatcher",))
            from monsoon.site_data import parse_json, validate_site_package
            try:
                frozen = _copy(parse_json(payload))
            except (ValueError, UnicodeError, TypeError) as exc:
                raise OperationsError("Site input must be bounded valid JSON with unique keys; keep malformed source files as attachments.") from exc
            report = _copy(validate_site_package(frozen))
            return self._save("site", {"package": frozen, "validation": report,
                               "package_sha256": canonical_sha256(frozen), "status": "staged",
                               "attachments": self._attachments(attachment_ids), "review": None,
                               "operational_activation_allowed": False, "physical_validation_established": False},
                               user["id"], "site_staged")

    def review_site(self, token, site_id, expected_version, notes, attachment_ids=()):
        with self._tx():
            user, _ = self._auth(token, ("reviewer",))
            site = self._get(site_id, "site")
            self._expected(site, expected_version)
            if site["created_by"] == user["id"]:
                raise PermissionDenied("A different account must review the staged site package.")
            if site["data"]["review"] is not None:
                raise OperationsError("This site version already has an immutable review; stage a new version for corrections.")
            from monsoon.site_data import validate_site_package
            validation = _copy(validate_site_package(site["data"]["package"]))
            if not validation.get("valid") or validation != site["data"]["validation"]:
                raise OperationsError("The site contract is invalid or the validator changed; stage a fresh corrected package.")
            review = {"reviewer_id": user["id"], "notes": _text(notes, "Site review notes"),
                      "attachments": self._attachments(attachment_ids), "recorded_at": _iso(self._now()),
                      "scope": "Contract review for research; no hydraulic activation or site permit."}
            return self._save("site", dict(site["data"], status="reviewed_for_research", review=review),
                              user["id"], "site_contract_reviewed", record=site)

    def create_interview(self, token, site_id, operator_name, operator_role, window_description,
                         constraints, baseline_plan, attachment_ids=()):
        with self._tx():
            user, _ = self._auth(token, ("dispatcher",))
            site = self._get(site_id, "site")
            constraints, baseline_plan = _constraints(constraints), _baseline(baseline_plan)
            _validate_plan_constraints(baseline_plan, constraints)
            if site["data"]["validation"].get("valid") and constraints["authorised_jobs"] is not None:
                job_ids = {job["id"] for job in site["data"]["package"]["jobs"]}
                if not set(constraints["authorised_jobs"]).issubset(job_ids):
                    raise OperationsError("Authorised jobs must refer to the staged valid site's job IDs.")
            now = _iso(self._now())
            return self._save("interview", {"site_id": site_id, "site_package_sha256": site["data"]["package_sha256"],
                               "operator_name": _text(operator_name, "Operator name", 200),
                               "operator_role": _text(operator_role, "Operator role", 200),
                               "window_description": _text(window_description, "Maintenance window"),
                               "constraints": constraints, "baseline_plan": baseline_plan,
                               "baseline_recorded_at": now, "attachments": self._attachments(attachment_ids),
                               "model_reveal": None, "operator_review": None,
                               "participation_status": "recorded_claim_not_independently_verified",
                               "status": "baseline_recorded_before_model_reveal"}, user["id"], "operator_baseline_recorded")

    def revise_interview(self, token, interview_id, expected_version, constraints, baseline_plan, notes):
        with self._tx():
            user, _ = self._auth(token, ("dispatcher",))
            record = self._get(interview_id, "interview")
            self._expected(record, expected_version)
            if record["data"]["model_reveal"] is not None:
                raise OperationsError("The operator baseline cannot change after model disclosure; retain disagreements in the review.")
            constraints, baseline_plan = _constraints(constraints), _baseline(baseline_plan)
            _validate_plan_constraints(baseline_plan, constraints)
            site = self._get(record["data"]["site_id"], "site")
            if site["data"]["validation"].get("valid") and constraints["authorised_jobs"] is not None:
                job_ids = {job["id"] for job in site["data"]["package"]["jobs"]}
                if not set(constraints["authorised_jobs"]).issubset(job_ids):
                    raise OperationsError("Authorised jobs must refer to the staged valid site's job IDs.")
            data = dict(record["data"], constraints=constraints, baseline_plan=baseline_plan,
                        baseline_recorded_at=_iso(self._now()), revision_notes=_text(notes, "Revision notes"))
            return self._save("interview", data, user["id"], "operator_baseline_revised_before_reveal", record=record)

    def _model(self, model_snapshot):
        if not isinstance(model_snapshot, dict):
            raise OperationsError("The frozen model snapshot must be an object.")
        model = _copy(model_snapshot)
        for key in ("model_id", "policy_id"):
            model[key] = _text(model.get(key), key, 200)
        _sha(model.get("inputs_sha256"), "Model input hash")
        _sha(model.get("site_package_sha256"), "Model site-package hash")
        if _time(model.get("generated_at"), "Model generation time") > self._now():
            raise OperationsError("Model generation time cannot be in the future.")
        result = model.get("result")
        if not isinstance(result, dict) or result.get("decision") not in ("recommend", "abstain", "no_work"):
            raise OperationsError("The model result needs a recommend, abstain, or no_work decision.")
        result["queue"] = _queue(result.get("queue"), "Model queue")
        if not isinstance(result.get("reasons"), list) or any(not isinstance(s, str) or not s.strip() for s in result["reasons"]):
            raise OperationsError("Model result reasons must be a list of non-empty strings.")
        if result["decision"] in ("abstain", "no_work") and (result["queue"] or not result["reasons"]):
            raise OperationsError("Abstention/no-work requires an empty queue and a recorded reason.")
        if result["decision"] == "recommend" and not result["queue"]:
            raise OperationsError("A recommendation needs a non-empty queue; use no_work or abstain for an empty queue.")
        return model

    def reveal_model(self, token, interview_id, expected_version, model_snapshot):
        with self._tx():
            user, _ = self._auth(token, ("dispatcher",))
            record = self._get(interview_id, "interview")
            self._expected(record, expected_version)
            if record["data"]["model_reveal"] is not None:
                raise OperationsError("The model ranking was already disclosed and sealed.")
            model = self._model(model_snapshot)
            if model["site_package_sha256"] != record["data"]["site_package_sha256"]:
                raise OperationsError("The model artifact belongs to a different site package.")
            site = self._get(record["data"]["site_id"], "site")
            if site["data"]["validation"].get("valid"):
                job_ids = {job["id"] for job in site["data"]["package"]["jobs"]}
                if not set(model["result"]["queue"]).issubset(job_ids):
                    raise OperationsError("The model queue contains a job outside the staged valid site package.")
            reveal = {"snapshot": model, "snapshot_sha256": canonical_sha256(model),
                      "revealed_at": _iso(self._now()), "baseline_sha256": canonical_sha256(record["data"]["baseline_plan"]),
                      "baseline_record_sha256": record["sha256"],
                      "disclosure_scope": "Application ordering recorded; prior off-platform disclosure cannot be independently excluded."}
            return self._save("interview", dict(record["data"], model_reveal=reveal, status="model_revealed_baseline_locked"),
                              user["id"], "model_disclosed_after_baseline", record=record)

    def record_interview_review(self, token, interview_id, expected_version, feedback, attachment_ids=()):
        with self._tx():
            user, _ = self._auth(token, ("reviewer",))
            record = self._get(interview_id, "interview")
            self._expected(record, expected_version)
            if record["data"]["model_reveal"] is None:
                raise OperationsError("Record the baseline and model disclosure before the comparative operator review.")
            if record["data"]["operator_review"] is not None:
                raise OperationsError("The comparative review is already recorded.")
            review = {"feedback": _text(feedback, "Operator feedback and disagreements"),
                      "attachments": self._attachments(attachment_ids, required=True),
                      "reviewer_id": user["id"], "recorded_at": _iso(self._now()),
                      "status": "review_recorded_for_discussion_participation_not_independently_verified"}
            return self._save("interview", dict(record["data"], operator_review=review), user["id"],
                              "operator_comparison_review_recorded", record=record)

    def _inputs(self, inputs, decision):
        if not isinstance(inputs, list) or not inputs or len(inputs) > 1000:
            raise OperationsError("A shadow decision needs 1–1000 explicit available-input records.")
        copied, identifiers = _copy(inputs), set()
        for item in copied:
            if not isinstance(item, dict):
                raise OperationsError("Every available input must be an object.")
            identifier = _text(item.get("id"), "Input identifier", 200)
            if identifier in identifiers:
                raise OperationsError("Available input identifiers must be unique.")
            identifiers.add(identifier)
            _text(item.get("source"), "Input source")
            if "value" not in item:
                raise OperationsError("Inputs need an explicit value; use null for unknown observations.")
            timestamps = [_time(item.get(key), f"Input {key}") for key in ("observed_at", "issued_at", "available_at")]
            if any(t > decision for t in timestamps) or max(timestamps[:2]) > timestamps[2]:
                raise OperationsError("Future-dated or later-issued information cannot enter a shadow decision.")
            self._attachments(item.get("attachment_ids", []), cutoff=decision)
        return copied

    def create_shadow(self, token, site_id, interview_id, available_inputs, protocol, *,
                      decision_at=None, operator_plan=None, model_snapshot=None, attachment_ids=(), mode="SHADOW"):
        with self._tx():
            user, _ = self._auth(token, ("dispatcher",))
            if mode != "SHADOW":
                raise OperationsError("Only SHADOW recordkeeping is supported; this API cannot activate or authorise live work or a pilot.")
            now = self._now()
            decision = now if decision_at is None else _time(decision_at, "Decision time")
            if decision > now or (now - decision).total_seconds() > MAX_DECISION_AGE_SECONDS:
                raise OperationsError("Prospective decisions must be captured now (at most 5 minutes old), never backfilled or future-dated.")
            site, interview = self._get(site_id, "site"), self._get(interview_id, "interview")
            if interview["data"]["site_id"] != site_id:
                raise OperationsError("The operator baseline belongs to another site package.")
            reveal = interview["data"]["model_reveal"]
            if reveal is None:
                raise OperationsError("Record and seal the operator baseline, then disclose the model before sealing a shadow decision.")
            if reveal["snapshot"]["site_package_sha256"] != site["data"]["package_sha256"]:
                raise OperationsError("The disclosed model artifact is not bound to this site package.")
            if (site["data"]["validation"].get("valid")
                and _time(site["data"]["package"]["created_at"], "Site package creation time")
                > _time(reveal["snapshot"]["generated_at"], "Model generation time")):
                raise OperationsError("The model cannot use a site package created after its declared generation time.")
            if any(_time(value, "Decision evidence time") > decision for value in (
                interview["data"]["baseline_recorded_at"], reveal["revealed_at"], reveal["snapshot"]["generated_at"])):
                raise OperationsError("Baseline/model disclosure occurred after the declared decision time.")
            if operator_plan is not None and canonical_sha256(_baseline(operator_plan)) != reveal["baseline_sha256"]:
                raise OperationsError("The operator plan differs from the baseline sealed before model disclosure.")
            if model_snapshot is not None and canonical_sha256(self._model(model_snapshot)) != reveal["snapshot_sha256"]:
                raise OperationsError("The model snapshot differs from the sealed disclosure.")
            # A snapshot cannot have used information which only became
            # available between its generation and the later decision capture.
            inputs = self._inputs(available_inputs, _time(reveal["snapshot"]["generated_at"], "Model generation time"))
            if input_snapshot_sha256(inputs) != reveal["snapshot"]["inputs_sha256"]:
                raise OperationsError("Available inputs do not match the model's frozen input fingerprint.")
            if not isinstance(protocol, dict):
                raise OperationsError("A shadow protocol must be an object.")
            protocol = _copy(protocol)
            for key in ("protocol_id", "objective", "stopping_rules", "exception_rules", "outcome_plan"):
                _text(protocol.get(key), f"Shadow protocol {key}")
            if any(r["data"]["interview_id"] == interview_id for r in self._latest("shadow")):
                raise OperationsError("This baseline has already been used in a shadow decision; capture a new baseline for each decision.")
            # Input declarations are checked against server capture, but external
            # truth/availability still needs independent provenance review.
            sealed = {"mode": "SHADOW", "site_id": site_id,
                      "evidence_kind": site["data"]["validation"].get("evidence_kind", "unknown"),
                      "contract_coherence": "matched_declared_site_contract" if site["data"]["validation"].get("valid") else "draft_site_unvalidated",
                      "site_record_sha256": site["sha256"], "site_package_sha256": site["data"]["package_sha256"],
                      "interview_id": interview_id, "interview_sha256": interview["sha256"],
                      "decision_at": _iso(decision), "sealed_at": _iso(now),
                      "available_inputs": inputs, "inputs_sha256": input_snapshot_sha256(inputs),
                      "operator_plan": interview["data"]["baseline_plan"], "operator_constraints": interview["data"]["constraints"],
                      "model_snapshot": reveal["snapshot"], "model_snapshot_sha256": reveal["snapshot_sha256"],
                      "protocol": protocol, "protocol_sha256": canonical_sha256(protocol),
                      "attachments": self._attachments(attachment_ids, cutoff=decision),
                      "operational_activation_allowed": False, "pilot_authorised": False,
                      "input_provenance_status": "declared_timestamps_not_independently_verified"}
            return self._save("shadow", {**sealed, "decision_seal_sha256": canonical_sha256(sealed),
                                        "outcome_ids": [], "outcome_status": "unresolved_missing"},
                              user["id"], "prospective_shadow_sealed")

    def record_outcome(self, token, shadow_id, expected_version, status, observed_at, observations,
                       notes, attachment_ids=()):
        with self._tx():
            user, _ = self._auth(token, ("observer", "inspector"))
            shadow = self._get(shadow_id, "shadow")
            self._expected(shadow, expected_version)
            if status not in ("observed", "missing", "error"):
                raise OperationsError("Outcome status must be observed, missing, or error.")
            if shadow["data"]["outcome_status"] == "observed":
                raise OperationsError("Observed outcomes are immutable; record corrections as a new explicitly linked study.")
            observed = _time(observed_at, "Outcome observation time")
            if observed <= _time(shadow["data"]["sealed_at"], "Decision seal time") or observed > self._now():
                raise OperationsError("Outcomes must be observed after the decision was sealed and no later than now.")
            if not isinstance(observations, dict):
                raise OperationsError("Outcome observations must be an object, with unknowns preserved as null.")
            observations = _copy(observations)
            attachments = self._attachments(attachment_ids, required=status == "observed")
            if status == "observed":
                for key in ("executed_plan", "completed_jobs", "exceptions", "measured_response", "planning_minutes", "crew_minutes"):
                    if key not in observations:
                        raise OperationsError(f"Observed outcome is missing explicit field {key}; use null when unknown.")
                if observations["executed_plan"] is None:
                    raise OperationsError("An observed trial needs the actual executed plan; otherwise retain missing/error status.")
                _queue(observations["executed_plan"], "Executed plan")
                _queue(observations["completed_jobs"], "Completed jobs")
                if not set(observations["completed_jobs"]).issubset(observations["executed_plan"]):
                    raise OperationsError("Completed jobs must belong to the actually executed plan.")
                if not isinstance(observations["exceptions"], list):
                    raise OperationsError("Observed exceptions must be an explicit list, including an empty list when none are reported.")
                authorised = shadow["data"]["operator_constraints"]["authorised_jobs"]
                if authorised is not None:
                    for job_id in set(observations["executed_plan"]) - set(authorised):
                        if not any(isinstance(item, dict) and item.get("type") == "unplanned_job"
                                   and item.get("job_id") == job_id and isinstance(item.get("reason"), str)
                                   and item["reason"].strip() for item in observations["exceptions"]):
                            raise OperationsError("Executed jobs outside the recorded authorised set need a documented unplanned_job exception with job_id and reason.")
                if observations["measured_response"] is not None and not isinstance(observations["measured_response"], dict):
                    raise OperationsError("Measured response must be a structured object or null for missing measurements.")
                for key in ("planning_minutes", "crew_minutes"):
                    value = observations[key]
                    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                        raise OperationsError(f"{key} must be finite non-negative minutes or null for unknown.")
                for linked in attachments:
                    source = self._get(linked["id"], "attachment")
                    evidence_time = _time(source["data"]["observed_at"], "Outcome evidence time")
                    if evidence_time <= _time(shadow["data"]["sealed_at"], "Decision seal time"):
                        raise OperationsError("Observed outcome evidence must have been collected after the shadow decision was sealed.")
                    if evidence_time > observed:
                        raise OperationsError("Outcome evidence cannot postdate the declared outcome observation time.")
            outcome = self._save("outcome", {"site_id": shadow["data"]["site_id"], "shadow_id": shadow_id,
                                "decision_seal_sha256": shadow["data"]["decision_seal_sha256"],
                                "status": status, "observed_at": _iso(observed), "observations": observations,
                                "notes": _text(notes, "Outcome notes"), "attachments": attachments,
                                "counterfactual_benefit_established": False,
                                "scope": "Reported observed plan only; model counterfactuals are not measured flood reductions."},
                                user["id"], "shadow_outcome_recorded")
            self._save("shadow", dict(shadow["data"], outcome_ids=shadow["data"]["outcome_ids"] + [outcome["id"]],
                                      outcome_status="observed" if status == "observed" else "unresolved_" + status),
                       user["id"], "shadow_outcome_linked", record=shadow)
            return outcome

    def record_evidence_review(self, token, site_id, category, assessment, notes, attachment_ids,
                               *, engineer_name=None, qualification_reference=None):
        with self._tx():
            user, _ = self._auth(token, ("reviewer", "inspector"))
            site = self._get(site_id, "site")
            if category not in EVIDENCE_CATEGORIES or assessment not in ("accepted_for_discussion", "unresolved", "rejected"):
                raise OperationsError("Use a declared evidence category and accepted_for_discussion, unresolved, or rejected assessment.")
            if category == "engineer_review":
                engineer_name = _text(engineer_name, "Named responsible engineer", 200)
                qualification_reference = _text(qualification_reference, "Qualification and verification reference")
            return self._save("evidence_review", {"site_id": site_id, "site_package_sha256": site["data"]["package_sha256"],
                               "category": category, "assessment": assessment, "notes": _text(notes, "Evidence review notes"),
                               "attachments": self._attachments(attachment_ids, required=True),
                               "engineer_name": engineer_name, "qualification_reference": qualification_reference,
                               "qualification_status": "reported_not_independently_verified" if category == "engineer_review" else None,
                               "operational_activation_allowed": False, "pilot_authorised": False},
                               user["id"], "readiness_evidence_review_recorded")

    def readiness(self, token, site_id):
        with self._tx(write=False):
            self._auth(token)
            site = self._get(site_id, "site")
            interviews = [r for r in self._latest("interview") if r["data"]["site_id"] == site_id]
            shadows = [r for r in self._latest("shadow") if r["data"]["site_id"] == site_id]
            reviews = [r for r in self._latest("evidence_review") if r["data"]["site_id"] == site_id]
            latest_reviews = {r["data"]["category"]: r for r in reviews}
            gaps = []
            if not site["data"]["validation"].get("valid"):
                gaps.append({"code": "site_contract_invalid", "message": "Correct the site package contract errors."})
            if site["data"]["review"] is None:
                gaps.append({"code": "site_review_missing", "message": "An independent authenticated reviewer has not reviewed this staged package."})
            reviewed_interviews = [r for r in interviews if r["data"]["operator_review"] is not None]
            if not reviewed_interviews:
                gaps.append({"code": "operator_review_missing", "message": "A baseline captured before disclosure and a documented operator comparison review are missing."})
            if not any(all(r["data"]["constraints"].get(key) is not None for key in CONSTRAINT_FIELDS) for r in reviewed_interviews):
                gaps.append({"code": "operating_inputs_incomplete", "message": "A reviewed operator baseline with all six explicit operating constraint fields is missing."})
            for category in EVIDENCE_CATEGORIES:
                review = latest_reviews.get(category)
                if review is None or review["data"]["assessment"] != "accepted_for_discussion":
                    gaps.append({"code": category + "_missing_or_unresolved", "message": category.replace("_", " ").capitalize() + " evidence has not been accepted for readiness discussion."})
            observed = [r for r in shadows if r["data"]["outcome_status"] == "observed"]
            synthetic = [r for r in observed if r["data"]["evidence_kind"] == "synthetic_fixture"]
            reported_measured = [r for r in observed if r["data"]["evidence_kind"] == "supplied_survey"
                                 and r["data"]["contract_coherence"] == "matched_declared_site_contract"]
            unresolved = [r for r in shadows if r["data"]["outcome_status"] != "observed"]
            if not reported_measured:
                gaps.append({"code": "observed_shadow_missing", "message": "No prospective sealed shadow decision for a reported measured site has a documented later reported outcome; synthetic fixtures do not supply field evidence."})
            for shadow in reported_measured:
                outcome = self._get(shadow["data"]["outcome_ids"][-1], "outcome")
                if outcome["data"]["observations"].get("measured_response") in (None, {}):
                    gaps.append({"code": "shadow_response_measurements_missing", "message": "A reported observed plan still lacks measured physical response."})
                    break
            if unresolved:
                gaps.append({"code": "shadow_outcomes_unresolved", "message": f"{len(unresolved)} shadow decision(s) retain missing or error outcomes."})
            gaps.append({"code": "external_engineering_authority_required", "message": "Professional identity, physical validity, site permission and any supervised pilot envelope require independent responsible engineering review outside this local recordkeeper."})
            return {"site_id": site_id, "mode": "RESEARCH_SHADOW_ONLY", "status": "not_authorised_for_field_use",
                    "documentary_gaps": gaps, "research_recordkeeping_gaps": [g for g in gaps if g["code"] != "external_engineering_authority_required"],
                    "evidence_kind": site["data"]["validation"].get("evidence_kind", "unknown"),
                    "observed_shadow_count": len(reported_measured), "reported_measured_count": len(reported_measured),
                    "synthetic_fixture_count": len(synthetic), "recorded_observed_status_count": len(observed),
                    "unresolved_shadow_count": len(unresolved),
                    "evidence_review_statuses": {key: value["data"]["assessment"] for key, value in latest_reviews.items()},
                    "operator_participation_independently_verified": False, "professional_identity_verified": False,
                    "physical_validation_established": False, "counterfactual_benefit_established": False,
                    "operational_activation_allowed": False, "pilot_authorised": False,
                    "legacy_ticket_authentication_covered": False}

    def export_site(self, token, site_id):
        with self._tx(write=False):
            self._auth(token)
            self._get(site_id, "site")
            records = [r for r in self._latest() if r["id"] == site_id or r["data"].get("site_id") == site_id]
            return {"schema_version": self.SCHEMA_VERSION, "exported_at": _iso(self._now()),
                    "scope": "Research/shadow evidence; no credentials or attachment bytes included.",
                    "records": records, "store_integrity": self._verify(), "operational_activation_allowed": False}

    def backup(self, token, destination):
        """Write a consistent verified SQLite backup to a NEW path; never overwrite."""
        target = Path(destination).expanduser().resolve()
        with self._lock:
            # A read transaction authenticates one consistent source snapshot.
            with self._tx(write=False):
                self._auth(token, ("admin",))
                integrity = self._verify()
                if target.exists() or (self.db_path != ":memory:" and target == Path(self.db_path).resolve()):
                    raise OperationsError("Backups must use a new path; existing files are never overwritten.")
                target.parent.mkdir(parents=True, exist_ok=True)
                # Exclusive creation closes the check/create race.
                with target.open("xb"):
                    pass
                destination_db = sqlite3.connect(str(target))
                try:
                    self._db.backup(destination_db)
                finally:
                    destination_db.close()
            checked = self._verify_file(target)
            if checked["head_sha256"] != integrity["head_sha256"]:
                raise IntegrityError("The backup does not match the captured source revision.")
            return {"path": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "integrity": checked, "contains_password_hashes_and_session_hashes": True}

    @classmethod
    def _verify_file(cls, path):
        # Read-only inspection: do not repair a corrupt/foreign backup by creating
        # missing schema or triggers before deciding whether it is valid.
        connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            if connection.execute("PRAGMA application_id").fetchone()[0] != cls.APPLICATION_ID or connection.execute("PRAGMA user_version").fetchone()[0] != cls.SCHEMA_VERSION:
                raise IntegrityError("Backup is not a compatible operations database.")
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise IntegrityError("SQLite integrity checking failed.")
            instance = object.__new__(cls)
            instance._db = connection
            return instance._verify()
        except sqlite3.DatabaseError as exc:
            raise IntegrityError("Backup database is corrupt or incomplete.") from exc
        finally:
            connection.close()

    def restore_new(self, token, backup_path, destination):
        """Admin restores a verified backup into a NEW DB; all restored sessions revoke."""
        with self._tx(write=False):
            actor, _ = self._auth(token, ("admin",))
        source, target = Path(backup_path).resolve(), Path(destination).resolve()
        if not source.is_file() or source == target or target.exists():
            raise OperationsError("Restore requires an existing backup and a new destination; it never replaces the live database.")
        self._verify_file(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Copy via SQLite's backup API, not a file copy that could omit WAL data.
        with target.open("xb"):
            pass
        source_db = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        target_db = sqlite3.connect(str(target))
        try:
            source_db.backup(target_db)
        finally:
            source_db.close()
            target_db.close()
        self._verify_file(target)
        restored = OperationsStore(target, session_seconds=self.session_seconds, clock=self._clock)
        try:
            with restored._tx():
                restored._verify()
                for session in restored._latest("session"):
                    if not session["data"]["revoked"]:
                        restored._save("session", dict(session["data"], revoked=True), "restore:" + actor["id"],
                                       "restore_revoked_session", record=session)
                restored._save("restore", {"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                                          "sessions_revoked": True, "live_database_replaced": False},
                               "restore:" + actor["id"], "verified_restore_to_new_database")
                integrity = restored._verify()
        finally:
            restored.disconnect()
        return {"path": str(target), "integrity": integrity, "all_sessions_revoked": True,
                "live_database_replaced": False}
