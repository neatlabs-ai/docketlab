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

"""Synthetic docket with known ground truth.

Built so the pipeline can be verified without network access and, more
importantly, so dedup and linkage can be *scored* rather than eyeballed. A
seeded fixture tells you your near-duplicate threshold is wrong; a real docket
just gives you plausible-looking output you have no way to check.

Seeded problems, deliberately:
  - an exact-duplicate campaign (trivially catchable)
  - a near-duplicate campaign with personalized inserts (tests template split)
  - a paraphrase family sharing no 5-grams (defeats MinHash on purpose —
    this is the AI-assisted campaign case, and it SHOULD fall to embeddings)
  - substantive org letters with novel evidence
  - a "see attached" comment with empty inline text
  - two high-significance comments the synthetic final rule never answers
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from . import store

DOCKET = "FIXTURE-2026-0001"
RULE_TITLE = "Fixture Rule: Minimum Safety Standards for Widget Manufacturing"

FORM_LETTER = (
    "I am writing to oppose the proposed widget safety rule. This regulation "
    "will impose crushing costs on small manufacturers in my community without "
    "delivering any measurable safety benefit. The agency has not justified its "
    "cost estimates. I urge the agency to withdraw this proposal."
)

INSERTS = [
    "My family has run a widget shop in Ohio for forty-one years and we employ nine people. "
    "A twelve thousand dollar compliance cost is more than our entire annual equipment budget.",
    "I lost a finger to a widget press in 1998 and I still oppose this rule, because the "
    "guarding requirement in section 4 would not have prevented my injury.",
    "As a third generation machinist I want to add that the training requirement conflicts "
    "with the apprenticeship schedule our state already mandates.",
]

PARAPHRASES = [
    "The proposed widget standard should be withdrawn. Small shops cannot absorb the "
    "expenditure, and nothing in the record demonstrates a corresponding reduction in injuries.",
    "This rulemaking ought to be pulled back. The financial burden falls hardest on modest "
    "manufacturers, while the safety case remains unproven in the docket.",
    "I ask the agency to rescind this proposal. Independent widget makers face expenses they "
    "cannot bear, and the asserted injury reductions are not supported by the evidence presented.",
    "Please do not finalize this standard. The compliance outlay for a small operation is "
    "prohibitive and the agency's own analysis fails to establish a genuine safety gain.",
]

ORG_LETTERS = [
    (
        "National Widget Manufacturers Association",
        "The Association submits these comments on the proposed rule at 90 FR 11111. "
        "Section 4.2(b) of the proposal would require redundant interlocks on all Class II "
        "presses. Our 2025 member survey (n=413, methodology at Appendix B) found a median "
        "retrofit cost of $18,400 per press, substantially above the agency's $6,200 estimate "
        "in the Regulatory Impact Analysis. The agency's figure appears to draw on 2011 "
        "pricing without escalation. We further submit that the agency lacks statutory "
        "authority under section 6(b) of the Widget Safety Act to regulate presses used "
        "solely for prototype fabrication. We request that section 4.2(b) be modified to "
        "exempt prototype-only equipment and that the cost analysis be reopened for comment.",
    ),
    (
        "Widget Workers United, Local 42",
        "Local 42 supports the proposed rule and urges the agency to strengthen it. Bureau of "
        "Labor Statistics data for 2020 through 2024 shows widget press amputations rising "
        "14 percent while overall manufacturing injury rates declined. The proposal's "
        "eighteen-month compliance window in section 7.1 is too long given that trend; we "
        "request twelve months. We also request that section 5 training requirements specify "
        "a minimum of eight hours rather than leaving duration to employer discretion.",
    ),
    (
        "Institute for Regulatory Restraint",
        "The proposed rule exceeds the agency's delegated authority and should be withdrawn. "
        "Under the major questions doctrine, an agency may not resolve a question of vast "
        "economic significance absent clear congressional authorization. The Widget Safety "
        "Act nowhere authorizes equipment design mandates. The agency also failed to comply "
        "with the Regulatory Flexibility Act by omitting an adequate small entity analysis.",
    ),
    (
        "State Association of Occupational Health Directors",
        "We write regarding the interaction between the proposed federal standard and existing "
        "state plans. Twenty-two states operate approved plans with widget provisions already "
        "in effect. Section 9 of the proposal is silent on preemption. We request that the "
        "final rule expressly address whether more protective state requirements survive, and "
        "we ask the agency to clarify the compliance date for facilities in state plan states.",
    ),
]

# These two get no response in the synthetic final rule, on purpose.
UNANSWERED = [
    (
        "Coalition for Rural Manufacturing",
        "Our comment concerns section 11.3, the recordkeeping provision. The proposal requires "
        "retention of calibration logs for seven years in electronic form. Roughly a third of "
        "our member facilities lack reliable broadband; we surveyed 87 rural shops and 29 "
        "reported connection speeds below 3 Mbps. We request that section 11.3 permit paper "
        "recordkeeping as an alternative for facilities in areas designated as unserved.",
    ),
    (
        "Dr. Alma Reyes, Professor of Industrial Engineering",
        "I submit peer-reviewed findings relevant to section 4.2. My laboratory's 2025 study "
        "in the Journal of Machine Safety (attached) measured interlock failure rates across "
        "1,240 press-hours and found that redundant interlocks of the type specified in the "
        "proposal exhibited a 3.1 percent nuisance-trip rate, which in field conditions leads "
        "operators to bypass the guard entirely. The proposed specification may therefore "
        "reduce net safety. I recommend a performance standard in place of the design mandate.",
    ),
]

FINAL_RULE = """
[[Page 55001]]
DEPARTMENT OF WIDGETS
Fixture Rule: Minimum Safety Standards for Widget Manufacturing
AGENCY: Widget Safety Administration. ACTION: Final rule.

