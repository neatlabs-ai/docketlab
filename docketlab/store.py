# Copyright 2026 Security 360, LLC DBA NEATLABS(TM)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Persistence layer.

Doctrine: the raw API payload is written to disk verbatim and never edited.
Every derived row carries the comment_id it came from, so any number the UI
shows can be walked back to a document on regulations.gov.
"""
from __future__ import annotations

import json
import re
import threading
from contextlib import contextmanager

import duckdb

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS dockets (
    docket_id      VARCHAR PRIMARY KEY,
    title          VARCHAR,
    agency         VARCHAR,
    docket_type    VARCHAR,
    fetched_at     TIMESTAMP
);

CREATE TABLE IF NOT EXISTS documents (
    document_id    VARCHAR PRIMARY KEY,
    docket_id      VARCHAR,
    document_type  VARCHAR,   -- Proposed Rule / Rule / Notice / Supporting
    title          VARCHAR,
    posted_date    DATE,
    fr_doc_number  VARCHAR,
    comment_count  INTEGER
);

CREATE TABLE IF NOT EXISTS comments (
    comment_id     VARCHAR PRIMARY KEY,
    docket_id      VARCHAR,
    document_id    VARCHAR,
    posted_date    TIMESTAMP,
    received_date  TIMESTAMP,
    submitter      VARCHAR,
    organization   VARCHAR,
    submitter_type VARCHAR,
    title          VARCHAR,
    body           VARCHAR,       -- inline comment text
    attach_text    VARCHAR,       -- concatenated extracted attachment text
    full_text      VARCHAR,       -- body + attach_text, normalized
    n_attachments  INTEGER,
    text_source    VARCHAR,       -- inline | attachment | both | empty
    word_count     INTEGER
);

CREATE TABLE IF NOT EXISTS dedup (
    comment_id     VARCHAR PRIMARY KEY,
    exact_hash     VARCHAR,
    campaign_id    VARCHAR,       -- near-duplicate family, NULL if singleton
    is_exemplar    BOOLEAN,
    template_ratio DOUBLE,        -- share of text that is campaign scaffold
    insert_text    VARCHAR        -- the personalized remainder, if any
);

CREATE TABLE IF NOT EXISTS clusters (
    cluster_id     INTEGER,
    comment_id     VARCHAR,
    is_medoid      BOOLEAN
);

CREATE TABLE IF NOT EXISTS analysis (
    comment_id     VARCHAR PRIMARY KEY,
    stance         VARCHAR,        -- support / oppose / mixed / neutral
    argument_types VARCHAR,        -- JSON array
    provisions     VARCHAR,        -- JSON array of cited rule sections
    requested      VARCHAR,        -- JSON array of requested actions
    novel_evidence BOOLEAN,
    evidence_note  VARCHAR,
    significance   INTEGER,        -- 0-100, approximates "requires response"
    summary        VARCHAR,
    model          VARCHAR,
    tokens_in      INTEGER,
    tokens_out     INTEGER
);

CREATE TABLE IF NOT EXISTS responses (
    response_id    VARCHAR PRIMARY KEY,
    document_id    VARCHAR,       -- the final rule
    seq            INTEGER,
    comment_para   VARCHAR,       -- agency's paraphrase of the comment
    response_para  VARCHAR,       -- agency's response
    fr_page        VARCHAR
);

CREATE TABLE IF NOT EXISTS linkage (
    comment_id     VARCHAR,
    response_id    VARCHAR,
    score          DOUBLE,
    method         VARCHAR,       -- embedding | adjudicated
    verdict        VARCHAR,       -- accepted / partial / rejected / unclear
    rationale      VARCHAR
);

CREATE TABLE IF NOT EXISTS textdiff (
    docket_id      VARCHAR,        -- without this a second docket overwrote the first
    section        VARCHAR,
    sort_key       DOUBLE,        -- 170.2 sorts before 170.10, unlike the string
    change_kind    VARCHAR,       -- added / removed / modified / rewritten / unchanged
    similarity     DOUBLE,        -- 1.0 identical, 0.0 nothing in common
    magnitude      DOUBLE,        -- 1 - similarity; how much of the section moved
    words_proposed INTEGER,
    words_final    INTEGER,
    proposed_text  VARCHAR,
    final_text     VARCHAR
);

CREATE TABLE IF NOT EXISTS api_calls (
    ts             TIMESTAMP,
    service        VARCHAR,       -- regulations.gov | federalregister | anthropic
    endpoint       VARCHAR,
    status         INTEGER,
    remaining      INTEGER,       -- as reported by the server, NULL if absent
    limit_total    INTEGER,
    model          VARCHAR,
    tokens_in      INTEGER,
    tokens_out     INTEGER
);

CREATE TABLE IF NOT EXISTS runlog (
    ts             TIMESTAMP,
    stage          VARCHAR,
    detail         VARCHAR
);
"""


