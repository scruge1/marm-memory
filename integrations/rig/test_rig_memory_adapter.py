import hashlib
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from rig_memory_adapter import read_memory


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "rig.db"
        self.body = "CallMeIE " + "original source body " * 100
        with closing(sqlite3.connect(self.db)) as c:
            c.execute("CREATE TABLE mem(id INTEGER PRIMARY KEY,text,tag,project,created_at)")
            c.execute("CREATE VIRTUAL TABLE mem_fts USING fts5(text,tag,project,content='mem',content_rowid='id')")
            c.executemany("INSERT INTO mem VALUES(?,?,?,?,?)", [(1,self.body,"test","urban","2026-10-03"), (2,"CallMeIE different tenant","test","hotel","2026-10-03")])
            c.execute("INSERT INTO mem_fts(mem_fts) VALUES('rebuild')")
            c.commit()

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_body_and_fetch_identity(self):
        search = read_memory(self.db, query="CallMeIE", project="urban")
        row = search["results"][0]
        self.assertEqual(row["body"], self.body)
        self.assertFalse(row["body_truncated"])
        self.assertEqual(row["source_sha256"], hashlib.sha256(self.body.encode()).hexdigest())
        fetched = read_memory(self.db, record_id=row["id"])
        self.assertEqual(fetched["results"][0], row)

    def test_project_scope(self):
        self.assertEqual([r["id"] for r in read_memory(self.db, query="CallMeIE", project="urban")["results"]], ["1"])

    def test_result_limit_visible(self):
        out = read_memory(self.db, query="CallMeIE", limit=1)
        self.assertTrue(out["results_truncated"])
        self.assertIn("narrow", out["truncation_reason"])

    def test_body_limit_visible(self):
        out = read_memory(self.db, record_id=1, body_limit=100)["results"][0]
        self.assertTrue(out["body_truncated"])
        self.assertEqual(len(out["body"]), 100)
        self.assertEqual(out["body_characters"], len(self.body))

    def test_unknown_session_never_leaks_unscoped_results(self):
        self.assertEqual(read_memory(self.db, query="CallMeIE", session="other")["status"], "unsupported_scope")

    def test_unknown_platform(self):
        self.assertEqual(read_memory(self.db, query="CallMeIE", platform="codex")["results"], [])

    def test_sql_and_fts_injection_are_data(self):
        out = read_memory(self.db, query='" OR 1=1; DROP TABLE mem; --', project="urban' OR '1'='1")
        self.assertEqual(out["status"], "empty")
        self.assertEqual(read_memory(self.db, record_id=1)["status"], "ok")

    def test_missing_store_is_not_empty_and_not_created(self):
        missing = self.db.parent / "missing.db"
        self.assertEqual(read_memory(missing, query="x")["status"], "unavailable")
        self.assertFalse(missing.exists())

    def test_broken_schema_is_not_empty(self):
        other = self.db.parent / "broken.db"
        with closing(sqlite3.connect(other)) as c:
            c.execute("CREATE TABLE x(a)")
            c.commit()
        self.assertEqual(read_memory(other, query="x")["status"], "unavailable")

    def test_real_empty(self):
        self.assertEqual(read_memory(self.db, query="unrelatedzz")["status"], "empty")

    def test_invalid_long_query(self):
        self.assertEqual(read_memory(self.db, query="word "*65)["status"], "invalid_query")

    def test_invalid_record_id(self):
        with self.assertRaises(ValueError):
            read_memory(self.db, record_id="1 OR 1=1")

    def test_unicode_irish_name_keeps_body_and_identity(self):
        with closing(sqlite3.connect(self.db)) as c:
            c.execute("INSERT INTO mem VALUES(3,?,?,?,?)", ("Bríd Ní Bhraonáin in Galway", "test", "urban", "2026-10-03"))
            c.execute("INSERT INTO mem_fts(mem_fts) VALUES('rebuild')")
            c.commit()
        out = read_memory(self.db, query="Bríd", project="urban")
        self.assertEqual([r["id"] for r in out["results"]], ["3"])
        self.assertEqual(out["results"][0]["body"], "Bríd Ní Bhraonáin in Galway")
        self.assertEqual(read_memory(self.db, record_id=3)["results"][0], out["results"][0])

    def test_aggregate_body_budget_and_explicit_fetch(self):
        out = read_memory(self.db, query="CallMeIE", body_budget=100)
        self.assertLessEqual(sum(len(r["body"]) for r in out["results"]), 100)
        self.assertTrue(out["body_budget_exhausted"])
        clipped = next(r for r in out["results"] if r["body_truncated"])
        full = read_memory(self.db, record_id=clipped["id"], body_budget=32000)["results"][0]
        self.assertFalse(full["body_truncated"])
        self.assertEqual(full["source_sha256"], clipped["source_sha256"])

    def test_budget_bound(self):
        with self.assertRaises(ValueError):
            read_memory(self.db, query="CallMeIE", body_budget=1048577)


if __name__ == "__main__":
    unittest.main()

