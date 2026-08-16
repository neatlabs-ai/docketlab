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

"""Federal Register ingest and preamble parsing.

The outcome-linkage layer lives or dies here. A final rule's preamble contains
the agency's adjudication of the comments — that text is the only public record
of which arguments landed. It is unstructured prose, but agencies are creatures
of habit and the conventions are recognizable.

We try several known conventions, report which one matched and what fraction of
the preamble it covered, and refuse to guess when coverage is poor. A linkage
built on a bad parse is worse than no linkage, because it looks authoritative.
"""
from __future__ import annotations

import re

import requests

from . import config, extract, store, usage

PAGE_MARK = re.compile(r"\[\[Page (\d+)\]\]")

# Ordered by specificity. Each yields (comment_text, response_text) pairs.
CONVENTIONS = [
    (
        "numbered",
        re.compile(
            r"Comment\s*(\d+)\s*[:.]\s*(?P<c>.+?)\s*Response\s*\1?\s*[:.]\s*(?P<r>.+?)"
            r"(?=Comment\s*\d+\s*[:.]|\Z)",
            re.S | re.I,
        ),
    ),
    (
        "plain",
        re.compile(
            r"\bComments?\s*[:.]\s*(?P<c>.+?)\s*\bResponse\s*[:.]\s*(?P<r>.+?)"
            r"(?=[\s.;)]Comments?\s*[:.]|^Comments?\s*[:.]|\Z)",
            re.S | re.I,
        ),
    ),
    (
        "one-comment-many-responses",
        re.compile(
            r"\bComment\b\s*[-—]\s*(?P<c>.+?)\s*\bResponse\b\s*[-—]\s*(?P<r>.+?)"
            r"(?=\bComment\b\s*[-—]|\Z)",
            re.S | re.I,
        ),
    ),
]


def _get(path: str, params: dict | None = None) -> dict:
    r = requests.get(f"{config.FEDREG_BASE}/{path}", params=params or {}, timeout=45)
    usage.record("federalregister", path, r.status_code, r.headers)
    r.raise_for_status()
    return r.json()


def find_documents(docket_id: str) -> list[dict]:
    """Locate the NPRM and final rule for a docket. No API key required."""
    payload = _get(
        "documents.json",
        {
            "conditions[docket_id]": docket_id,
            "per_page": 50,
            "order": "oldest",
            "fields[]": [
                "document_number", "title", "type", "publication_date",
                "start_page", "end_page", "raw_text_url", "comments_close_on",
                "effective_on", "html_url",
            ],
        },
    )
    store.write_raw("fedreg", docket_id, payload)
    return payload.get("results", [])


def raw_text(doc: dict) -> str:
    url = doc.get("raw_text_url")
    if not url:
        return ""
    r = requests.get(url, timeout=90)
    r.raise_for_status()
    return r.text


def _page_index(text: str) -> list[tuple[int, str]]:
    return [(m.start(), m.group(1)) for m in PAGE_MARK.finditer(text)]


def _page_at(index: list[tuple[int, str]], pos: int) -> str | None:
    page = None
    for start, p in index:
        if start <= pos:
            page = p
        else:
            break
    return page


def parse_responses(document_id: str, text: str) -> dict:
    """Extract (comment, response) pairs. Returns pairs plus parse diagnostics."""
    text = extract.normalize(text)
    pages = _page_index(text)

    best_name, best_pairs, best_cov = None, [], 0.0
    for name, pattern in CONVENTIONS:
        pairs, covered = [], 0
        for m in pattern.finditer(text):
            c = m.group("c").strip()
            r = m.group("r").strip()
            if len(c) < 40 or len(r) < 40:
                continue
            if len(r) > 20000:      # runaway match: convention doesn't fit
                continue
            pairs.append((m.start(), c, r))
            covered += m.end() - m.start()
        cov = covered / max(len(text), 1)
        if len(pairs) > len(best_pairs):
            best_name, best_pairs, best_cov = name, pairs, cov

    rows = []
    for i, (pos, c, r) in enumerate(best_pairs, start=1):
        rows.append(
            {
                "response_id": f"{document_id}-R{i:04d}",
                "document_id": document_id,
                "seq": i,
                "comment_para": c[:12000],
                "response_para": r[:12000],
                "fr_page": _page_at(pages, pos),
            }
        )
    with store.db() as con:
        con.execute("DELETE FROM responses WHERE document_id = ?", [document_id])
    store.upsert("responses", rows)

    diag = {
        "convention": best_name,
        "pairs": len(rows),
        "preamble_coverage": round(best_cov, 3),
        "confident": len(rows) >= 5 and best_cov >= 0.05,
    }
    store.log("fedreg", f"{document_id}: {diag}")
    return diag


def load(docket_id: str, progress=None) -> dict:
    say = progress or (lambda m: None)
    docs = find_documents(docket_id)
    if not docs:
        return {"error": f"no Federal Register documents found for {docket_id}"}

    nprm = next((d for d in docs if d["type"] == "Proposed Rule"), None)
    final = next((d for d in reversed(docs) if d["type"] == "Rule"), None)
    say(f"{len(docs)} FR documents; NPRM={bool(nprm)} final={bool(final)}")

    out = {"documents": len(docs), "nprm": None, "final": None}
    if nprm:
        out["nprm"] = {
            "document_number": nprm["document_number"],
            "published": nprm["publication_date"],
            "pages": f"{nprm.get('start_page')}-{nprm.get('end_page')}",
            "comments_close_on": nprm.get("comments_close_on"),
        }
    if not final:
        out["warning"] = (
            "No final rule published yet. Outcome linkage cannot run — the "
            "docket is still open or stalled at OIRA."
        )
        return out

    say(f"fetching final rule {final['document_number']}")
    text = raw_text(final)
    (config.RAW / f"finalrule_{final['document_number']}.txt").write_text(
        text, encoding="utf-8"
    )
    diag = parse_responses(final["document_number"], text)
    out["final"] = {
        "document_number": final["document_number"],
        "published": final["publication_date"],
        "pages": f"{final.get('start_page')}-{final.get('end_page')}",
        "chars": len(text),
        **diag,
    }
    say(
        f"parsed {diag['pairs']} comment/response pairs "
        f"({diag['convention']}, coverage {diag['preamble_coverage']:.0%})"
    )
    return out
