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

"""Docket discovery by agency, subject, and status.

Searching one docket at a time assumes you already know which rulemaking you
care about. Often the question is the other way round: *which proposals in my
sector are open right now, and which recently closed ones can be analysed end
to end.*

This runs against the Federal Register API rather than regulations.gov, for two
reasons. It is unmetered — scanning twenty agencies costs no quota — and its
filters are far better: agency, document type, publication window, comment
close date, and full-text term, all composable. The regulations.gov docket IDs
come back inside the FR records, so a hit here hands straight off to the pull.

Each result is classified by what you can actually do with it:

  OPEN        comments still being accepted — you can still file
  CLOSED      comment period over, no final rule yet — the front half only
  ANALYZABLE  final rule published — the full pipeline applies
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import requests

from . import config, discover, store, usage

PROFILE_PATH = config.ROOT / "watchlists.json"

FIELDS = [
    "document_number", "title", "type", "publication_date", "docket_ids",
    "comments_close_on", "agencies", "html_url", "abstract",
]

# A starting set aimed at federal contracting, cyber, and privacy. Agency slugs
# are the Federal Register's own; the Agencies list on the page is fetched live.
STARTER_PROFILES = [
    {
        "name": "Federal cyber & acquisition",
        "agencies": ["defense-department", "general-services-administration",
                     "national-aeronautics-and-space-administration"],
        "terms": "cybersecurity OR CMMC OR \"controlled unclassified information\"",
        "months": 24,
    },
    {
        "name": "Privacy & data protection",
        "agencies": ["federal-trade-commission", "commerce-department"],
        "terms": "privacy OR \"personal information\" OR data broker",
        "months": 24,
    },
    {
        "name": "Critical infrastructure security",
        "agencies": ["homeland-security-department", "energy-department",
                     "transportation-department"],
        "terms": "cybersecurity OR resilience OR critical infrastructure",
        "months": 18,
    },
]


def load() -> list[dict]:
    if PROFILE_PATH.exists():
        try:
            data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    return list(STARTER_PROFILES)


def save(profiles: list[dict]):
    PROFILE_PATH.write_text(json.dumps(profiles, indent=1), encoding="utf-8")


def agencies() -> list[dict]:
    """Live agency list, so slugs are never guessed."""
    try:
        r = requests.get(f"{config.FEDREG_BASE}/agencies", timeout=45)
        usage.record("federalregister", "agencies", r.status_code, r.headers)
        r.raise_for_status()
        out = [
            {"slug": a.get("slug"), "name": a.get("name")}
            for a in r.json()
            if a.get("slug") and a.get("name")
        ]
        return sorted(out, key=lambda a: a["name"])
    except Exception:
        return []


def _fetch(params: dict) -> list[dict]:
    r = requests.get(f"{config.FEDREG_BASE}/documents.json", params=params, timeout=60)
    usage.record("federalregister", "documents/scan", r.status_code, r.headers)
    r.raise_for_status()
    return r.json().get("results", [])


def scan(profile: dict, progress=None) -> dict:
    """Find every rulemaking matching a profile and say what state it's in."""
    say = progress or (lambda m: None)
    months = int(profile.get("months") or 24)
    since = (date.today() - timedelta(days=months * 31)).isoformat()

    base = {
        "per_page": 100,
        "order": "newest",
        "fields[]": FIELDS,
        "conditions[publication_date][gte]": since,
    }
    if profile.get("terms"):
        base["conditions[term]"] = profile["terms"]
    for a in profile.get("agencies") or []:
        base.setdefault("conditions[agencies][]", []).append(a)

    say(f"scanning {len(profile.get('agencies') or []) or 'all'} agencies since {since}")

    proposed = _fetch({**base, "conditions[type][]": "PRORULE"})
    finals = _fetch({**base, "conditions[type][]": "RULE"})
    say(f"{len(proposed)} proposed rules, {len(finals)} final rules")

    # A docket is analysable end to end only if a final rule exists for it.
    finalized: dict[str, dict] = {}
    for f in finals:
        for d in f.get("docket_ids") or []:
            finalized[discover.normalize_id(d) or d] = f

    today = date.today()
    rows = []
    for p in proposed:
        dockets = p.get("docket_ids") or []
        if not dockets:
            continue
        resolved = discover.normalize_id(dockets[0])
        did = resolved or dockets[0]
        close = p.get("comments_close_on")
        days_left = None
        if close:
            try:
                days_left = (datetime.strptime(close, "%Y-%m-%d").date() - today).days
            except ValueError:
                pass
        final = finalized.get(did)
        if final:
            status, note = "analyzable", f"final rule {final['publication_date']}"
        elif days_left is not None and days_left >= 0:
            status = "open"
            note = "closes today" if days_left == 0 else f"{days_left} days to comment"
        else:
            status, note = "closed", "comment period over, no final rule yet"

        rows.append(
            {
                "docket_id": did,
                "title": p.get("title"),
                "agency": (p.get("agencies") or [{}])[0].get("name", ""),
                "published": p.get("publication_date"),
                "comments_close_on": close,
                "days_left": days_left,
                "status": status,
                "note": note,
                "final_document": final["document_number"] if final else None,
                "url": p.get("html_url"),
                "abstract": (p.get("abstract") or "")[:400],
                # Some FR docket_ids are prose ("FAR Case 2017-016, Docket No.
                # 2017-0016, Sequence No. 1") with no derivable ID. Say so
                # rather than offering a button that 400s.
                "id_ok": bool(resolved),
            }
        )

    # Deduplicate on docket, preferring the most actionable state.
    rank = {"open": 0, "analyzable": 1, "closed": 2}
    best: dict[str, dict] = {}
    for r in rows:
        cur = best.get(r["docket_id"])
        if cur is None or rank[r["status"]] < rank[cur["status"]]:
            best[r["docket_id"]] = r
    rows = sorted(
        best.values(),
        key=lambda r: (rank[r["status"]], r["days_left"] if r["days_left"] is not None else 999),
    )

    have = set(
        store.query("SELECT DISTINCT docket_id FROM comments")["docket_id"].tolist()
    )
    for r in rows:
        r["pulled"] = r["docket_id"] in have

    counts = {k: sum(1 for r in rows if r["status"] == k)
              for k in ("open", "analyzable", "closed")}
    out = {"profile": profile.get("name"), "results": rows, "counts": counts,
           "scanned": len(proposed) + len(finals)}
    store.log("watch", f"{profile.get('name')}: {counts}")
    say(f"{counts['open']} open · {counts['analyzable']} analyzable · {counts['closed']} closed")
    return out


