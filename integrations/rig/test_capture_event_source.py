import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from capture_event_source import select_event


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.source = self.home / ".pi/agent/sessions/session.jsonl"
        self.source.parent.mkdir(parents=True)
        self.source.write_text(json.dumps({"type": "session", "id": "s"})+"\n"+json.dumps({"type": "message", "id": "native-1", "message": {"role": "user", "content": "Safe fixture"}})+"\n")
        self.root = self.home / ".local/state/pi-memory-capture"
        (self.root / "exports").mkdir(parents=True)
        self.refresh()
        self.export = self.root / "exports" / (hashlib.sha256(str(self.source.resolve()).encode()).hexdigest()[:16]+"-session.md")
        self.export.write_text("Sanitized fixture export")

    def refresh(self):
        stat = self.source.stat()
        (self.root / "sources.json").write_text(json.dumps({str(self.source.resolve()): [stat.st_size, stat.st_mtime_ns]}))

    def tearDown(self): self.tmp.cleanup()

    def test_exact_selected_native_event_has_source_provenance(self):
        out = select_event(self.home, self.source, "native-1", "s")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["record"]["id"], "native-1")
        self.assertEqual(out["ordinal"], 2)
        self.assertGreater(out["byte_offset"], 0)

    def test_append_requires_capture_owner_refresh(self):
        with self.source.open("a") as file: file.write(json.dumps({"type": "message", "id": "native-2"})+"\n")
        self.assertEqual(select_event(self.home, self.source, "native-1", "s")["reason"], "capture_source_not_current")
        self.refresh()
        self.assertEqual(select_event(self.home, self.source, "native-1", "s")["record"]["id"], "native-1")

    def test_missing_capture_is_unavailable(self):
        self.export.unlink()
        self.assertEqual(select_event(self.home, self.source, "native-1", "s")["status"], "unavailable")

    def test_cross_session_identity_fails_closed(self):
        self.assertEqual(select_event(self.home, self.source, "native-1", "other")["reason"], "native_session_identity_mismatch")

    def test_missing_event_is_unavailable_not_empty(self):
        self.assertEqual(select_event(self.home, self.source, "absent", "s")["reason"], "native_event_not_found")

    def test_outside_path_is_unavailable(self):
        self.assertEqual(select_event(self.home, self.home / "outside", "id", "s")["reason"], "source_outside_native_capture")


if __name__ == "__main__": unittest.main()
