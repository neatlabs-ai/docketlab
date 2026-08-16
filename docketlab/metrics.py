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

"""Metrics.

The question worth answering is not "what did the public say" — every comment
tool answers that. It is "what kind of comment moves an agency." That requires
crossing what a comment *was* against what the agency *did*, which is only
possible because argument type, provision anchor, and adjudicated verdict all
live in the same store.

Every figure here carries its own denominator. A response rate computed over
six comments is not a finding, and the page says so rather than rendering a
confident bar.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict

from . import store, textdiff


def _has(v) -> bool:
    """pandas NA is not falsy — it raises. Every presence check goes through here."""
    return v is not None and str(v) not in ("nan", "<NA>", "NaT", "")


def _loads(v):
    try:
        return json.loads(v) if v else []
    except Exception:
        return []


def compute(docket_id: str) -> dict:
    base = store.query(
        """
        SELECT c.comment_id, c.organization, c.submitter, c.word_count,
               c.text_source, c.n_attachments,
               d.campaign_id, d.is_exemplar,
               a.stance, a.significance, a.argument_types, a.provisions,
               a.requested, a.novel_evidence, a.summary,
               l.response_id, l.verdict, l.score,
               r.fr_page
        FROM comments c
        JOIN dedup d USING (comment_id)
        LEFT JOIN analysis a USING (comment_id)
        LEFT JOIN linkage l USING (comment_id)
        LEFT JOIN responses r ON r.response_id = l.response_id
        WHERE c.docket_id = ?
          AND (d.campaign_id IS NULL OR d.is_exemplar)
        """,
        [docket_id],
    )
    m: dict = {"docket_id": docket_id, "units": len(base)}
    if base.empty:
        return m

    changed = textdiff.outcome_map(docket_id)
    m["textdiff"] = textdiff.summary()
    m["textdiff_available"] = m["textdiff"].get("available", False)

    analyzed = base[base.significance.notna()]
    m["analyzed"] = len(analyzed)
    m["submissions"] = store.scalar(
        "SELECT count(*) FROM comments WHERE docket_id = ?", [docket_id]
    ) or 0
    m["responses"] = store.scalar("SELECT count(*) FROM responses") or 0

    # ── Corpus shape ─────────────────────────────────────────────────────────
    m["text_source"] = dict(Counter(base.text_source.dropna()))
    m["with_attachments"] = int((base.n_attachments.fillna(0) > 0).sum())
    m["campaigns"] = int(base.campaign_id.notna().sum())
    m["median_words"] = int(base.word_count.median()) if len(base) else 0

    # ── Outcomes ─────────────────────────────────────────────────────────────
    linked = base[base.response_id.notna()]
    m["linked"] = len(linked)
    m["response_rate"] = round(len(linked) / len(base), 4) if len(base) else 0
    m["verdicts"] = dict(Counter(linked.verdict.dropna()))
    m["stances"] = dict(Counter(analyzed.stance.dropna()))

    # Orphaned adjudications: agency responses matching nothing in the corpus.
    orphans = store.scalar(
        "SELECT count(*) FROM responses WHERE response_id NOT IN "
        "(SELECT response_id FROM linkage WHERE response_id IS NOT NULL)"
    ) or 0
    m["orphan_responses"] = int(orphans)

    # ── Response rate by significance band — does salience predict a reply? ──
    bands = [(0, 19), (20, 39), (40, 59), (60, 79), (80, 100)]
    m["by_significance"] = []
    for lo, hi in bands:
        sub = analyzed[(analyzed.significance >= lo) & (analyzed.significance <= hi)]
        n = len(sub)
        m["by_significance"].append(
            {
                "band": f"{lo}–{hi}",
                "n": n,
                "answered": int(sub.response_id.notna().sum()),
                "rate": round(float(sub.response_id.notna().mean()), 4) if n else None,
            }
        )

    # ── Which grounds move an agency ─────────────────────────────────────────
    by_arg = defaultdict(lambda: {"n": 0, "answered": 0, "accepted": 0, "partial": 0,
                                  "rejected": 0})
    for r in analyzed.itertuples():
        for t in _loads(r.argument_types):
            b = by_arg[t]
            b["n"] += 1
            if _has(r.response_id):
                b["answered"] += 1
                if r.verdict in ("accepted", "partial", "rejected"):
                    b[r.verdict] += 1
    m["by_argument"] = sorted(
        (
            {
                "type": k,
                **v,
                "rate": round(v["answered"] / v["n"], 4) if v["n"] else None,
                # A rate over a handful of comments should not render as a full
                # bar. The template dims anything below this.
                "thin": v["n"] < 10,
                "win": round((v["accepted"] + 0.5 * v["partial"]) / v["answered"], 4)
                if v["answered"]
                else None,
            }
            for k, v in by_arg.items()
        ),
        key=lambda x: -x["n"],
    )

    # ── Most contested provisions ────────────────────────────────────────────
    prov = Counter()
    prov_answered = Counter()
    for r in analyzed.itertuples():
        seen = set(_loads(r.provisions))
        for p in seen:
            prov[p] += 1
            if _has(r.response_id):
                prov_answered[p] += 1
    m["provisions"] = [
        {"provision": p, "n": n, "answered": prov_answered[p]}
        for p, n in prov.most_common(12)
    ]

    # ── Does putting evidence on the record help? ────────────────────────────
    ev = analyzed[analyzed.novel_evidence.fillna(False) == True]  # noqa: E712
    noev = analyzed[analyzed.novel_evidence.fillna(False) != True]  # noqa: E712
    m["evidence"] = {
        "with": {
            "n": len(ev),
            "rate": round(float(ev.response_id.notna().mean()), 4) if len(ev) else None,
        },
        "without": {
            "n": len(noev),
            "rate": round(float(noev.response_id.notna().mean()), 4) if len(noev) else None,
        },
    }

    # ── The four-way outcome grid: preamble response × text change ───────────
    grid = {"answered_changed": 0, "answered_only": 0, "changed_only": 0, "neither": 0}
    silent = []
    for r in base.itertuples():
        answered = _has(r.response_id)
        moved = r.comment_id in changed
        if answered and moved:
            grid["answered_changed"] += 1
        elif answered:
            grid["answered_only"] += 1
        elif moved:
            grid["changed_only"] += 1
            silent.append(
                {
                    "comment_id": r.comment_id,
                    "who": r.organization or r.submitter or "Individual commenter",
                    "summary": r.summary,
                    "significance": int(r.significance or 0),
                    "changed": changed[r.comment_id]["changed"],
                    "top_magnitude": changed[r.comment_id].get("top_magnitude", 0),
                }
            )
        else:
            grid["neither"] += 1
    m["outcome_grid"] = grid
    # Rank by how far the cited section moved, then by significance — on a rule
    # where everything changed, magnitude is what separates evidence from noise.
    m["silent_wins"] = sorted(
        silent, key=lambda x: (-x.get("top_magnitude", 0), -x["significance"])
    )[:15]

    # ── Unanswered and significant: the accountability list ──────────────────
    un = analyzed[analyzed.response_id.isna() & (analyzed.significance >= 60)]
    m["unanswered_significant"] = [
        {
            "comment_id": r.comment_id,
            "who": r.organization or r.submitter or "Individual commenter",
            "summary": r.summary,
            "significance": int(r.significance),
            "provisions": _loads(r.provisions),
            "moved": r.comment_id in changed,
        }
        for r in un.sort_values("significance", ascending=False).itertuples()
    ][:20]

    # ── Cost ─────────────────────────────────────────────────────────────────
    tok = store.query(
        "SELECT coalesce(sum(tokens_in),0) i, coalesce(sum(tokens_out),0) o, "
        "count(*) n FROM analysis a JOIN comments c USING (comment_id) "
        "WHERE c.docket_id = ?",
        [docket_id],
    )
    m["tokens"] = {
        "in": int(tok.i[0]),
        "out": int(tok.o[0]),
        "per_unit": round((int(tok.i[0]) + int(tok.o[0])) / max(int(tok.n[0]), 1)),
    }
    return m


def caution(n: int) -> str | None:
    """Honest labelling for small denominators."""
    if n == 0:
        return "no data"
    if n < 10:
        return f"n={n} — too few to read as a rate"
    if n < 30:
        return f"n={n} — indicative only"
    return None
