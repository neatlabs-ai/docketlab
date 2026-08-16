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

"""Regulations.gov v4 ingest.

Three things the API makes you handle and most scripts get wrong:

1.  Comment *text* is only on the per-item detail endpoint, so a docket of N
    comments costs N+ requests. At 1,000/hr that is the whole budget.
2.  Pagination caps at 20 pages x 250 = 5,000 results per query. Past that you
    must re-anchor on lastModifiedDate and start a fresh page walk.
3.  Quota exhaustion returns 429 mid-run. Everything here checkpoints to DuckDB
    after each comment, so re-running resumes rather than restarting.
"""
from __future__ import annotations

import time
from typing import Callable, Iterator

import requests

from . import config, discover, extract, settings, store, usage

_last_call = [0.0]


def _as_filter_date(iso: str | None) -> str | None:
    """Convert an API-returned timestamp into the format its own filter expects.

    regulations.gov returns lastModifiedDate as ISO-8601 with a Z suffix but
    accepts `filter[lastModifiedDate][ge]` only as 'yyyy-MM-dd HH:mm:ss'.
    Handing the value straight back produces a 400 — which only ever surfaces
    on dockets past the 5,000-result pagination wall, i.e. exactly the large
    ones this cursor exists to handle.
    """
    if not iso:
        return None
    v = str(iso).strip().replace("T", " ").replace("Z", "")
    if "." in v:
        v = v.split(".", 1)[0]
    if "+" in v:
        v = v.split("+", 1)[0]
    return v.strip()[:19] or None


def _throttle():
    delta = time.time() - _last_call[0]
    if delta < config.MIN_INTERVAL:
        time.sleep(config.MIN_INTERVAL - delta)
    _last_call[0] = time.time()


def _get(path: str, params: dict | None = None, tries: int = 4) -> dict:
    params = dict(params or {})
    url = f"{config.REGS_BASE}/{path.lstrip('/')}"
    headers = {"X-Api-Key": settings.get("regs_key") or "DEMO_KEY"}
    for attempt in range(tries):
        _throttle()
        r = requests.get(url, params=params, headers=headers, timeout=45)
        usage.record("regulations.gov", path, r.status_code, r.headers)
        if r.status_code == 429:
            # Quota exhausted. Caller decides whether to wait; we surface it.
            raise QuotaExhausted(r.headers.get("X-RateLimit-Reset", "unknown"))
        if r.status_code == 404:
            raise NotFound(url)
        if r.status_code >= 500 and attempt < tries - 1:
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"exhausted retries for {url}")


class QuotaExhausted(RuntimeError):
    """Hourly API quota is spent. Progress is saved; resume after reset."""


class NotFound(RuntimeError):
    pass


# ── Docket + documents ───────────────────────────────────────────────────────

def fetch_docket(docket_id: str) -> dict:
    payload = _get(f"dockets/{docket_id}")
    store.write_raw("dockets", docket_id, payload)
    a = payload["data"]["attributes"]
    row = {
        "docket_id": docket_id,
        "title": a.get("title"),
        "agency": a.get("agencyId"),
        "docket_type": a.get("docketType"),
        "fetched_at": None,
    }
    store.upsert("dockets", [row])
    store.log("ingest", f"docket {docket_id}: {a.get('title')}")
    return row


def fetch_documents(docket_id: str) -> list[dict]:
    rows, page = [], 1
    while page <= 20:
        payload = _get(
            "documents",
            {
                "filter[docketId]": docket_id,
                "page[size]": 250,
                "page[number]": page,
                "sort": "postedDate",
            },
        )
        data = payload.get("data", [])
        if not data:
            break
        for d in data:
            a = d["attributes"]
            rows.append(
                {
                    "document_id": d["id"],
                    "docket_id": docket_id,
                    "document_type": a.get("documentType"),
                    "title": a.get("title"),
                    "posted_date": a.get("postedDate", "")[:10] or None,
                    "fr_doc_number": a.get("frDocNum"),
                    "comment_count": None,
                }
            )
        if len(data) < 250:
            break
        page += 1
    store.upsert("documents", rows)
    store.log("ingest", f"{len(rows)} documents in {docket_id}")
    return rows


# ── Comment headers (cheap: 250 per request) ─────────────────────────────────

