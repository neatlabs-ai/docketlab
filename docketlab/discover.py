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

"""Docket discovery and preflight.

Two ways in. A short curated list of dockets I can vouch for, and a live search
against the API so you aren't limited to whatever someone hardcoded.

Preflight matters more than either. Comment *text* costs one request per
comment against a 1,000/hour quota, so the difference between a docket you can
pull over coffee and one that ties up your key for two days is a number you
want *before* you press the button, not after.
"""
from __future__ import annotations

import json
import re

import requests

from . import config, settings, usage

STARTER_PATH = config.ROOT / "starters.json"


def starters() -> list[dict]:
    """Shipped examples, overridable. A user in healthcare has no use for CMMC."""
    if STARTER_PATH.exists():
        try:
            data = json.loads(STARTER_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return list(DEFAULT_STARTERS)


def save_starters(rows: list[dict]):
    STARTER_PATH.write_text(json.dumps(rows, indent=1), encoding="utf-8")


# Verified against the Federal Register and the published record. Comment
# counts are approximate — preflight gets the live number.
DEFAULT_STARTERS = [
    {
        "docket_id": "DOD-2023-OS-0063",
        "label": "CMMC Program (32 CFR 170)",
        "agency": "DoD",
        "approx_comments": 361,
        "closed": True,
        "why": "The reference case, and the docket every claim in this project's "
               "README was measured against. Closed, with a 140-page final rule at "
               "89 FR 83092 whose preamble uses the plain Comment/Response "
               "convention. Small enough to pull inside one hourly quota, and heavy "
               "on PDF attachments from trade associations and universities.",
        "tests": "outcome linkage, attachment extraction, argument typing",
    },
    {
        "docket_id": "DEA-2024-0059",
        "label": "Marijuana rescheduling (Schedule I → III)",
        "agency": "DEA",
        "approx_comments": 42913,
        "closed": True,
        "why": "The campaign-heavy counterpart. The most comments any DEA proposal "
               "has drawn, with a final rule published in April 2026, so the full "
               "stack applies. 42,913 comments is roughly 43 hours of API quota — "
               "a capped sample shows the pipeline working; the Mirrulations S3 "
               "mirror is the route to the whole corpus.",
        "tests": "campaign dedup at scale, paraphrase families, template splits",
    },
    {
        "docket_id": "EPA-HQ-OW-2023-0469",
        "label": "Unregulated Contaminant Monitoring Rule (UCMR 6)",
        "agency": "EPA",
        "approx_comments": 60,
        "closed": False,
        "why": "A non-DoD docket, and an example of the third state: the comment "
               "period closed in April 2024 but no final rule has been published, "
               "so the agency has not yet adjudicated anything. Ingest, campaign "
               "detection and clustering all run; outcome linkage and text diff "
               "correctly refuse. Useful for seeing what the tool does when the "
               "answer does not exist yet.",
        "tests": "ingest and clustering on a second agency; the no-final-rule guard",
    },
]


# The Federal Register's own `docket_ids` field returns values like
# "Docket DARS-2020-0034" and "FAR Case 2017-016, Docket No. 2017-0016,
# Sequence No. 1" — labels and all. So this is not defensive tidying for sloppy
# paste; without it, every hand-off from the Watch tab to a pull is a 400.
_LABELS = re.compile(
    r"^\s*(?:docket\s*(?:id|no\.?|number)?\s*[:\-]?\s*|"
    r"regulations\.gov\s*[:\-]?\s*|rin\s*[:\-]?\s*)+", re.I
)
_SHAPE = re.compile(r"[A-Z][A-Z0-9]{1,9}(?:-[A-Z0-9]{1,6}){1,4}")


def normalize_id(raw: str) -> str | None:
    """Pull a usable docket ID out of whatever the user or an API handed us.

    Returns None when nothing docket-shaped is present, so the caller can say
    what's wrong instead of spending a request to be told 400 by the server.
    """
    if not raw:
        return None
    v = str(raw).strip().strip('"\'')
    v = v.split(",")[0]                       # "…, Sequence No. 1"
    v = _LABELS.sub("", v).strip()
    v = v.replace("\u2013", "-").replace("\u2014", "-")
    m = _SHAPE.search(v.upper())
    return m.group(0) if m else None


def _headers():
    return {"X-Api-Key": settings.get("regs_key") or "DEMO_KEY"}


def search(term: str, limit: int = 10) -> list[dict]:
    """Live docket search. One request."""
    if not term.strip():
        return []
    r = requests.get(
        f"{config.REGS_BASE}/dockets",
        params={
            "filter[searchTerm]": term.strip(),
            "page[size]": min(limit, 25),
            "sort": "-lastModifiedDate",
        },
        headers=_headers(),
        timeout=40,
    )
    usage.record("regulations.gov", "dockets/search", r.status_code, r.headers)
    r.raise_for_status()
    out = []
    for d in r.json().get("data", []):
        a = d.get("attributes", {})
        out.append(
            {
                "docket_id": d["id"],
                "title": a.get("title"),
                "agency": a.get("agencyId"),
                "type": a.get("docketType"),
                "modified": (a.get("lastModifiedDate") or "")[:10],
            }
        )
    return out


def preflight(raw_id: str) -> dict:
    """How big is this and what will pulling it cost? Two requests."""
    docket_id = normalize_id(raw_id)
    if not docket_id:
        return {"error": f"\u201c{raw_id}\u201d doesn\u2019t contain a docket ID. "
                         "They look like AGENCY-YYYY-NNNN, e.g. DOD-2023-OS-0063."}
    info = {"docket_id": docket_id, "raw": raw_id if raw_id != docket_id else None}
    try:
        r = requests.get(
            f"{config.REGS_BASE}/dockets/{docket_id}", headers=_headers(), timeout=40
        )
        usage.record("regulations.gov", "dockets/get", r.status_code, r.headers)
        if r.status_code == 404:
            return {"error": f"No docket {docket_id}. Check the ID — they look like AGENCY-YYYY-NNNN."}
        r.raise_for_status()
        a = r.json()["data"]["attributes"]
        info["title"] = a.get("title")
        info["agency"] = a.get("agencyId")
    except requests.HTTPError as e:
        return {"error": f"lookup failed: {e}"}
    except Exception as e:
        return {"error": f"could not reach regulations.gov: {type(e).__name__}"}

    try:
        r = requests.get(
            f"{config.REGS_BASE}/comments",
            params={"filter[docketId]": docket_id, "page[size]": 5},
            headers=_headers(),
            timeout=40,
        )
        usage.record("regulations.gov", "comments/count", r.status_code, r.headers)
        r.raise_for_status()
        payload = r.json()
        total = payload.get("meta", {}).get("totalElements")
        info["comments"] = total
        info["remaining_quota"] = r.headers.get("X-RateLimit-Remaining")
    except Exception:
        info["comments"] = None

    n = info.get("comments") or 0
    # 1 detail request per comment, plus ~1 header request per 250, plus the
    # docket and document lookups. Attachments are separate HTTP fetches but
    # they don't come off the api.data.gov quota.
    requests_needed = n + max(1, n // 250) + 3
    info["requests"] = requests_needed
    info["hours"] = round(requests_needed / 950, 2)
    if requests_needed <= 950:
        info["verdict"] = "fits in one hourly quota — pull the whole thing"
    elif requests_needed <= 5000:
        info["verdict"] = (
            f"about {info['hours']:.1f} hours of quota; resumable, or cap the sample"
        )
    else:
        info["verdict"] = (
            f"~{info['hours']:.0f} hours via the API. Cap the sample to see it work, "
            "then use the Mirrulations S3 mirror for the full corpus."
        )
    return info
