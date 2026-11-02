"""File-only observer preparation. Explicit events; no replay, network or scheduler."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

NORMALIZER = "pi-public-text/v1"


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def public_text(record):
    if record.get("type") != "message":
        return None, "not_native_message"
    message = record.get("message")
    if not isinstance(message, dict) or message.get("role") not in ("user", "assistant"):
        return None, "not_public_dialogue_role"
    channel = message.get("channel")
    if channel is not None and channel not in ("final", "commentary"):
        return None, "nonpublic_channel"
    content = message.get("content")
    if isinstance(content, str) and message["role"] == "user":
        return content, None
    if not isinstance(content, list):
        return None, "unsupported_content"
    # Qualified Pi1.0.1 UI renders content.type=text separately from thinking.
    # Missing channel here is covered by that native typed-block contract, not
    # a general permission to ingest arbitrary assistant/provider payloads.
    parts = [item["text"] for item in content if isinstance(item, dict)
             and item.get("type") == "text" and isinstance(item.get("text"), str)]
    text = "\n".join(parts)
    return (text, None) if text.strip() else (None, "no_public_text")


def prepare(record, *, session, account, project, source, ordinal, redact,
            redaction_version, reviewed_non_sensitive=False, observed=None):
    text, excluded = public_text(record)
    if excluded:
        return {"status": "excluded", "reason": excluded}
    native_id = record.get("id")
    if not isinstance(native_id, str) or not native_id:
        return {"status": "quarantined", "reason": "missing_native_event_id"}
    if not all(isinstance(value, str) and value for value in (session, account, project, source, redaction_version)):
        raise ValueError("source scope and redactor identity required")
    if not text.strip() or len(text) > 12000:
        return {"status": "quarantined", "reason": "empty_or_oversize_public_text"}
    sanitized = redact(text)
    if not isinstance(sanitized, str) or len(sanitized) > 12000:
        return {"status": "quarantined", "reason": "redactor_invalid_output"}
    logical = digest("\0".join(("pi", account, session, native_id)))
    source_sha = digest(text)
    version = digest("\0".join((logical, source_sha, NORMALIZER, redaction_version, digest(sanitized))))
    message = record["message"]
    provenance = {"logical_event_id": logical, "version_id": version,
                  "platform": "pi", "account_scope": account, "project_scope": project,
                  "native_session_id": session, "native_message_id": native_id,
                  "parent_message_id": record.get("parentId"), "parent_session_id": None,
                  "original_ordinal": ordinal, "source_locator": source + "#record/" + native_id,
                  "source_content_sha256": source_sha, "sanitized_body_sha256": digest(sanitized),
                  "normalizer_version": NORMALIZER, "redaction_version": redaction_version,
                  "source_timestamp": record.get("timestamp"),
                  "observed_timestamp": observed or datetime.now(timezone.utc).isoformat(),
                  "role": message["role"], "channel": message.get("channel") or "pi_rendered_text",
                  "authored_or_generated": "user_role_origin_unverified" if message["role"] == "user" else "model_generated",
                  "trust_class": "untrusted_source_evidence", "verification_status": "unverified",
                  "privacy_eligibility": "reviewed_non_sensitive" if reviewed_non_sensitive else "review_required",
                  "training_eligibility": "not_approved", "truncated": False}
    observer = {"contentSessionId": session, "platformSource": "pi", "tool_name": "public_dialogue",
                "tool_use_id": logical + ":" + version,
                "tool_input": provenance,
                "tool_response": {"text": sanitized, "truncated": False, "original_chars": len(text)}}
    return {"schema": "rig-observer-event/v1", "status": "prepared", "provenance": provenance,
            "observer_event": observer, "supersedes_versions": []}


@contextmanager
def lock(root):
    root = Path(root)
    if root.is_symlink():
        raise ValueError("outbox cannot be a symlink")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    file = root / "outbox.lock"
    if file.is_symlink():
        raise ValueError("outbox lock cannot be a symlink")
    with file.open("a+b") as stream:
        os.chmod(file, 0o600)
        if os.name == "nt":
            import msvcrt
            stream.write(b"\0"); stream.flush(); stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield root
        finally:
            if os.name == "nt":
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def atomic(path, value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try: os.fsync(directory_fd)
            finally: os.close(directory_fd)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def identity(event):
    provenance = event["provenance"]
    logical, version = provenance["logical_event_id"], provenance["version_id"]
    if not all(re.fullmatch(r"[0-9a-f]{64}", v) for v in (logical, version)):
        raise ValueError("invalid event identity")
    return logical + "-" + version


def validate(event):
    key = identity(event)
    p = event["provenance"]
    observer = event["observer_event"]
    body = observer["tool_response"]["text"]
    logical = digest("\0".join(("pi", p["account_scope"], p["native_session_id"], p["native_message_id"])))
    version = digest("\0".join((logical, p["source_content_sha256"], p["normalizer_version"],
                                  p["redaction_version"], digest(body))))
    if (logical != p["logical_event_id"] or version != p["version_id"]
            or digest(body) != p["sanitized_body_sha256"]
            or observer["tool_use_id"] != logical + ":" + version
            or observer["tool_input"] != p or len(body) > 12000):
        raise ValueError("event body/provenance integrity mismatch")
    return key


def private_directory(path):
    if path.is_symlink(): raise ValueError("outbox directory cannot be a symlink")
    path.mkdir(exist_ok=True, mode=0o700)
    return path


def enqueue(root, event):
    if event.get("status") != "prepared" or event.get("schema") != "rig-observer-event/v1":
        raise ValueError("only prepared source events may enter outbox")
    key = validate(event)
    with lock(root) as root:
        events = private_directory(root / "events")
        path = events / (key + ".json")
        if path.exists():
            if path.is_symlink(): raise ValueError("event cannot be a symlink")
            existing = json.loads(path.read_text(encoding="utf-8"))
            validate(existing)
            if existing["observer_event"] != event["observer_event"]:
                # Observed timestamp can differ on re-reading the same source;
                # substantive body/source identity must remain unchanged.
                left = json.loads(json.dumps(existing["observer_event"]))
                right = json.loads(json.dumps(event["observer_event"]))
                left["tool_input"].pop("observed_timestamp", None)
                right["tool_input"].pop("observed_timestamp", None)
                if left != right: raise ValueError("identity collision or scope drift")
            return {"status": "duplicate", "key": key}
        previous = []
        for other in events.glob(event["provenance"]["logical_event_id"] + "-*.json"):
            if other.is_symlink(): raise ValueError("event cannot be a symlink")
            stored = json.loads(other.read_text(encoding="utf-8"))
            validate(stored)
            previous.append(stored["provenance"]["version_id"])
        event = json.loads(json.dumps(event))
        event["supersedes_versions"] = sorted(previous)
        atomic(path, event)
        return {"status": "staged", "key": key, "supersedes_versions": sorted(previous)}


def pending(root):
    with lock(root) as root:
        try:
            directory = private_directory(root / "events")
            acks = private_directory(root / "acks")
            files = list(directory.glob("*.json"))
            if any(path.is_symlink() for path in files): raise ValueError("event symlink")
            events = [json.loads(path.read_text(encoding="utf-8")) for path in files]
            for event in events:
                key = validate(event)
                ack = acks / (key + ".json")
                if ack.exists():
                    if ack.is_symlink(): raise ValueError("ack symlink")
                    receipt = json.loads(ack.read_text(encoding="utf-8"))
                    readback = receipt["record_readback"]
                    expected = {"tool_use_id": event["observer_event"]["tool_use_id"],
                                "source_content_sha256": event["provenance"]["source_content_sha256"],
                                "sanitized_body_sha256": event["provenance"]["sanitized_body_sha256"]}
                    if receipt.get("event_key") != key or not receipt.get("receiver") or not readback.get("observation_ids"):
                        raise ValueError("ack identity mismatch")
                    if any(readback.get(field) != value for field, value in expected.items()):
                        raise ValueError("ack source mismatch")
        except (ValueError, KeyError, TypeError, OSError):
            return {"status": "unavailable", "pending": [], "delivery_eligible": 0,
                    "reason": "outbox_event_integrity_or_read_failed"}
        superseded = {(event["provenance"]["logical_event_id"], version)
                      for event in events for version in event["supersedes_versions"]}
        usable = [event for event in events
                  if (event["provenance"]["logical_event_id"], event["provenance"]["version_id"]) not in superseded
                  and not (root / "acks" / (identity(event) + ".json")).exists()]
        return {"status": "ok", "pending": usable,
                "delivery_eligible": sum(event["provenance"]["privacy_eligibility"] == "reviewed_non_sensitive" for event in usable),
                "ignored_incomplete_temporary_files": len(list((root / "events").glob(".pending-*")))}


def acknowledge(root, key, *, receiver, record_readback):
    if not re.fullmatch(r"[0-9a-f]{64}-[0-9a-f]{64}", key):
        raise ValueError("invalid acknowledgement identity")
    if not receiver or not isinstance(record_readback, dict) or not record_readback.get("observation_ids"):
        raise ValueError("receiver identity and fetched observation metadata required")
    with lock(root) as root:
        path = root / "events" / (key + ".json")
        if (root / "events").is_symlink() or path.is_symlink(): raise ValueError("event cannot be a symlink")
        if not path.exists(): raise ValueError("unknown event version")
        event = json.loads(path.read_text(encoding="utf-8"))
        validate(event)
        if event["provenance"]["privacy_eligibility"] != "reviewed_non_sensitive":
            raise ValueError("event privacy review not accepted")
        expected = {"tool_use_id": event["observer_event"]["tool_use_id"],
                    "source_content_sha256": event["provenance"]["source_content_sha256"],
                    "sanitized_body_sha256": event["provenance"]["sanitized_body_sha256"]}
        if any(record_readback.get(field) != value for field, value in expected.items()):
            raise ValueError("stored/fetched source readback mismatch")
        ids = record_readback["observation_ids"]
        if not isinstance(ids, list) or not all(isinstance(i, str) and i for i in ids):
            raise ValueError("invalid fetched observation IDs")
        acks = private_directory(root / "acks")
        receipt = {"schema": "rig-observer-ack/v1", "event_key": key, "receiver": receiver,
                   "record_readback": record_readback,
                   "meaning": "caller-supplied stored/fetched IDs and exact source hashes; not semantic verification"}
        file = acks / (key + ".json")
        if file.exists():
            if file.is_symlink(): raise ValueError("acknowledgement cannot be a symlink")
            if json.loads(file.read_text(encoding="utf-8")) != receipt: raise ValueError("acknowledgement collision")
            return {"status": "duplicate_ack", "key": key}
        atomic(file, receipt)
        return {"status": "acknowledged", "key": key}
