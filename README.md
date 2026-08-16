<div align="center">

**NEATLABS™**

# DOCKETLAB

**What did the agency actually do with the public comments?**

[![CI](https://github.com/neatlabs-ai/docketlab/actions/workflows/ci.yml/badge.svg)](https://github.com/neatlabs-ai/docketlab/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](pyproject.toml)

[neatlabs.ai](https://neatlabs.ai) · [info@neatlabs.ai](mailto:info@neatlabs.ai)

</div>

---

When a federal agency proposes a rule, the public comments on it. The agency is then legally obliged to respond to the significant comments, and it does so in the preamble of the final rule — often hundreds of pages of prose.

Plenty of tools will summarize what the public said. Almost none will tell you **what the agency did with it.**

DOCKETLAB pulls the comments, works out what each one argued and which provision it attacked, then matches those arguments against the agency's own adjudications *and* against the changes between the proposed and final regulatory text. The output is a ledger: for every submission, whether it drew a response, what the agency said, and whether the rule moved.

Aggregate that and you can ask the question nobody has good data on — **what kind of comment actually works?**

Everything runs on your machine. Flask console on `127.0.0.1`, DuckDB and parquet on disk, embeddings on CPU. No server, no telemetry, no account.

---

## Quickstart

```bash
git clone https://github.com/neatlabs-ai/docketlab
cd docketlab
pip install -r requirements.txt
python -m docketlab fixture
```

Ten seconds, no keys, no network. It builds a synthetic docket with problems seeded at known positions and grades the pipeline against them.

```bash
python -m docketlab serve          # or LAUNCH_DOCKETLAB.bat on Windows
```

Add a free [api.data.gov](https://api.data.gov/signup/) key and an Anthropic key on the **Settings** tab, then pick a docket. `DOD-2023-OS-0063` (CMMC) is a good first run: closed, ~361 comments, and a final rule whose preamble parses cleanly.

Full operating manual: [docs/OPERATING.md](docs/OPERATING.md).

---

## What it looks like

<p align="center"><img src="docs/img/ledger.png" alt="The adjudication ledger: one row per submission, with the agency's response and verdict" width="880"></p>

The **ledger** — one row per submission, with the Federal Register page carrying
the agency's response and whether it was accepted, partially accepted, or
rejected.

<p align="center"><img src="docs/img/metrics.png" alt="Metrics: the four-way outcome grid" width="880"></p>

The **four-way grid** — answered and changed, answered only, changed with no
response (the silent grant), neither. With the base-rate warning that appears
when a rule was rewritten wholesale.

<p align="center"><img src="docs/img/silent-grants.png" alt="Silent grants: comments with no response whose cited section moved" width="880"></p>

**Silent grants** — comments that drew no written response but whose cited
section moved more than the rule as a whole.

## Two channels, not one

The insight that makes this different from comment summarization.

A comment can succeed two ways. The agency writes a response to it — or the agency quietly fixes the text and never mentions it. Editorial defect reports ("§170.17(a)(1) cites Level 3 where it means Level 2") almost never get a Comment/Response pair; the agency just corrects it.

Score only the preamble and a commenter who got exactly what they asked for looks identical to one who was ignored. DOCKETLAB diffs the codified text between proposed and final rule and reports the four-way outcome:

|                      | Text changed     | Text unchanged   |
| -------------------- | ---------------- | ---------------- |
| **Agency responded** | landed           | engaged          |
| **No response**      | **silent grant** | no engagement    |

---

## Pipeline

| Stage | What it does | Cost |
| --- | --- | --- |
| Pull comments | regulations.gov v4, attachments, PDF/DOCX text | API quota |
| Find campaigns | exact hash → MinHash → containment → template split | free, CPU |
| Cluster | local embeddings + HDBSCAN | free, CPU |
| Load final rule | Federal Register text, response-to-comments parse | free, no key |
| Diff rule text | proposed vs final codified text, section by section | free, no key |
| Extract arguments | provision-anchored claims, not sentiment | tokens |
| Link outcomes | comment → response, accepted/partial/rejected | tokens |

**Containment matters more than it sounds.** Jaccard alone splits a campaign the moment participants append a personal paragraph: a 55-word scaffold inside an 80-word submission scores ~0.69 and falls below any sane near-duplicate threshold, so one form letter appears as three campaigns. The containment pass catches scaffold-inside-variant and isolates the personal addition — real content the template didn't supply, and the most commonly discarded signal in comment analysis.

**The analysis is not sentiment.** "73% opposed" is the least useful sentence you can write about a docket. An agency isn't taking a vote; it's obliged to respond to significant comments. So the extractor records which provision a comment attacks, on what grounds, what it asks for, and whether it puts new evidence on the record.

---

## The rate limit problem

Comment *text* only exists on the per-item detail endpoint, and an api.data.gov key allows 1,000 requests per hour. Pulling a decade of comments that way takes years; GSA has declined to raise limits or provide bulk download.

DOCKETLAB handles this rather than pretending it away — it self-throttles below the ceiling, checkpoints after every comment so an exhausted quota costs nothing, and re-anchors on `lastModifiedDate` at the 20-page × 250-result pagination wall. The **Usage** tab reads remaining requests from the server's own rate-limit header rather than a local tally.

For anything past a few thousand comments, use the [Mirrulations](https://registry.opendata.aws/mirrulations/) mirror on AWS Open Data (PDF text already extracted) instead of the API. An S3 loader is the obvious next module.

---

## Verification

The fixture seeds problems with known answers so the pipeline can be *scored* rather than eyeballed:

| Check | Result |
| --- | --- |
| Exact-duplicate campaign caught | 100% |
| Near-duplicate campaign (personal inserts) caught | 100% |
| Personal inserts recovered from templates | 100% |
| Paraphrase family caught by MinHash | **0% — by design** |
| Paraphrase family recovered by embeddings | 100% |
| Substantive letters wrongly swept into a campaign | 0% |
| Answered submissions correctly linked | 100% |
| Unanswered submissions correctly left unlinked | 100% |

The 0% row is the point. MinHash cannot see a campaign whose members each ran the sponsor's talking points through a chatbot — no shared 5-grams. Skip the embedding stage and those look like thirty independent citizens.

`python stress.py` runs ~30 adversarial and scaling checks. Findings it has produced, all fixed:

- **Dedup was quadratic** — projected ~100 minutes at 40,000 comments, exactly the campaign-heavy case the pass exists for. Rebuilt on LSH Ensemble; now 3.1× cost for 3× data.
- **The pagination cursor was malformed** — the API returns ISO-8601 but its own filter accepts only `yyyy-MM-dd HH:mm:ss`, so it 400s past the 5,000-result wall.
- **A DuckDB connection per query**, unbounded attachment downloads, and an uncapped report that would produce an unopenable file on a large docket.

---

## Doctrine

- **Zero custody.** Everything runs locally. The corpus, keys, and analysis never leave your machine — there is no server to send them to.
- **Absent is not zero.** An unparsed preamble is unknown, not unanswered.
- **Collapsing is display, never deletion.** Campaign members keep their rows and counts always report true submission numbers. A campaign of 40,000 is a real political fact even when it contributes one argument.
- **Everything walks back.** Every figure traces to a comment ID, and every comment ID to a public document.
- **Two channels, not one.** A comment succeeds by drawing a response or by moving the text.

---

## Validation status

**The preamble parser has been verified against one agency.** Every figure in
this README — 114 comment/response pairs at 68% coverage, the outcome linkage,
the silent grants — comes from `DOD-2023-OS-0063` (CMMC, 32 CFR 170). DoD writes
plain `Comment: … Response: …` pairs, which the parser handles well.

Other agencies structure preambles differently, and some organize responses
thematically rather than as pairs. The parser knows three conventions; there are
more. It reports which one matched and what fraction of the preamble it covered,
so a poor result is visible rather than silent, and prints diagnostic samples
when it finds nothing — paste those into an issue and the convention can be
added.

Ingest, campaign detection, clustering, and the guards have been exercised on a
second agency (`EPA-HQ-OW-2023-0469`). That docket has no final rule, so it
confirms the pipeline correctly declines to run outcome linkage rather than
inventing a result — but it does not test the parser.

If you run a docket from a new agency, the parse line from **Load final rule** is
worth reporting either way. Successes tell us the conventions generalize;
failures tell us which one to add next.

## Reproducibility

Ingest, campaign detection, clustering, and the text diff are deterministic —
the same corpus produces the same output.

**Linkage is not exactly reproducible.** Embedding retrieval proposes candidates
and a model adjudicates each pair independently, so borderline matches can fall
either way between runs. Observed variation on a 56-unit docket was one link out
of thirty-seven. Aggregate rates are stable; an individual borderline row may
not be. If a specific linkage matters, open the comment and read the agency's
response beside the submitted text — the interface shows both for exactly this
reason.

## What it can't tell you

**Whether a comment caused a change.** A section moving after a comment cited it is evidence, not proof.

**Why a comment went unanswered.** Three different things produce the same mark: the agency didn't engage, the response sits in the part of the preamble the parser missed, or the agency acted without writing about it. The diff stage separates the third.

**Whether the machine judgements are right.** Argument types, significance, and verdicts are model output. They're reproducible and every one cites a comment ID and a Federal Register page — which means they're checkable, and worth checking before you quote them.

**Anything about a docket you only partly pulled.** The orphan-response count on the Metrics page shows how far off you are.

---

## Contributing

The most valuable contribution is **preamble conventions**. The parser knows three ways agencies structure their responses; there are more. If a final rule parses to zero pairs, that's a bug report worth filing even without a fix — see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License and attribution

Apache-2.0. Copyright 2026 Security 360, LLC DBA NEATLABS™.

Built from public data: the regulations.gov and Federal Register APIs.

> This product uses the Regulations.gov Data API but is neither endorsed nor certified by Regulations.gov.

---

<div align="center">

**NEATLABS™** · Tech for Civic Good

[neatlabs.ai](https://neatlabs.ai) · [info@neatlabs.ai](mailto:info@neatlabs.ai) · [github.com/neatlabs-ai](https://github.com/neatlabs-ai)

</div>
