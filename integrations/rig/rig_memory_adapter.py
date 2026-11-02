"""Read existing rig memory without silently clipping source bodies or creating DBs."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3

SCHEMA = "cross-harness-memory/v1"


def envelope(status, results=None, **details):
    return {"schema": SCHEMA, "status": status, "results": results or [],
            "authority": "historical_discovery_only", **details}


def record(row, db, body_limit=None):
    full = row["text"] or ""
    body = full if body_limit is None else full[:body_limit]
    return {"store": "rig-memory", "id": str(row["id"]),
            "source_path": db.resolve().as_uri() + "#mem/" + str(row["id"]),
            "source_sha256": hashlib.sha256(full.encode("utf-8")).hexdigest(),
            "body": body, "body_characters": len(full),
            "body_truncated": len(body) < len(full),
            "project": row["project"], "session": None, "platform": "rig",
            "tag": row["tag"], "source_timestamp": row["created_at"],
            "timestamp_timezone": "unspecified_by_source",
            "evidence_class": "raw_history", "state": "unknown"}


def read_memory(db, query=None, record_id=None, project=None, session=None,
                platform=None, limit=8, body_limit=None, body_budget=32000):
    if (not 1 <= limit <= 50 or (body_limit is not None and body_limit < 1)
            or not 1 <= body_budget <= 1048576):
        raise ValueError("invalid result/body limit")
    if (query is None) == (record_id is None):
        raise ValueError("provide exactly one of query or record_id")
    # The existing mem schema does not attribute individual sessions. Do not
    # manufacture a successful scoped query from unscoped records.
    if session is not None or (platform is not None and platform != "rig"):
        return envelope("unsupported_scope", scope={"session": session, "platform": platform})
    db = Path(db)
    if not db.is_file():
        return envelope("unavailable", reason="database_missing")
    sql = "SELECT m.id,m.text,m.tag,m.project,m.created_at FROM mem m"
    values = []
    if record_id is not None:
        if not str(record_id).isdigit():
            raise ValueError("record_id must be numeric")
        sql += " WHERE m.id=?"
        values.append(int(record_id))
        mode = "source_fetch"
    else:
        terms = re.findall(r"\w+", query or "", flags=re.UNICODE)
        if not terms:
            return envelope("invalid_query", reason="no_searchable_terms")
        if len(terms) > 64:
            return envelope("invalid_query", reason="query_exceeds_64_terms")
        match = " OR ".join('"' + t + '"' for t in terms)
        sql += " JOIN mem_fts ON mem_fts.rowid=m.id WHERE mem_fts MATCH ?"
        values.append(match)
        mode = "lexical_fts"
    if project is not None:
        sql += " AND m.project=?"
        values.append(project)
    sql += " ORDER BY m.id DESC LIMIT ?"
    values.append(limit + 1)
    try:
        # URI mode=ro cannot create a new store. Do not use immutable=1: it
        # ignores live WAL content and can return an obsolete generation.
        with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as con:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA query_only=ON")
            rows = con.execute(sql, values).fetchall()
    except sqlite3.Error as error:
        return envelope("unavailable", reason="database_read_failed",
                        error_type=type(error).__name__, retrieval_mode=mode)
    results = []
    remaining = body_budget
    for row in rows[:limit]:
        row_limit = remaining if body_limit is None else min(remaining, body_limit)
        item = record(row, db, row_limit)
        remaining -= len(item["body"])
        results.append(item)
    return envelope("ok" if results else "empty", results,
                    retrieval_mode=mode, scope={"project": project, "platform": "rig"},
                    results_truncated=len(rows) > limit,
                    truncation_reason="result_limit; narrow project/query or increase limit" if len(rows) > limit else None,
                    body_budget=body_budget,
                    body_budget_exhausted=any(item["body_truncated"] for item in results) and remaining == 0,
                    body_fetch_guidance="Use --id and an explicit larger --body-budget if body_truncated is true",
                    semantic_lane="not_requested; use existing MemPalace owner")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path.home() / "foldterm/rig-memory.db")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--query")
    group.add_argument("--id", dest="record_id")
    parser.add_argument("--project")
    parser.add_argument("--session")
    parser.add_argument("--platform")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--body-limit", type=int)
    parser.add_argument("--body-budget", type=int, default=32000)
    args = parser.parse_args()
    output = read_memory(**vars(args))
    print(json.dumps(output, ensure_ascii=False))
    return 0 if output["status"] in {"ok", "empty"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

