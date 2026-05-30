from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .classifier import reportable
from .models import ServerRecord, ToolRecord
from .utils import ensure_dir, stable_hash


SCHEMA = """
CREATE TABLE IF NOT EXISTS servers (
  provider TEXT NOT NULL,
  server_id TEXT NOT NULL,
  native_surface TEXT NOT NULL,
  name TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  current_hash TEXT NOT NULL,
  write_confidence TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  PRIMARY KEY (provider, server_id)
);

CREATE TABLE IF NOT EXISTS tools (
  provider TEXT NOT NULL,
  server_id TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  native_surface TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  current_hash TEXT NOT NULL,
  write_confidence TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  PRIMARY KEY (provider, server_id, tool_name)
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_date TEXT NOT NULL,
  event_type TEXT NOT NULL,
  provider TEXT NOT NULL,
  server_id TEXT NOT NULL,
  tool_name TEXT,
  confidence TEXT NOT NULL,
  summary TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  previous_hash TEXT,
  current_hash TEXT,
  UNIQUE (run_date, event_type, provider, server_id, tool_name)
);
"""


def connect(path: Path) -> sqlite3.Connection:
    ensure_dir(path.parent)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _fetch_one(conn: sqlite3.Connection, table: str, where: Tuple[Any, ...]) -> Optional[sqlite3.Row]:
    if table == "servers":
        return conn.execute("SELECT * FROM servers WHERE provider=? AND server_id=?", where).fetchone()
    return conn.execute("SELECT * FROM tools WHERE provider=? AND server_id=? AND tool_name=?", where).fetchone()


def _insert_event(
    conn: sqlite3.Connection,
    run_date: str,
    event_type: str,
    provider: str,
    server_id: str,
    tool_name: Optional[str],
    confidence: str,
    summary: str,
    evidence: List[Dict[str, Any]],
    previous_hash: Optional[str],
    current_hash: str,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO events
        (run_date, event_type, provider, server_id, tool_name, confidence, summary, evidence_json, previous_hash, current_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (run_date, event_type, provider, server_id, tool_name, confidence, summary, json.dumps(evidence, sort_keys=True), previous_hash, current_hash),
    )


def seeded_providers(conn: sqlite3.Connection, run_date: str) -> set:
    """Providers that already have at least one server row from a prior run
    date. A provider NOT in this set is appearing for the first time and its
    new-write events should be suppressed (silent baseline)."""
    rows = conn.execute(
        "SELECT DISTINCT provider FROM servers WHERE first_seen < ?", (run_date,)
    ).fetchall()
    return {row["provider"] for row in rows}


def upsert_server(conn: sqlite3.Connection, run_date: str, server: ServerRecord, provider_seeded: bool = True) -> None:
    raw = server.to_dict(include_tools=False)
    current_hash = stable_hash(raw)
    previous = _fetch_one(conn, "servers", (server.provider, server.server_id))
    if previous is None:
        if reportable(server.write_confidence) and provider_seeded:
            _insert_event(
                conn,
                run_date,
                "new_write_server",
                server.provider,
                server.server_id,
                None,
                server.write_confidence,
                f"New write-capable {server.provider} {server.native_surface}: {server.name}",
                server.evidence,
                None,
                current_hash,
            )
        first_seen = run_date
    else:
        first_seen = previous["first_seen"]
        if not reportable(previous["write_confidence"]) and reportable(server.write_confidence):
            _insert_event(
                conn,
                run_date,
                "write_status_changed",
                server.provider,
                server.server_id,
                None,
                server.write_confidence,
                f"{server.provider} {server.native_surface} became write-capable: {server.name}",
                server.evidence,
                previous["current_hash"],
                current_hash,
            )

    conn.execute(
        """
        INSERT INTO servers
        (provider, server_id, native_surface, name, first_seen, last_seen, current_hash, write_confidence, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, server_id) DO UPDATE SET
          native_surface=excluded.native_surface,
          name=excluded.name,
          last_seen=excluded.last_seen,
          current_hash=excluded.current_hash,
          write_confidence=excluded.write_confidence,
          raw_json=excluded.raw_json
        """,
        (
            server.provider,
            server.server_id,
            server.native_surface,
            server.name,
            first_seen,
            run_date,
            current_hash,
            server.write_confidence,
            json.dumps(raw, sort_keys=True),
        ),
    )


def upsert_tool(conn: sqlite3.Connection, run_date: str, tool: ToolRecord) -> None:
    raw = tool.to_dict()
    current_hash = stable_hash(raw)
    previous = _fetch_one(conn, "tools", (tool.provider, tool.server_id, tool.name))
    if previous is None:
        if reportable(tool.write_confidence):
            _insert_event(
                conn,
                run_date,
                "new_write_tool",
                tool.provider,
                tool.server_id,
                tool.name,
                tool.write_confidence,
                f"New write-capable tool: {tool.provider}/{tool.server_id}/{tool.name}",
                tool.evidence,
                None,
                current_hash,
            )
        first_seen = run_date
    else:
        first_seen = previous["first_seen"]
        if not reportable(previous["write_confidence"]) and reportable(tool.write_confidence):
            _insert_event(
                conn,
                run_date,
                "write_status_changed",
                tool.provider,
                tool.server_id,
                tool.name,
                tool.write_confidence,
                f"Tool became write-capable: {tool.provider}/{tool.server_id}/{tool.name}",
                tool.evidence,
                previous["current_hash"],
                current_hash,
            )
        elif previous["current_hash"] != current_hash and reportable(tool.write_confidence):
            _insert_event(
                conn,
                run_date,
                "tool_schema_changed",
                tool.provider,
                tool.server_id,
                tool.name,
                tool.write_confidence,
                f"Write-capable tool changed: {tool.provider}/{tool.server_id}/{tool.name}",
                tool.evidence,
                previous["current_hash"],
                current_hash,
            )

    conn.execute(
        """
        INSERT INTO tools
        (provider, server_id, tool_name, native_surface, first_seen, last_seen, current_hash, write_confidence, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, server_id, tool_name) DO UPDATE SET
          native_surface=excluded.native_surface,
          last_seen=excluded.last_seen,
          current_hash=excluded.current_hash,
          write_confidence=excluded.write_confidence,
          raw_json=excluded.raw_json
        """,
        (
            tool.provider,
            tool.server_id,
            tool.name,
            tool.native_surface,
            first_seen,
            run_date,
            current_hash,
            tool.write_confidence,
            json.dumps(raw, sort_keys=True),
        ),
    )


def events_for_date(conn: sqlite3.Connection, run_date: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM events WHERE run_date=? ORDER BY id ASC",
        (run_date,),
    ).fetchall()
    events = []
    for row in rows:
        item = dict(row)
        item["evidence"] = json.loads(item.pop("evidence_json") or "[]")
        events.append(item)
    return events


def all_current(conn: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
    rows = conn.execute(f"SELECT raw_json FROM {table} ORDER BY provider, server_id").fetchall()
    return [json.loads(row["raw_json"]) for row in rows]

