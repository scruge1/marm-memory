"""Read one explicitly selected native event through the existing capture owner."""
import ast
import hashlib
import json
from pathlib import Path
import re

CAPTURE_SHA = "83396f81160f2253fcc5d98224603915ed3979b8fd85b26b2933d74a5f24e3c5"


def select_event(home, source, native_id, session):
    home, source = Path(home), Path(source)
    root = home / ".local/state/pi-memory-capture"
    try:
        if source.is_symlink() or not source.resolve().is_relative_to((home / ".pi/agent/sessions").resolve()):
            return {"status": "unavailable", "reason": "source_outside_native_capture"}
        manifest = json.loads((root / "sources.json").read_text(encoding="utf-8"))
        stamp = manifest.get(str(source.resolve()))
        before = source.stat()
        if stamp != [before.st_size, before.st_mtime_ns]:
            return {"status": "unavailable", "reason": "capture_source_not_current"}
        if before.st_size > 50 * 1024 * 1024:
            return {"status": "unavailable", "reason": "source_exceeds_native_limit"}
        export = root / "exports" / (hashlib.sha256(str(source.resolve()).encode()).hexdigest()[:16] + "-" + source.stem + ".md")
        if not export.is_file() or export.is_symlink():
            return {"status": "unavailable", "reason": "sanitized_capture_export_missing"}
        selected = None; header = None
        with source.open("rb") as stream:
            ordinal = 0
            while True:
                offset = stream.tell()
                line = stream.readline(1024 * 1024 + 1)
                if not line: break
                ordinal += 1
                if len(line) > 1024 * 1024:
                    return {"status": "unavailable", "reason": "native_record_exceeds_limit"}
                value = json.loads(line)
                if ordinal == 1: header = value
                if value.get("id") == native_id:
                    selected = {"record": value, "ordinal": ordinal, "byte_offset": offset}
                    break
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            return {"status": "unavailable", "reason": "source_changed_during_read"}
        if not header or header.get("type") != "session" or header.get("id") != session:
            return {"status": "unavailable", "reason": "native_session_identity_mismatch"}
        if selected is None:
            return {"status": "unavailable", "reason": "native_event_not_found"}
        selected.update(status="ok", source=str(source.resolve()), session=session,
                        parent_session_id=header.get("parentSession"),
                        sanitized_export_path=str(export), sanitized_export_sha256=hashlib.sha256(export.read_bytes()).hexdigest())
        return selected
    except (OSError, ValueError) as error:
        return {"status": "unavailable", "reason": "capture_source_read_failed", "error_type": type(error).__name__}


def owner_redactor(home):
    source = Path(home) / "foldterm/pi-memory-capture.py"
    content = source.read_bytes()
    if hashlib.sha256(content).hexdigest() != CAPTURE_SHA:
        raise ValueError("capture redactor owner source drift; requalify")
    tree = ast.parse(content.decode("utf-8"))
    definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "redact"]
    if len(definitions) != 1: raise ValueError("capture redactor missing")
    namespace = {"re": re}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(source), "exec"), namespace)
    return namespace["redact"], "pi-capture-redact/" + CAPTURE_SHA