def iter_comment_ids(docket_id: str) -> Iterator[tuple[str, str]]:
    """Yield (comment_id, lastModifiedDate) across the 5,000-result ceiling."""
    cursor = None
    seen: set[str] = set()
    while True:
        page, emitted_this_anchor = 1, 0
        last_seen_mod = cursor
        while page <= 20:
            params = {
                "filter[docketId]": docket_id,
                "page[size]": 250,
                "page[number]": page,
                "sort": "lastModifiedDate",
            }
            if cursor:
                params["filter[lastModifiedDate][ge]"] = _as_filter_date(cursor)
            payload = _get("comments", params)
            data = payload.get("data", [])
            if not data:
                return
            for c in data:
                cid = c["id"]
                mod = c["attributes"].get("lastModifiedDate")
                last_seen_mod = mod or last_seen_mod
                if cid in seen:
                    continue
                seen.add(cid)
                emitted_this_anchor += 1
                yield cid, mod
            if len(data) < 250:
                return
            page += 1
        # Hit the 20-page wall. Re-anchor on the newest lastModifiedDate seen.
        if emitted_this_anchor == 0 or last_seen_mod == cursor:
            return  # no forward progress; stop rather than loop
        cursor = last_seen_mod


# ── Comment details (expensive: 1 request each, plus attachments) ─────────────

def fetch_comment(comment_id: str, docket_id: str, download_attachments=True) -> dict:
    payload = _get(f"comments/{comment_id}", {"include": "attachments"})
    store.write_raw("comments", comment_id, payload)
    a = payload["data"]["attributes"]

    body = (a.get("comment") or "").strip()
    attach_text, n_files = "", 0
    if download_attachments:
        attach_text, n_files = extract.harvest_attachments(comment_id, payload)

    if body and attach_text:
        src = "both"
    elif attach_text:
        src = "attachment"
    elif body:
        src = "inline"
    else:
        src = "empty"

    full = extract.normalize(f"{body}\n\n{attach_text}".strip())
    row = {
        "comment_id": comment_id,
        "docket_id": docket_id,
        "document_id": a.get("commentOnDocumentId"),
        "posted_date": a.get("postedDate"),
        "received_date": a.get("receiveDate"),
        "submitter": " ".join(
            x for x in [a.get("firstName"), a.get("lastName")] if x
        ).strip()
        or None,
        "organization": a.get("organization"),
        "submitter_type": a.get("submitterType"),
        "title": a.get("title"),
        "body": body or None,
        "attach_text": attach_text or None,
        "full_text": full or None,
        "n_attachments": n_files,
        "text_source": src,
        "word_count": len(full.split()) if full else 0,
    }
    store.upsert("comments", [row])
    return row


def pull_docket(docket_id: str, progress: Callable[[str], None] | None = None,
                limit: int | None = None) -> dict:
    """Full resumable pull. Safe to call repeatedly."""
    say = progress or (lambda m: None)
    store.init()
    clean = discover.normalize_id(docket_id)
    if not clean:
        return {"error": f"\u201c{docket_id}\u201d doesn\u2019t contain a docket ID "
                         "(they look like AGENCY-YYYY-NNNN)."}
    if clean != docket_id:
        say(f"using {clean} (from \u201c{docket_id}\u201d)")
    docket_id = clean
    fetch_docket(docket_id)
    docs = fetch_documents(docket_id)
    say(f"{len(docs)} documents")

    have = set(
        store.query(
            "SELECT comment_id FROM comments WHERE docket_id = ?", [docket_id]
        )["comment_id"].tolist()
    )
    say(f"{len(have)} comments already local")

    new = 0
    try:
        for cid, _mod in iter_comment_ids(docket_id):
            if cid in have:
                continue
            fetch_comment(cid, docket_id)
            new += 1
            if new % 25 == 0:
                say(f"pulled {new} new comments")
            if limit and new >= limit:
                break
    except QuotaExhausted as e:
        say(f"quota exhausted (resets {e}); {new} pulled, progress saved - rerun later")

    total = store.scalar(
        "SELECT count(*) FROM comments WHERE docket_id = ?", [docket_id]
    )
    store.log("ingest", f"pull_docket {docket_id}: +{new}, total {total}")
    return {"new": new, "total": total, "documents": len(docs)}
