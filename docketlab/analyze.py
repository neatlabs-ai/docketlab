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

"""Argument extraction.

Deliberately not sentiment. "73% opposed" is the least useful sentence you can
write about a docket: an agency is not taking a vote, it is obligated to
respond to significant comments. What matters is which provision a comment
attacks, on what grounds, what it asks for instead, and whether it puts new
evidence on the record.

Model routing: campaign exemplars and short singletons go to the cheap model;
long submissions and anything the triage pass flags as carrying evidence go to
the capable one. That funnel is where the cost savings actually live.
"""
from __future__ import annotations

import json
import re

from . import config, provisions, settings, store, usage

SCHEMA_PROMPT = """You are analyzing one public comment submitted on a proposed U.S. federal regulation.

RULE UNDER COMMENT: {rule_title}

Return ONLY a JSON object, no preamble, no markdown fences:
{{
  "stance": "support" | "oppose" | "mixed" | "neutral",
  "argument_types": [...],        // any of: statutory_authority, apa_procedure,
                                  // technical, scientific, economic_cost,
                                  // feasibility, small_business, equity,
                                  // privacy, security, definitional, none
  "provisions": [...],            // section numbers ONLY, exactly as cited, e.g.
                                  // "170.19(c)(1)" or "252.204-7012". Never a URL, never
                                  // a page number, never a prose description. Empty list
                                  // if the comment cites no section.
  "requested": [...],             // ONLY from this list, and only ones you can point
                                  // to a sentence for: "withdraw", "extend_comment_period",
                                  // "modify_text", "clarify", "delay_effective_date",
                                  // "add_exemption", "no_change". Omit rather than guess;
                                  // an empty list is a valid and useful answer.
  "novel_evidence": true|false,   // does it put NEW data, a study, a survey, or a
                                  // cost estimate on the record? Restating the
                                  // agency's own figures is NOT novel evidence.
  "evidence_note": "one sentence naming the evidence, or empty string",
  "significance": 0-100,          // likelihood the agency is obligated to respond.
                                  // Use the whole scale — on a real docket the top
                                  // band should not be empty:
                                  //   85-100  cites a specific provision AND supplies
                                  //           data, a study, or a legal argument the
                                  //           agency must address on the record
                                  //   65-84   cites a specific provision with a
                                  //           concrete, reasoned request
                                  //   40-64   substantive but general, or a request
                                  //           without supporting reasoning
                                  //   15-39   an opinion with little specific content
                                  //   0-14    no readable or substantive content
  "summary": "<=35 words, the comment's actual argument, not its tone"
}}

Rules:
- Judge only what the text says. Do not infer positions the commenter did not take.
- If the text is empty, unreadable, or says only "see attached" with no attachment
  text, return stance "neutral", significance 0, and summary "no readable content".
- significance is about legal salience, not about whether you agree.
- Do not pad any list. Categories you cannot point to a sentence for do not belong.

COMMENT TEXT:
---
{text}
---"""


def _client():
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError(
            "pip install anthropic — needed for the analysis stage"
        ) from e
    if not settings.get("anthropic_key"):
        raise RuntimeError("No Anthropic key — add one on the Settings page")
    return anthropic.Anthropic(api_key=settings.get("anthropic_key"))


def _parse_json(raw: str) -> dict | None:
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def run(docket_id: str, rule_title: str = "", limit: int | None = None,
        progress=None) -> dict:
    say = progress or (lambda m: None)
    client = _client()

    df = store.query(
        """
        SELECT c.comment_id, c.full_text, c.word_count, c.organization,
               d.campaign_id, d.is_exemplar
        FROM comments c JOIN dedup d USING (comment_id)
        WHERE c.docket_id = ?
          AND (d.campaign_id IS NULL OR d.is_exemplar)
          AND c.full_text IS NOT NULL
          AND c.comment_id NOT IN (SELECT comment_id FROM analysis)
        ORDER BY c.word_count DESC
        """,
        [docket_id],
    )
    if df.empty:
        return {"analyzed": 0, "note": "nothing new to analyze"}
    if limit:
        df = df.head(limit)

    if not rule_title:
        rule_title = store.scalar(
            "SELECT title FROM dockets WHERE docket_id = ?", [docket_id]
        ) or docket_id

    rows, tin, tout, failures = [], 0, 0, 0
    for i, r in enumerate(df.itertuples(), start=1):
        deep = r.word_count >= 400 or bool(r.organization)
        model = settings.get("model_deep") if deep else settings.get("model_triage")
        prompt = SCHEMA_PROMPT.format(
            rule_title=rule_title, text=(r.full_text or "")[:60000]
        )
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=900,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:  # keep going; a single failure isn't fatal
            failures += 1
            store.log("analyze", f"{r.comment_id}: {type(e).__name__}: {e}")
            continue

        usage.record("anthropic", "messages", 200, None, model,
                     resp.usage.input_tokens, resp.usage.output_tokens)
        tin += resp.usage.input_tokens
        tout += resp.usage.output_tokens
        text = "".join(b.text for b in resp.content if b.type == "text")
        obj = _parse_json(text)
        if not obj:
            failures += 1
            continue

        rows.append(
            {
                "comment_id": r.comment_id,
                "stance": obj.get("stance"),
                "argument_types": json.dumps(obj.get("argument_types") or []),
                "provisions": json.dumps(provisions.clean(obj.get("provisions"))),
                "requested": json.dumps(obj.get("requested") or []),
                "novel_evidence": bool(obj.get("novel_evidence")),
                "evidence_note": (obj.get("evidence_note") or "")[:600] or None,
                "significance": int(obj.get("significance") or 0),
                "summary": (obj.get("summary") or "")[:600],
                "model": model,
                "tokens_in": resp.usage.input_tokens,
                "tokens_out": resp.usage.output_tokens,
            }
        )
        if i % 20 == 0:
            say(f"analyzed {i}/{len(df)}")
            store.upsert("analysis", rows)
            rows = []

    store.upsert("analysis", rows)
    out = {
        "analyzed": len(df) - failures,
        "failures": failures,
        "tokens_in": tin,
        "tokens_out": tout,
    }
    store.log("analyze", str(out))
    say(f"analysis done: {out['analyzed']} units, {tin:,} in / {tout:,} out tokens")
    return out
