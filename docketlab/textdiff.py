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

"""Regulatory text diff — the second channel through which a comment succeeds.

The CMMC ledger exposed the gap. Nine high-significance comments came back
marked "no response," and nearly all of them were editorial defect reports:
§170.17(a)(1) cites Level 3 where it means Level 2; the rule contradicts itself
on whether Level 1 requires scoring; a stray L3 reference sits inside an L2
standard.

Agencies do not write a Comment/Response pair for those. They just fix the
text. So a preamble-only view scores a commenter who got exactly what they
asked for identically to one the agency ignored — opposite outcomes rendered as
the same red stamp.

This module reads the codified rule text out of both the proposed and final
Federal Register documents, diffs it section by section, and gives the ledger a
second way to say a comment landed: *the provision you cited changed.*
"""
from __future__ import annotations

import difflib
import re

from . import extract, fedreg, store

# Section headings in Federal Register full text are not one shape. Observed:
#
#     § 170.4  Acronyms and definitions.        heading and title on one line
#     § 170.4                                   title on the *next* line
#     Acronyms and definitions.
#     Sec. 170.4  Acronyms and definitions.     older / some agencies
#
# The original pattern required the title on the same line as the number, which
# silently matched nothing on a real DoD rule and reported zero sections without
# saying why. Detection is now two-stage — find every candidate, then decide
# which are headings and which are cross-references — and it reports its own
# diagnostics so a miss can be debugged instead of guessed at.
HEADING = re.compile(r"(?m)^[ \t]*(?:§+|Sec\.)[ \t]*(\d{1,3}\.\d{1,3}[a-z]?)[ \t]*(.*)$")

# A cross-reference, not a heading: "§§ 170.4 and 170.5", "see § 170.4(c)(1)".
CROSSREF = re.compile(r"^\s*(?:and|through|to|or)\b|^\s*\(")

# Everything before this in a final rule is preamble, not regulatory text.
TEXT_MARKERS = [
    r"List of Subjects in \d+ CFR",
    r"^\s*PART \d+[—\-–]",
    r"For the reasons (set forth|stated|discussed)",
    r"is amended as follows",
    r"^\s*Authority:",
]


def _codified_region(text: str) -> tuple[str, int]:
    """Return the tail holding actual rule text, plus where it started."""
    best = 0
    for pat in TEXT_MARKERS:
        for m in re.finditer(pat, text, re.M | re.I):
            best = max(best, m.start())
    return (text[best:] if best else text), best


def diagnose(text: str) -> dict:
    """What does this document actually look like? Surfaced when detection fails.

    A parser that reports zero and stops is a parser you cannot fix. This says
    how many section-like tokens exist, how many sit at the start of a line, and
    shows a few verbatim so the real convention is visible.
    """
    norm = extract.normalize(text)
    region, offset = _codified_region(norm)
    samples = []
    for m in list(re.finditer(r"(?:§+|Sec\.)[ \t]*\d{1,3}\.\d{1,3}", norm))[:6]:
        line_start = norm.rfind("\n", 0, m.start()) + 1
        line_end = norm.find("\n", m.end())
        samples.append(norm[line_start:line_end if line_end > 0 else m.end() + 60][:110])
    return {
        "chars": len(norm),
        "section_tokens": len(re.findall(r"(?:§+|Sec\.)[ \t]*\d{1,3}\.\d{1,3}", norm)),
        "line_start_tokens": len(HEADING.findall(norm)),
        "codified_region_found": offset > 0,
        "codified_region_chars": len(region),
        "samples": samples,
    }


def sections(text: str) -> dict[str, dict]:
    """Split codified text into {section: {title, body}}."""
    norm = extract.normalize(text)
    region, _ = _codified_region(norm)
    lines = region.split("\n")

    hits: list[tuple[int, str, str, int]] = []  # (line, section, title, body start)
    for i, line in enumerate(lines):
        m = HEADING.match(line)
        if not m:
            continue
        num, rest = m.group(1), (m.group(2) or "").strip()
        if CROSSREF.match(rest):
            continue                       # "§§ 170.4 and 170.5"
        title = rest
        body_from = i + 1
        if not title:                      # title lives on the following line
            for j in range(i + 1, min(i + 3, len(lines))):
                nxt = lines[j].strip()
                if nxt:
                    title, body_from = nxt, j + 1
                    break
        # A heading's title reads like a title: it does not run on as prose.
        if len(title) > 140:
            title = title[:140]
        hits.append((i, num, title.rstrip("."), body_from))

    out: dict[str, dict] = {}
    for k, (idx, num, title, body_from) in enumerate(hits):
        end = hits[k + 1][0] if k + 1 < len(hits) else len(lines)
        # body_from skips a title that sat on its own line — counting it as body
        # makes an otherwise identical section read as "modified".
        body = "\n".join(lines[body_from:end]).strip()
        # A section can appear more than once (cross-references inside other
        # sections). The longest body is the real codified text.
        if num not in out or len(body) > len(out[num]["body"]):
            out[num] = {"title": title, "body": body}
    return out