SUMMARY: The agency adopts minimum safety standards for widget manufacturing.

III. Discussion of Public Comments

Comment: A trade association and numerous individual manufacturers stated that the
retrofit cost estimate in the Regulatory Impact Analysis was too low, citing a member
survey showing a median cost substantially above the agency's figure, and asserted that
the agency's pricing data was outdated.

Response: The agency has reviewed the submitted survey and agrees that the original
estimate did not adequately escalate equipment pricing. The agency has revised the cost
estimate in the final Regulatory Impact Analysis and has modified Sec. 4.2(b) to exempt
equipment used solely for prototype fabrication, as requested.

[[Page 55014]]
Comment: A commenter argued that the agency lacks statutory authority to impose equipment
design mandates and invoked the major questions doctrine, and separately asserted a failure
to comply with the Regulatory Flexibility Act.

Response: The agency disagrees. Section 6(b) of the Widget Safety Act expressly authorizes
the agency to prescribe means of compliance where performance standards have proven
inadequate. The agency prepared and published an initial regulatory flexibility analysis
concurrently with the proposed rule.

Comment: A labor organization requested that the compliance window in Sec. 7.1 be shortened
from eighteen to twelve months and that training duration be specified as a minimum number
of hours.

Response: The agency declines to shorten the compliance window, which reflects equipment
lead times documented in the record. The agency has revised Sec. 5 to specify a minimum of
eight hours of training, as requested.

[[Page 55022]]
Comment: Several commenters raised the relationship between this standard and existing
approved state plans, and requested clarification regarding preemption and compliance dates.

Response: The agency has added Sec. 9(d) to the final rule clarifying that approved state
plans may impose requirements at least as protective as this standard, and specifying the
compliance date applicable in state plan states.

Comment: Many individual commenters expressed general opposition to the rule on the grounds
of cost to small manufacturers.

