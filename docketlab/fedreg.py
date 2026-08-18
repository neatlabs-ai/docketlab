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
from xml.etree import ElementTree as ET

import requests

from . import config, extract, store, usage

# Actions that are not the operative document, however they are typed. A
# correction, an interim final rule and a technical amendment all carry
# type "Rule"; a comment-period extension and a supplemental notice both carry
# type "Proposed Rule". Selecting on type alone picked a 78-page correction over
# a 408-page final rule.
_NOT_OPERATIVE = re.compile(
    r"\b(correction|corrections|correcting amendment|technical amendment"
    r"|withdrawal|withdraw|extension of (the )?comment period|reopening"
    r"|notice of (public )?(meeting|hearing)|delay of effective date"
    r"|stay of effective date|partial stay)\b", re.I
)
_INTERIM = re.compile(r"\binterim (final )?rule\b", re.I)
_SUPPLEMENTAL = re.compile(r"\bsupplement(al|ary)?\b", re.I)

# A comment/response pair longer than this is a failed match, not a long pair.
# Whatever is stored must be whole: truncating a side produces a fragment that
# reads as evidence.
MAX_SIDE = 20000

PAGE_MARK = re.compile(r"\[\[Page (\d+)\]\]")

# Ordered by specificity. Each yields (comment_text, response_text) pairs.
CONVENTIONS = [
    (
        "numbered",
        re.compile(
            r"^[ \t]*Comment\s*(\d+)\s*[:.]\s*(?P<c>.+?)\s*"
            r"^[ \t]*Response\s*\1?\s*[:.]\s*(?P<r>.+?)"
            r"(?=^[ \t]*Comment\s*\d+\s*[:.]|\Z)",
            re.S | re.I | re.M,
        ),
    ),
    (
        "plain",
        # The label is anchored to the start of a line and requires a colon.
        # Accepting a full stop meant any sentence ending "...we received
        # comments." opened a pair, and because finditer resumes at the end of
        # each match one spurious start shifted every following boundary. On SSA
        # 2026-13420 the first match began 5,628 characters before the
        # document's first real label and only 26 of 71 pairs survived, 17 of
        # them beginning inside a Response.
        re.compile(
            r"^[ \t]*Comments?\s*:\s*(?P<c>.+?)\s*^[ \t]*Response\s*:\s*(?P<r>.+?)"
            r"(?=^[ \t]*Comments?\s*:|\Z)",
            re.S | re.I | re.M,
        ),
    ),
    (
        "one-comment-many-responses",
        re.compile(
            r"^[ \t]*Comment\b\s*[-—]\s*(?P<c>.+?)\s*"
            r"^[ \t]*Response\b\s*[-—]\s*(?P<r>.+?)"
            r"(?=^[ \t]*Comment\b\s*[-—]|\Z)",
            re.S | re.I | re.M,
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
                "effective_on", "html_url", "action", "full_text_xml_url",
            ],
        },
    )
    store.write_raw("fedreg", docket_id, payload)
    return payload.get("results", [])


def _pages(d: dict) -> int:
    try:
        return max(int(d.get("end_page") or 0) - int(d.get("start_page") or 0) + 1, 0)
    except (TypeError, ValueError):
        return 0


def _pick(docs: list[dict], want: str) -> tuple[dict | None, list[str]]:
    """Choose the operative NPRM or final rule, and say why.

    Preference order: the action text has to look like the real thing, and among
    candidates that qualify the longest document wins - a preamble that
    adjudicates hundreds of comments is not 78 pages. Supplemental proposals
    supersede the original, so the latest qualifying proposal is taken.
    """
    typed = [d for d in docs if d.get("type") == want]
    if not typed:
        return None, ["no document of that type"]

    notes: list[str] = []
    eligible = []
    for d in typed:
        action = d.get("action") or ""
        if _NOT_OPERATIVE.search(action):
            notes.append(f"skipped {d['document_number']} ({action.strip()[:48]})")
            continue
        eligible.append(d)

    if not eligible:
        # Every candidate looks ancillary. Fall back rather than return nothing,
        # but say so - an interim final rule may be all there is.
        eligible = typed
        notes.append("no non-ancillary candidate; using the longest available")

    if want == "Rule":
        # Prefer a plain final rule over an interim one, then the longest.
        plain = [d for d in eligible if not _INTERIM.search(d.get("action") or "")]
        pool = plain or eligible
        chosen = max(pool, key=lambda d: (_pages(d), d.get("publication_date") or ""))
    else:
        # A supplemental proposal supersedes the original it amends. Absent one,
        # length decides: a docket carries ancillary documents typed "Proposed
        # Rule" that no action keyword predicts - a notice of posting an
        # informational video, of data availability, of a public hearing. Ranking
        # by date first handed the NPRM slot to whichever of those came last.
        supp = [d for d in eligible if _SUPPLEMENTAL.search(d.get("action") or "")]
        pool = supp or eligible
        chosen = max(pool, key=lambda d: (_pages(d), d.get("publication_date") or ""))

    notes.append(
        f"chose {chosen['document_number']} ({_pages(chosen)}pp, "
        f"{(chosen.get('action') or 'no action text').strip()[:56]})"
    )
    return chosen, notes


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


# ── Structural parsing, preferred over the regex conventions ─────────────────
#
# The Federal Register publishes full text as XML in which each paragraph is its
# own element, and a Comment or Response label opens a paragraph. Matching on
# element boundaries removes the whole class of problem that regex over
# flattened text creates: a sentence ending "...we received comments." cannot
# open a pair, because it is not the start of a paragraph, and a match cannot
# run past its paragraph into codified rule text.
#
# Credit for the approach to Abigail Haddad, who reported the failures it fixes.