def closing_soon(days: int = 30, progress=None) -> list[dict]:
    """Everything government-wide with a comment window closing inside N days."""
    today = date.today()
    rows = _fetch(
        {
            "per_page": 100,
            "order": "newest",
            "fields[]": FIELDS,
            "conditions[type][]": "PRORULE",
            "conditions[comments_close_on][gte]": today.isoformat(),
            "conditions[comments_close_on][lte]": (today + timedelta(days=days)).isoformat(),
        }
    )
    out = []
    for p in rows:
        dockets = p.get("docket_ids") or []
        if not dockets:
            continue
        close = p.get("comments_close_on")
        try:
            left = (datetime.strptime(close, "%Y-%m-%d").date() - today).days
        except (ValueError, TypeError):
            left = None
        out.append(
            {
                "docket_id": discover.normalize_id(dockets[0]) or dockets[0],
                "title": p.get("title"),
                "agency": (p.get("agencies") or [{}])[0].get("name", ""),
                "comments_close_on": close,
                "days_left": left,
                "url": p.get("html_url"),
                "status": "open",
                "note": f"{left} days to comment" if left is not None else "",
                "published": p.get("publication_date"),
            }
        )
    out.sort(key=lambda r: r["days_left"] if r["days_left"] is not None else 999)
    if progress:
        progress(f"{len(out)} comment windows closing within {days} days")
    return out