Response: The agency acknowledges these concerns and has addressed the cost issues in the
revised Regulatory Impact Analysis discussed above. Where commenters did not identify
specific provisions or supply supporting data, the agency was unable to make further
targeted adjustments.
"""


def build(n_exact: int = 120, n_near: int = 90, seed: int = 7,
          progress=None) -> dict:
    """Materialize the fixture docket directly into the store."""
    say = progress or (lambda m: None)
    rng = random.Random(seed)
    store.init()

    with store.db() as con:
        for t in ("comments", "dedup", "clusters", "analysis", "linkage"):
            con.execute(
                f"DELETE FROM {t} WHERE comment_id IN "
                f"(SELECT comment_id FROM comments WHERE docket_id = '{DOCKET}')"
                if t != "comments"
                else f"DELETE FROM comments WHERE docket_id = '{DOCKET}'"
            )
        con.execute("DELETE FROM responses WHERE document_id = 'FIXTURE-FINAL'")

    store.upsert(
        "dockets",
        [{"docket_id": DOCKET, "title": RULE_TITLE, "agency": "WSA",
          "docket_type": "Rulemaking", "fetched_at": None}],
    )
    store.upsert(
        "documents",
        [{"document_id": "FIXTURE-NPRM", "docket_id": DOCKET,
          "document_type": "Proposed Rule", "title": RULE_TITLE,
          "posted_date": "2026-01-05", "fr_doc_number": "FIXTURE-NPRM",
          "comment_count": None},
         {"document_id": "FIXTURE-FINAL", "docket_id": DOCKET,
          "document_type": "Rule", "title": RULE_TITLE,
          "posted_date": "2026-07-20", "fr_doc_number": "FIXTURE-FINAL",
          "comment_count": None}],
    )

    base = datetime(2026, 2, 1, 9, 0, 0)
    rows, truth = [], {}
    n = 0

    def add(text, org=None, name=None, truth_label=None, attach=0, inline=True):
        nonlocal n
        n += 1
        cid = f"{DOCKET}-{n:05d}"
        truth[cid] = truth_label
        body = text if inline else "See attached."
        attach_text = "" if inline else text
        full = f"{body}\n\n{attach_text}".strip()
        rows.append(
            {
                "comment_id": cid, "docket_id": DOCKET,
                "document_id": "FIXTURE-NPRM",
                "posted_date": base + timedelta(minutes=7 * n),
                "received_date": base + timedelta(minutes=7 * n),
                "submitter": name, "organization": org,
                "submitter_type": "Organization" if org else "Individual",
                "title": "Comment on widget rule",
                "body": body, "attach_text": attach_text or None,
                "full_text": full, "n_attachments": attach,
                "text_source": "both" if (not inline and attach) else "inline",
                "word_count": len(full.split()),
            }
        )
        return cid

    for _ in range(n_exact):
        add(FORM_LETTER, truth_label="campaign_exact")
    for i in range(n_near):
        add(f"{FORM_LETTER} {INSERTS[i % len(INSERTS)]}", truth_label="campaign_near")
    # Paraphrase family: combinatorially assembled so no two share 5-grams.
    # MinHash should miss these entirely; embeddings should recover them.
    asks = ["I ask the agency to withdraw this proposal.",
            "Please do not finalize this standard.",
            "This rulemaking ought to be pulled back.",
            "The proposed widget standard should be rescinded.",
            "I respectfully request that this measure be abandoned."]
    burdens = ["Small shops cannot absorb the expenditure.",
               "Modest manufacturers face outlays they cannot bear.",
               "Independent widget makers confront prohibitive expenses.",
               "The financial weight lands hardest on tiny operations.",
               "Family-run businesses have no room for this cost."]
    evidence = ["Nothing in the record demonstrates a matching drop in injuries.",
                "The asserted harm reductions are unsupported by what was filed.",
                "The agency's own analysis fails to establish a genuine gain.",
                "No submitted material shows the promised improvement in outcomes.",
                "The claimed benefit remains unproven throughout the docket."]
    for i in range(30):
        text = " ".join([
            asks[i % len(asks)],
            burdens[(i // 2) % len(burdens)],
            evidence[(i // 3) % len(evidence)],
        ])
        add(text, truth_label="campaign_paraphrase")
    for text in PARAPHRASES:
        add(text, truth_label="campaign_paraphrase")
    for org, text in ORG_LETTERS:
        add(text, org=org, truth_label="substantive_answered", attach=1, inline=False)
    for org, text in UNANSWERED:
        add(text, org=org, truth_label="substantive_unanswered", attach=1, inline=False)
    add("See attached.", org="Empty Attachment Co.", truth_label="empty", attach=1)
    for i in range(6):
        add(
            f"I have been a widget operator for {rng.randint(3, 30)} years and I think the "
            f"rule is {'a good idea' if i % 2 else 'unnecessary'}. Please consider "
            f"the practical realities of shop floor work.",
            truth_label="singleton_low",
        )

    store.upsert("comments", rows)

    from . import fedreg
    diag = fedreg.parse_responses("FIXTURE-FINAL", FINAL_RULE)

    (store.config.RAW / "fixture_truth.json").write_text(
        __import__("json").dumps(truth, indent=1), encoding="utf-8"
    )
    out = {"docket_id": DOCKET, "comments": len(rows), **diag}
    say(f"fixture built: {len(rows)} comments, {diag['pairs']} response pairs")
    store.log("fixture", str(out))
    return out


def score(progress=None) -> dict:
    """Grade the pipeline against the seeded ground truth."""
    import json as _json

    truth = _json.loads((store.config.RAW / "fixture_truth.json").read_text())
    df = store.query(
        """
        SELECT c.comment_id, d.campaign_id, d.is_exemplar, d.insert_text,
               cl.cluster_id, a.significance, l.response_id
        FROM comments c
        LEFT JOIN dedup d USING (comment_id)
        LEFT JOIN clusters cl USING (comment_id)
        LEFT JOIN analysis a USING (comment_id)
        LEFT JOIN linkage l USING (comment_id)
        WHERE c.docket_id = ?
        """,
        [DOCKET],
    )
    df["truth"] = df.comment_id.map(truth)

    exact = df[df.truth == "campaign_exact"]
    near = df[df.truth == "campaign_near"]
    para = df[df.truth == "campaign_paraphrase"]
    subs = df[df.truth.isin(["substantive_answered", "substantive_unanswered"])]

    res = {
        "exact_campaign_caught": float(exact.campaign_id.notna().mean()) if len(exact) else None,
        "near_campaign_caught": float(near.campaign_id.notna().mean()) if len(near) else None,
        "near_inserts_recovered": float(near.insert_text.notna().mean()) if len(near) else None,
        "paraphrase_caught_by_minhash": float(para.campaign_id.notna().mean()) if len(para) else None,
        "paraphrase_grouped_by_embedding": (
            float((para.cluster_id.fillna(-1) >= 0).mean()) if len(para) else None
        ),
        "substantive_not_swept_into_campaign": (
            float(subs.campaign_id.isna().mean()) if len(subs) else None
        ),
        "answered_linked": float(
            df[df.truth == "substantive_answered"].response_id.notna().mean()
        ) if (df.truth == "substantive_answered").any() else None,
        "unanswered_correctly_unlinked": float(
            df[df.truth == "substantive_unanswered"].response_id.isna().mean()
        ) if (df.truth == "substantive_unanswered").any() else None,
    }
    store.log("fixture-score", str(res))
    if progress:
        progress(str(res))
    return res