_LABEL = re.compile(r"^\s*(Comments?|Response)\s*(\d+)?\s*[:.\u2014-]\s*(.*)$",
                    re.I | re.S)


def _paragraphs(xml_text: str) -> list[str]:
    """Every paragraph in document order, as text."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out: list[str] = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1].upper() != "P":
            continue
        txt = " ".join(t.strip() for t in el.itertext() if t and t.strip())
        txt = re.sub(r"\s+", " ", txt).strip()
        if txt:
            out.append(txt)
    return out


def parse_structural(document_id: str, xml_text: str) -> tuple[list[tuple], dict]:
    """Pair Comment and Response paragraphs on element boundaries."""
    paras = _paragraphs(xml_text)
    if not paras:
        return [], {"paragraphs": 0, "usable": False}

    pairs: list[tuple] = []
    i = 0
    labelled = 0
    while i < len(paras):
        m = _LABEL.match(paras[i])
        if not m or m.group(1).lower().startswith("response"):
            i += 1
            continue
        labelled += 1
        # Accumulate the comment side until a Response label opens a paragraph.
        comment = [m.group(3).strip()]
        j = i + 1
        while j < len(paras):
            mj = _LABEL.match(paras[j])
            if mj and mj.group(1).lower().startswith("response"):
                break
            if mj:            # another Comment label: this one had no response
                break
            comment.append(paras[j])
            j += 1
        if j >= len(paras) or not _LABEL.match(paras[j] or ""):
            i = j
            continue
        mr = _LABEL.match(paras[j])
        if not mr.group(1).lower().startswith("response"):
            i = j
            continue
        response = [mr.group(3).strip()]
        k = j + 1
        while k < len(paras):
            if _LABEL.match(paras[k]):
                break
            response.append(paras[k])
            k += 1
        c = " ".join(x for x in comment if x).strip()
        r = " ".join(x for x in response if x).strip()
        if len(c) >= 40 and len(r) >= 40 and len(c) <= MAX_SIDE and len(r) <= MAX_SIDE:
            pairs.append((i, c, r))
        i = k

    return pairs, {
        "paragraphs": len(paras),
        "comment_labels": labelled,
        "usable": len(pairs) >= 3,
    }


def parse_responses(document_id: str, text: str, xml_text: str | None = None) -> dict:
    """Extract (comment, response) pairs. Returns pairs plus parse diagnostics."""
    text = extract.normalize(text)
    pages = _page_index(text)

    best_name, best_pairs, best_cov = None, [], 0.0

    # Structure first. Regex over flattened text is the fallback, not the plan.
    struct_diag = {}
    if xml_text:
        spairs, struct_diag = parse_structural(document_id, xml_text)
        if struct_diag.get("usable"):
            best_name, best_pairs = "structural", spairs
            best_cov = min(
                sum(len(c) + len(r) for _, c, r in spairs) / max(len(text), 1), 1.0)
    for name, pattern in CONVENTIONS:
        if best_name == "structural":
            break
        pairs, covered = [], 0
        for m in pattern.finditer(text):
            c = m.group("c").strip()
            r = m.group("r").strip()
            if len(c) < 40 or len(r) < 40:
                continue
            # Both sides are bounded. Only the response side was checked, and
            # the comment side was then truncated to 12,000 characters on the
            # way into the store - so an overlong match was kept rather than
            # rejected, and what got stored was a fragment that ran from
            # preamble prose into codified rule text. That fragment is what the
            # linkage embeds and what the adjudicator is shown as "the agency's
            # paraphrase of the comment it is answering".
            if len(c) > MAX_SIDE or len(r) > MAX_SIDE:
                continue
            pairs.append((m.start(), c, r))
            covered += m.end() - m.start()
        cov = covered / max(len(text), 1)
        if len(pairs) > len(best_pairs):
            best_name, best_pairs, best_cov = name, pairs, cov

    rows = []
    for i, (pos, c, r) in enumerate(best_pairs, start=1):
        page = _page_at(pages, pos) if best_name != "structural" else None
        rows.append(
            {
                "response_id": f"{document_id}-R{i:04d}",
                "document_id": document_id,
                "seq": i,
                "comment_para": c,
                "response_para": r,
                "fr_page": page,
            }
        )
    with store.db() as con:
        con.execute("DELETE FROM responses WHERE document_id = ?", [document_id])
    store.upsert("responses", rows)

    diag = {
        "convention": best_name,
        "structural": struct_diag or None,
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

    nprm, nprm_why = _pick(docs, "Proposed Rule")
    final, final_why = _pick(docs, "Rule")
    say(f"{len(docs)} FR documents; NPRM={bool(nprm)} final={bool(final)}")
    for line in nprm_why:
        say(f"  proposal: {line}")
    for line in final_why:
        say(f"  final:    {line}")

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
    xml_text = None
    if final.get("full_text_xml_url"):
        try:
            rx = requests.get(final["full_text_xml_url"], timeout=90)
            rx.raise_for_status()
            xml_text = rx.text
        except Exception as e:
            say(f"  structural XML unavailable ({type(e).__name__}); using flat text")
    (config.RAW / f"finalrule_{final['document_number']}.txt").write_text(
        text, encoding="utf-8"
    )
    diag = parse_responses(final["document_number"], text, xml_text)
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
