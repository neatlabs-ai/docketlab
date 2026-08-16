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

"""Outcome linkage — the layer nobody else builds.

Everything upstream tells you what the public said. This tells you what the
agency did with it: which comments drew a substantive response, which drew a
one-line dismissal, and which drew nothing at all.

Two passes:
  1. Retrieval. Embed the agency's own paraphrase of each comment ("Comment:
     several respondents argued...") and match it against the real comments.
     Local embeddings, free, runs in seconds.
  2. Adjudication. For the top candidate pairs only, ask a model whether the
     agency accepted, partially accepted, or rejected the argument. Bounded
     cost because it runs on pairs, not on the cross product.

The unanswered set is the output that matters. A high-significance comment with
no matching response is either a parser miss or an agency that didn't engage —
and distinguishing those two is exactly the kind of question this tool exists
to make askable.
"""
from __future__ import annotations

import json
import re

import numpy as np

from . import analyze, config, semantic, settings, store, usage

TOP_K = 3

# Retrieval uses a *relative* margin, not an absolute cosine floor. The two
# embedding backends live on completely different scales — a correct match
# scores ~0.75 with a sentence transformer and ~0.30 with TF-IDF+SVD — so any
# fixed threshold is right for one backend and silently wrong for the other.
# Requiring the top candidate to stand out from its own row's distribution is
# scale-free and degrades honestly when a comment matches nothing in particular.
Z_MARGIN = 1.5
MIN_COSINE = 0.05

ADJUDICATE_PROMPT = """A federal agency responded to public comments in a final rule preamble.

THE COMMENT (as submitted to the docket):
---
{comment}
---

THE AGENCY'S PARAPHRASE OF THE COMMENT IT IS ANSWERING:
---
{agency_comment}
---

THE AGENCY'S RESPONSE:
---
{agency_response}
---

Return ONLY JSON:
{{
  "same_issue": true|false,   // is the agency answering THIS comment's argument?
  "verdict": "accepted" | "partial" | "rejected" | "unclear",
  "rationale": "<=30 words citing what the agency actually said"
}}

"accepted" means the agency changed the rule text or committed to the requested
action. "partial" means it moved some of the way or committed to future guidance.
"rejected" means it declined and explained why. "unclear" means the response
acknowledges without resolving. If same_issue is false, verdict is "unclear"."""


def _adjudicate(client, comment: str, resp_row) -> dict | None:
    prompt = ADJUDICATE_PROMPT.format(
        comment=comment[:14000],
        agency_comment=resp_row["comment_para"][:6000],
        agency_response=resp_row["response_para"][:8000],
    )
    try:
        r = client.messages.create(
            model=settings.get("model_deep"),
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        store.log("linkage", f"adjudicate failed: {type(e).__name__}: {e}")
        return None
    usage.record("anthropic", "adjudicate", 200, None, settings.get("model_deep"),
                 r.usage.input_tokens, r.usage.output_tokens)
    text = "".join(b.text for b in r.content if b.type == "text")
    return analyze._parse_json(text)


def run(docket_id: str, adjudicate: bool = True, progress=None) -> dict:
    say = progress or (lambda m: None)

    responses = store.query(
        """
        SELECT r.* FROM responses r
        JOIN documents d ON d.fr_doc_number = r.document_id
        WHERE d.docket_id = ?
        """,
        [docket_id],
    )
    if responses.empty:
        responses = store.query("SELECT * FROM responses")
    if responses.empty:
        return {"error": "no parsed agency responses — run the Federal Register stage"}

    comments = store.query(
        """
        SELECT c.comment_id, c.full_text, c.organization, c.word_count,
               d.campaign_id, a.significance, a.summary
        FROM comments c
        JOIN dedup d USING (comment_id)
        LEFT JOIN analysis a USING (comment_id)
        WHERE c.docket_id = ?
          AND (d.campaign_id IS NULL OR d.is_exemplar)
          AND c.full_text IS NOT NULL
        ORDER BY c.comment_id
        """,
        [docket_id],
    )
    if comments.empty:
        return {"error": "no analysis units — run dedup first"}

    say(f"embedding {len(responses)} agency responses and {len(comments)} comments")
    r_vecs = semantic.embed(
        [f"{c} {r}" for c, r in zip(responses.comment_para, responses.response_para)],
        cache_key=f"{docket_id}-resp",
    )
    c_vecs = semantic.embed(comments.full_text.tolist(), cache_key=docket_id)

    if r_vecs.shape[1] != c_vecs.shape[1]:
        # TF-IDF fallback fits separate spaces; refit jointly so they're comparable.
        joint = semantic.embed(
            comments.full_text.tolist()
            + [f"{c} {r}" for c, r in zip(responses.comment_para, responses.response_para)],
            cache_key=f"{docket_id}-joint",
        )
        c_vecs, r_vecs = joint[: len(comments)], joint[len(comments):]

    sims = c_vecs @ r_vecs.T
    client = None
    if adjudicate:
        try:
            client = analyze._client()
        except RuntimeError as e:
            say(f"retrieval only - {e}")

    rows, adjudicated = [], 0
    use_z = len(responses) >= 4
    for i, cid in enumerate(comments.comment_id):
        row = sims[i]
        mu, sd = float(row.mean()), float(row.std())
        order = np.argsort(-row)[:TOP_K]
        for j in order:
            score = float(row[j])
            if score < MIN_COSINE:
                continue
            if use_z and sd > 1e-6 and (score - mu) / sd < Z_MARGIN:
                continue
            rrow = responses.iloc[int(j)]
            verdict, rationale, method = None, None, "embedding"
            if client is not None:
                obj = _adjudicate(client, comments.full_text.iloc[i], rrow)
                adjudicated += 1
                if obj:
                    method = "adjudicated"
                    if not obj.get("same_issue"):
                        continue
                    verdict = obj.get("verdict")
                    rationale = (obj.get("rationale") or "")[:400]
            rows.append(
                {
                    "comment_id": cid,
                    "response_id": rrow["response_id"],
                    "score": round(score, 4),
                    "method": method,
                    "verdict": verdict,
                    "rationale": rationale,
                }
            )
            break  # one linkage per comment; the best-scoring candidate
        if (i + 1) % 50 == 0:
            say(f"linked {i + 1}/{len(comments)}")

    with store.db() as con:
        con.execute(
            "DELETE FROM linkage WHERE comment_id IN "
            "(SELECT comment_id FROM comments WHERE docket_id = ?)",
            [docket_id],
        )
    store.upsert("linkage", rows)

    linked = {r["comment_id"] for r in rows}
    unanswered = comments[~comments.comment_id.isin(linked)]
    high_unanswered = unanswered[unanswered.significance.fillna(0) >= 60]

    out = {
        "responses_parsed": len(responses),
        "units": len(comments),
        "linked": len(linked),
        "unlinked": len(comments) - len(linked),
        "high_significance_unanswered": len(high_unanswered),
        "adjudicated_pairs": adjudicated,
        "response_rate": round(len(linked) / max(len(comments), 1), 4),
    }
    store.log("linkage", str(out))
    say(
        f"{out['linked']}/{out['units']} units matched to a response; "
        f"{out['high_significance_unanswered']} high-significance comments unanswered"
    )
    return out