class AlreadyRunning(RuntimeError):
    """The data directory is held by another instance."""


_ready = False
_conn = None
_guard = threading.RLock()


@contextmanager
def db():
    """One process-wide connection, guarded.

    Two reasons this is not a connection per call. DuckDB takes a file lock, so
    a UI request reading the ledger while a stage writes to it can collide; a
    single shared connection makes that a same-connection operation instead.
    And ingest calls this once per comment — on a 40,000-comment docket that
    was 40,000 connect/close cycles for no reason.
    """
    global _conn, _ready
    with _guard:
        if _conn is None:
            config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            try:
                _conn = duckdb.connect(str(config.DB_PATH))
            except duckdb.IOException as e:
                if "another process" in str(e).lower() or "lock" in str(e).lower():
                    raise AlreadyRunning(
                        "Another DOCKETLAB instance is already using this data "
                        f"directory:\n    {config.ROOT}\n\n"
                        "DuckDB allows one read-write process at a time. Close the "
                        "other window (check the taskbar for a second console), or "
                        "point this one somewhere else with DL_HOME.\n"
                    ) from e
                raise
        if not _ready:
            _conn.execute(SCHEMA)
            added = migrate(_conn)
            if added:
                print(f"  schema updated: {', '.join(added)}")
            _ready = True
        yield _conn


def _expected_columns() -> dict[str, list[tuple[str, str]]]:
    """Parse SCHEMA into {table: [(column, type), ...]}."""
    out: dict[str, list[tuple[str, str]]] = {}
    for block in re.finditer(
        r"CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\((.*?)\n\);", SCHEMA, re.S
    ):
        table, body = block.group(1), block.group(2)
        cols = []
        for line in body.splitlines():
            line = line.split("--")[0].strip().rstrip(",")
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2 or parts[0].upper() in ("PRIMARY", "FOREIGN", "UNIQUE"):
                continue
            cols.append((parts[0], parts[1]))
        out[table] = cols
    return out


def migrate(con) -> list[str]:
    """Bring an existing database up to the current schema.

    CREATE TABLE IF NOT EXISTS silently does nothing when the table already
    exists, so adding a column to SCHEMA upgrades new installs and breaks every
    existing one. Anything that ships a schema change has to carry the
    migration with it, so this diffs declared columns against actual ones and
    adds what's missing. Widening only — nothing is dropped or retyped, so an
    upgrade can never lose data.
    """
    applied = []
    for table, cols in _expected_columns().items():
        try:
            have = {
                r[0]
                for r in con.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = ?", [table]
                ).fetchall()
            }
        except Exception:
            continue
        if not have:
            continue                       # table doesn't exist; CREATE handles it
        for name, coltype in cols:
            if name not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {coltype}")
                applied.append(f"{table}.{name}")
    return applied


@contextmanager
def reader():
    """A read-only connection that does not take the exclusive lock.

    On Windows the read-write handle blocks even a file copy, so without this
    any inspection of a live instance means shutting the app down. Read-only
    work — the CLI, exports, ad-hoc queries — should come through here.
    """
    global _conn
    with _guard:
        if _conn is not None:      # same process: reuse, no second lock needed
            yield _conn
            return
    if not config.DB_PATH.exists():
        raise FileNotFoundError(f"No database at {config.DB_PATH}")
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    try:
        yield con
    finally:
        con.close()


def read_query(sql: str, params: list | None = None):
    """Query without taking a write lock. Works against a running instance."""
    with reader() as con:
        return con.execute(sql, params or []).fetchdf()


def init():
    with db():
        pass


def close():
    global _conn, _ready
    with _guard:
        if _conn is not None:
            _conn.close()
        _conn, _ready = None, False


def log(stage: str, detail: str):
    with db() as con:
        con.execute(
            "INSERT INTO runlog VALUES (current_timestamp, ?, ?)", [stage, detail]
        )


def write_raw(kind: str, ident: str, payload: dict):
    """Verbatim payload to disk. Content-addressed by kind/id."""
    d = config.RAW / kind
    d.mkdir(parents=True, exist_ok=True)
    safe = ident.replace("/", "_")
    (d / f"{safe}.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")


# Tables that are append-only fact tables rather than keyed entities.
NO_PK = {"clusters", "linkage", "textdiff", "runlog", "api_calls"}


def upsert(table: str, rows: list[dict]):
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in cols)
    collist = ", ".join(cols)
    verb = "INSERT" if table in NO_PK else "INSERT OR REPLACE"
    with db() as con:
        con.executemany(
            f"{verb} INTO {table} ({collist}) VALUES ({placeholders})",
            [[r.get(c) for c in cols] for r in rows],
        )
    return len(rows)


def query(sql: str, params: list | None = None):
    with db() as con:
        return con.execute(sql, params or []).fetchdf()


def scalar(sql: str, params: list | None = None):
    with db() as con:
        row = con.execute(sql, params or []).fetchone()
    return row[0] if row else None