def _sort_key(section: str) -> float:
    """170.2 belongs before 170.10. String sort puts it after 170.1 and 170.10."""
    try:
        part, sec = section.split(".", 1)
        return int(part) * 1000 + float(re.sub(r"[^0-9.]", "", sec) or 0)
    except Exception:
        return 0.0


def _summarize(a: str, b: str) -> tuple[str, float]:
    aw, bw = a.split(), b.split()
    ratio = difflib.SequenceMatcher(None, aw, bw, autojunk=False).ratio()
    if ratio > 0.995:
        return "unchanged", ratio
    if ratio < 0.45:
        return "rewritten", ratio
    return "modified", ratio


def run(docket_id: str, progress=None) -> dict:
    say = progress or (lambda m: None)

    docs = fedreg.find_documents(docket_id)
    # Same selection as the preamble parser, for the same reason: a correction
    # is typed "Rule" and diffing against it compares the wrong two documents.
    nprm, nprm_why = fedreg._pick(docs, "Proposed Rule")
    final, final_why = fedreg._pick(docs, "Rule")
    for line in nprm_why + final_why:
        say(f"  {line}")
    if not (nprm and final):
        return {"error": "need both a proposed and a final rule to diff"}

    say("fetching proposed and final rule text")
    a_text = fedreg.raw_text(nprm)
    b_text = fedreg.raw_text(final)
    a, b = sections(a_text), sections(b_text)
    say(f"{len(a)} sections in the proposal, {len(b)} in the final rule")
    if not a or not b:
        da, db = diagnose(a_text), diagnose(b_text)
        for label, d in (("proposal", da), ("final rule", db)):
            say(f"  {label}: {d['chars']:,} chars, {d['section_tokens']} section tokens, "
                f"{d['line_start_tokens']} at line start, "
                f"codified region {'found' if d['codified_region_found'] else 'NOT found'}")
            for smp in d["samples"][:3]:
                say(f"    | {smp}")
        return {
            "error": "no section headings matched in one of the documents",
            "diagnostics": {"proposed": da, "final": db},
            "hint": "Paste the sample lines above into an issue — the parser only "
                    "knows the heading conventions it has been shown.",
        }

    rows = []
    for num in sorted(set(a) | set(b), key=_sort_key):
        # Every row carries its docket. The table previously held whichever
        # docket was diffed most recently, and every reader reported it for
        # whatever docket was being viewed.
        pw = len((a[num]["body"] if num in a else "").split())
        fw = len((b[num]["body"] if num in b else "").split())
        base = {"docket_id": docket_id, "section": num, "sort_key": _sort_key(num),
                "words_proposed": pw, "words_final": fw}
        if num in a and num in b:
            kind, ratio = _summarize(a[num]["body"], b[num]["body"])
            rows.append({**base, "change_kind": kind, "similarity": round(ratio, 4),
                         "magnitude": round(1 - ratio, 4),
                         "proposed_text": a[num]["body"][:20000],
                         "final_text": b[num]["body"][:20000]})
        elif num in b:
            rows.append({**base, "change_kind": "added", "similarity": 0.0,
                         "magnitude": 1.0, "proposed_text": None,
                         "final_text": b[num]["body"][:20000]})
        else:
            rows.append({**base, "change_kind": "removed", "similarity": 0.0,
                         "magnitude": 1.0, "proposed_text": a[num]["body"][:20000],
                         "final_text": None})

    with store.db() as con:
        con.execute("DELETE FROM textdiff WHERE docket_id = ?", [docket_id])
    store.upsert("textdiff", rows)

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["change_kind"]] = counts.get(r["change_kind"], 0) + 1
    changed = sum(counts.get(k, 0) for k in CHANGED)
    rate = changed / max(len(rows), 1)
    mags = sorted(r["magnitude"] for r in rows if r["change_kind"] in CHANGED)
    out = {
        "sections": len(rows), **counts,
        "changed": changed,
        "change_rate": round(rate, 4),
        "median_magnitude": round(mags[len(mags) // 2], 4) if mags else 0.0,
        # When almost every section moved, "the section this comment cited
        # changed" stops distinguishing anything — every commenter who cited a
        # provision would read as a silent grant. That is not a finding, it is a
        # base rate, and the UI has to say so rather than render it as evidence.
        "discriminating": rate < 0.80,
    }
    store.log("textdiff", str(out))
    say(
        f"{changed}/{len(rows)} sections changed ({rate:.0%}), "
        f"{counts.get('added', 0)} added, {counts.get('removed', 0)} removed, "
        f"{counts.get('unchanged', 0)} untouched"
    )
    if not out["discriminating"]:
        say(f"  {rate:.0%} of sections moved — this rule was rewritten wholesale, so "
            f"'cited section changed' does not by itself distinguish one comment "
            f"from another. Magnitude is recorded per section and used instead.")
    return out


CHANGED = ("modified", "rewritten", "added", "removed")


# When most of a rule moved, mere movement is uninformative. A section rewritten
# far more than its peers still is. This is the percentile a section's magnitude
# must clear, relative to the rest of the rule, to count as evidence on a
# wholesale-rewrite docket.
STANDOUT_PERCENTILE = 0.60


def outcome_map(docket_id: str) -> dict[str, dict]:
    """Per comment: did any provision it cited actually change in the final rule?

    This is evidence of influence, not proof of it. A section can change for
    reasons unrelated to any comment, and a comment can succeed at a provision
    it never named. The ledger says "text changed at cited provision" and lets
    the reader draw the inference.
    """
    import json

    from . import provisions

    diffs = store.query(
        "SELECT section, change_kind, magnitude, words_proposed, words_final "
        "FROM textdiff WHERE docket_id = ?", [docket_id]
    )
    if diffs.empty:
        return {}
    kind_of = dict(zip(diffs.section, diffs.change_kind))
    mag_of = dict(zip(diffs.section, diffs.magnitude.fillna(0)))

    moved = diffs[diffs.change_kind.isin(CHANGED)]
    rate = len(moved) / max(len(diffs), 1)
    # On a wholesale rewrite, require a section to have moved more than its
    # peers before treating it as evidence for a particular comment.
    floor = 0.0
    if rate >= 0.80 and len(moved) >= 4:
        ordered = sorted(moved.magnitude.fillna(0))
        floor = ordered[int(len(ordered) * STANDOUT_PERCENTILE)]

    rows = store.query(
        "SELECT a.comment_id, a.provisions FROM analysis a "
        "JOIN comments c USING (comment_id) WHERE c.docket_id = ?",
        [docket_id],
    )
    out: dict[str, dict] = {}
    for r in rows.itertuples():
        try:
            cited = json.loads(r.provisions) if r.provisions else []
        except Exception:
            cited = []
        touched = []
        for p in cited:
            sec = provisions.section_of(p)
            if sec and kind_of.get(sec) in CHANGED:
                mag = float(mag_of.get(sec) or 0)
                if mag < floor:
                    continue          # moved no more than the rule as a whole
                touched.append(
                    {"section": sec, "change": kind_of[sec], "magnitude": round(mag, 3)}
                )
        if touched:
            touched.sort(key=lambda t: -t["magnitude"])
            out[r.comment_id] = {
                "changed": touched,
                "n": len(touched),
                "top_magnitude": touched[0]["magnitude"],
            }
    return out


def summary(docket_id: str | None = None) -> dict:
    """Base-rate facts the UI needs in order to caveat the silent-grant column."""
    if docket_id:
        df = store.query(
            "SELECT change_kind, magnitude FROM textdiff WHERE docket_id = ?",
            [docket_id])
    else:
        df = store.query("SELECT change_kind, magnitude FROM textdiff")
    if df.empty:
        return {"available": False}
    moved = df[df.change_kind.isin(CHANGED)]
    rate = len(moved) / len(df)
    mags = sorted(moved.magnitude.fillna(0))
    return {
        "available": True,
        "sections": len(df),
        "changed": len(moved),
        "change_rate": round(rate, 4),
        "median_magnitude": round(mags[len(mags) // 2], 4) if mags else 0.0,
        "discriminating": rate < 0.80,
    }
