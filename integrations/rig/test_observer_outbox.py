from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from observer_outbox import prepare, enqueue, pending, acknowledge


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "outbox"

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, text="A reusable fixture lesson.", native_id="native-1", reviewed=True):
        return prepare({"type": "message", "id": native_id, "parentId": "parent-1",
                        "timestamp": "2026-10-03T00:00:00Z",
                        "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "DO NOT LEARN"}, {"type": "text", "text": text}]}},
                       session="session-1", account="adam-rig", project="fixture", source="fixture.jsonl", ordinal=3,
                       redact=lambda value: value.replace("SECRET", "<REDACTED>"), redaction_version="fixture-redactor/v1",
                       reviewed_non_sensitive=reviewed)

    def readback(self, event):
        return {"observation_ids": ["fixture-row-1"],
                "tool_use_id": event["observer_event"]["tool_use_id"],
                "source_content_sha256": event["provenance"]["source_content_sha256"],
                "sanitized_body_sha256": event["provenance"]["sanitized_body_sha256"]}

    def test_append_preserves_old_native_identity(self):
        first = self.make(); again = self.make(); appended = self.make(native_id="native-2")
        self.assertEqual(first["provenance"]["logical_event_id"], again["provenance"]["logical_event_id"])
        self.assertNotEqual(first["provenance"]["logical_event_id"], appended["provenance"]["logical_event_id"])
        enqueue(self.root, first); enqueue(self.root, appended)
        self.assertEqual(len(pending(self.root)["pending"]), 2)

    def test_thinking_is_never_in_observer_event(self):
        event = self.make()
        self.assertNotIn("DO NOT LEARN", str(event))

    def test_correction_retains_history_supersedes_pending_version(self):
        old = self.make("Incorrect fixture"); new = self.make("Corrected fixture")
        enqueue(self.root, old); staged = enqueue(self.root, new)
        self.assertEqual(old["provenance"]["logical_event_id"], new["provenance"]["logical_event_id"])
        self.assertNotEqual(old["provenance"]["version_id"], new["provenance"]["version_id"])
        self.assertEqual(staged["supersedes_versions"], [old["provenance"]["version_id"]])
        self.assertEqual(len(list((self.root / "events").glob("*.json"))), 2)
        self.assertEqual(pending(self.root)["pending"][0]["observer_event"]["tool_response"]["text"], "Corrected fixture")

    def test_duplicate_redelivery_deduplicates_without_overwrite(self):
        first = enqueue(self.root, self.make())
        second = enqueue(self.root, self.make())
        self.assertEqual(first["key"], second["key"])
        self.assertEqual(second["status"], "duplicate")
        self.assertEqual(len(pending(self.root)["pending"]), 1)

    def test_crash_before_rename_retries_without_partial_event(self):
        with patch("observer_outbox.os.replace", side_effect=OSError("fixture crash")):
            with self.assertRaises(OSError): enqueue(self.root, self.make())
        self.assertEqual(pending(self.root)["pending"], [])
        self.assertEqual(enqueue(self.root, self.make())["status"], "staged")

    def test_crash_after_staging_before_ack_leaves_retryable_event(self):
        event = self.make(); key = enqueue(self.root, event)["key"]
        self.assertEqual(len(pending(self.root)["pending"]), 1)
        self.assertEqual(enqueue(self.root, self.make())["status"], "duplicate")
        acknowledge(self.root, key, receiver="fixture", record_readback=self.readback(event))
        self.assertEqual(pending(self.root)["pending"], [])

    def test_ack_requires_exact_stored_fetched_source_readback(self):
        event = self.make(); key = enqueue(self.root, event)["key"]
        with self.assertRaises(ValueError): acknowledge(self.root, key, receiver="fixture", record_readback={"http_status": 200})
        wrong = self.readback(event); wrong["source_content_sha256"] = "wrong"
        with self.assertRaises(ValueError): acknowledge(self.root, key, receiver="fixture", record_readback=wrong)
        self.assertEqual(len(pending(self.root)["pending"]), 1)

    def test_ack_is_idempotent_and_scope_bound(self):
        event = self.make(); key = enqueue(self.root, event)["key"]
        args = {"receiver": "fixture", "record_readback": self.readback(event)}
        self.assertEqual(acknowledge(self.root, key, **args)["status"], "acknowledged")
        self.assertEqual(acknowledge(self.root, key, **args)["status"], "duplicate_ack")
        with self.assertRaises(ValueError): acknowledge(self.root, "0"*64+"-"+"1"*64, **args)

    def test_review_required_never_delivery_eligible_or_acknowledged(self):
        event = self.make(reviewed=False); key = enqueue(self.root, event)["key"]
        self.assertEqual(pending(self.root)["delivery_eligible"], 0)
        with self.assertRaises(ValueError): acknowledge(self.root, key, receiver="fixture", record_readback=self.readback(event))

    def test_secret_redacted_and_original_body_not_stored(self):
        event = self.make("SECRET fixture")
        self.assertEqual(event["observer_event"]["tool_response"]["text"], "<REDACTED> fixture")
        self.assertNotIn("SECRET", str(event))

    def test_internal_peer_tool_and_analysis_excluded(self):
        for record in ({"type": "custom_message", "content": "peer"},
                       {"type": "message", "message": {"role": "toolResult"}},
                       {"type": "message", "message": {"role": "assistant", "channel": "analysis", "content": [{"type": "text", "text": "internal"}]}}):
            result = prepare(record, session="s", account="a", project="p", source="x", ordinal=1, redact=str, redaction_version="v1")
            self.assertEqual(result["status"], "excluded")

    def test_missing_identity_quarantined(self):
        record = {"type": "message", "message": {"role": "user", "content": "public"}}
        result = prepare(record, session="s", account="a", project="p", source="x", ordinal=1, redact=str, redaction_version="v1")
        self.assertEqual(result["reason"], "missing_native_event_id")

    def test_oversize_does_not_silently_clip(self):
        self.assertEqual(self.make("x"*12001)["status"], "quarantined")

    def test_corrupt_body_not_silently_delivered_or_empty(self):
        import json
        event = self.make(); key = enqueue(self.root, event)["key"]
        path = self.root / "events" / (key+".json")
        value = json.loads(path.read_text()); value["observer_event"]["tool_response"]["text"] = "corruption"
        path.write_text(json.dumps(value))
        self.assertEqual(pending(self.root)["status"], "unavailable")
        self.assertEqual(pending(self.root)["delivery_eligible"], 0)

    def test_corrupt_json_is_unavailable(self):
        key = enqueue(self.root, self.make())["key"]
        (self.root / "events" / (key+".json")).write_text("partial corrupted json")
        self.assertEqual(pending(self.root)["status"], "unavailable")

    def test_corrupt_ack_cannot_hide_pending_source(self):
        event = self.make(); key = enqueue(self.root, event)["key"]
        acknowledge(self.root, key, receiver="fixture", record_readback=self.readback(event))
        (self.root / "acks" / (key+".json")).write_text('{"event_key":"wrong"}')
        self.assertEqual(pending(self.root)["status"], "unavailable")


if __name__ == "__main__": unittest.main()
