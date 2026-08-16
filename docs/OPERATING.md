# DOCKETLAB v0.1

Local-first analysis of public comments on federal rulemaking dockets, through
to the part almost nobody builds: **what the agency actually did with them.**

Runs entirely on one machine. Flask console on `127.0.0.1:7910`, DuckDB and
parquet on disk, embeddings on CPU. The only metered cost is the LLM stage, and
the pipeline is arranged so that stage sees roughly 1–15% of the corpus.

---

## Quick start

```
pip install -r requirements.txt
LAUNCH_DOCKETLAB.bat
```

**Settings tab** takes your regulations.gov and Anthropic keys and saves them to
`%USERPROFILE%\DOCKETLAB_DATA\settings.json` — outside the source folder, so
re-extracting the zip never wipes them. Each key has a Test button. Once an
Anthropic key is saved, the model pickers populate from the models your key can
actually reach rather than a hardcoded list.

**Dockets tab** has two verified starters, a live search against the API, and a
preflight that tells you how many comments a docket holds and how much of your
hourly quota pulling it will cost — before you commit. Any pull can be capped,
and every pull is resumable, so raising the cap later picks up where it stopped.

Then, in the console, press **Build fixture** → **Find campaigns** → **Cluster**
→ **Link outcomes** → **Score fixture**. That runs the whole pipeline against a
synthetic docket with known ground truth, needs no network and no API keys, and
tells you in about ten seconds whether the install is sound.

For a real docket, set `DL_REGS_KEY` (free at https://api.data.gov/signup/) and
`ANTHROPIC_API_KEY` in the .bat file first.

---

## The recommended first real docket: `DOD-2023-OS-0063`

CMMC 32 CFR Part 170. Proposed rule 88 FR 89058 (Dec 26, 2023), final rule
89 FR 83092 (Oct 15, 2024), effective Dec 16, 2024.

Why this one rather than a bigger, louder docket:

- **It is closed with a published final rule.** Outcome linkage — the layer
  that makes this tool different — cannot be tested on an open docket. Most of
  the famous high-volume dockets (DEA marijuana rescheduling, for instance) have
  no final rule to link against, so they can only exercise the front half.
- **~361 submissions.** Small enough that a full pull with attachments fits
  inside one hourly API quota — roughly 15–25 minutes rather than two days. You
  can run the whole pipeline four times in an afternoon while tuning thresholds.
  See the rate-limit note below for why that matters more than it sounds.
- **A 140-page final rule with an unusually thorough response-to-comments
  section.** DoD uses the plain `Comment: … Response: …` convention, which is
  the cleanest case for the preamble parser. If linkage does not work here, it
  will not work anywhere, and you will know that on day one instead of week six.
- **Heavy attachment usage.** Trade associations, university consortia, and law
  firms filed PDFs. This exercises the extraction path that naive pipelines skip.
- **You can grade the output.** This is the real reason. Every other test docket
  gives you plausible-looking results you have no way to check. On CMMC you know
  which industry arguments actually moved DoD, so you can tell the difference
  between an analysis that is right and one that merely reads well.

What this docket does *not* test: mass-campaign dedup at scale. 361 comments has
no form-letter army. That is what the fixture is for — it seeds campaigns of
known size and composition. Run a campaign-heavy docket second, once the
linkage layer is trusted.

---

## Rate limits, which are the real constraint

Comment *text* only exists on the per-item detail endpoint. A docket of N
comments therefore costs N+ requests, and an api.data.gov key allows 1,000 per
hour. That is why bulk analysis of regulations.gov is rare: pulling a decade of
comments this way takes years, and GSA has declined to raise limits or provide
bulk download.

The ingest layer handles this rather than pretending it away:

- self-throttles below the ceiling instead of sprinting into a 429
- checkpoints to DuckDB after every single comment, so an exhausted quota costs
  you nothing — rerun after the reset and it resumes
- re-anchors on `lastModifiedDate` when it hits the 20-page × 250-result
  pagination wall, which is the documented workaround for dockets over 5,000

For anything larger than a few thousand comments, do not use the API at all.
Use the **Mirrulations** mirror on AWS Open Data (requester-pays S3, PDF text
already extracted), or the pre-processed parquet published by **spicy-regs**.
An S3 loader is the obvious next module and the natural place to take this if
the first docket goes well.

---

## Pipeline

| Stage | What it does | Cost |
|---|---|---|
| Pull comments | regulations.gov v4, attachments, PDF/DOCX text | API quota only |
| Find campaigns | exact hash → MinHash → **containment** → template split | free, CPU |
| Cluster | local embeddings + HDBSCAN | free, CPU |
| Load final rule | Federal Register text, response-to-comments parse | free, no key |
| Extract arguments | provision-anchored claims, not sentiment | tokens |
| Diff rule text | proposed vs final codified text, section by section | free, no key |
| Link outcomes | comment → agency response, accepted/partial/rejected | tokens |

**Two channels, not one.** A comment can succeed by drawing a written response
*or* by getting the text quietly fixed. Editorial defect reports — "§170.17(a)(1)
cites Level 3 where it means Level 2" — almost never get a Comment/Response pair;
the agency just corrects it. Scoring only the preamble marks a commenter who got
exactly what they asked for identically to one who was ignored. The text-diff
stage adds the second channel, and the **Metrics** tab shows the four-way grid:
answered and changed, answered only, changed only (the silent grant), neither.

**Containment matters more than it sounds.** Jaccard similarity alone splits a
campaign the moment participants append a personal paragraph: a 55-word
scaffold inside an 80-word submission scores ~0.69 and falls below any sane
near-duplicate threshold. The same form letter then shows up as three separate
campaigns. The containment pass catches scaffold-inside-variant, and the
template split isolates the personal addition — which is real content the
campaign did not supply, and the single most-discarded signal in comment
analysis.

**The analysis is not sentiment.** "73% opposed" is the least useful sentence
you can write about a docket. An agency is not taking a vote; it is obligated to
respond to significant comments. So the extractor records which provision a
comment attacks, on what grounds (statutory authority, cost, feasibility,
procedure), what it asks for, and whether it puts new evidence on the record.

---

## Metrics and reporting

The **Metrics** tab crosses what a comment *was* against what the agency *did* —
response rate by significance band, which argument grounds draw engagement and
how they fare when they do, whether putting new evidence on the record changes
anything, the most contested provisions, and the silent-grant list. Every rate
carries its own denominator, and anything under n=30 is labelled as indicative
rather than rendered as a confident bar.

**Download report** produces one self-contained HTML file: all charts, the full
ledger, a methodology section explaining how linkage was actually done, and a
limits section stating plainly what the numbers cannot support. No external
assets, no network — it opens on any machine and prints cleanly. That last part
is deliberate: a 66% response rate quoted without its parse coverage and corpus
completeness is a number someone will repeat in a room you aren't in.

---

## Finding dockets

**Dockets** searches by ID or subject and preflights size before you pull.

**Watch** is for when you know the sector but not the rulemaking. A profile is an
agency set plus a full-text subject filter; scanning sweeps every matching
proposal in a date window and classifies each result by what you can do with it:
`open` (comment window still accepting filings), `analyzable` (final rule
published, so outcome linkage applies), `closed` (window shut, no final rule
yet). There's also a government-wide "closing in 30 days" sweep.

This runs on the Federal Register API, not regulations.gov — it's unmetered, so
a twenty-agency sweep costs no quota, and its filters are considerably better.
The regulations.gov docket IDs come back inside the FR records, so a hit hands
straight off to the pull.

---

## Quota and cost

Two meters, one of which charges money.

**regulations.gov quota** is the binding constraint. Comment text costs one
request per comment against 1,000/hour, so a 40,000-comment docket is ~40 hours
of quota. The **Usage** tab reads remaining requests from the server's own
`X-RateLimit-Remaining` header rather than a local tally, so it stays accurate
even if the key was used elsewhere. Pulls are resumable.

**Token spend** comes only from argument extraction and the adjudication half of
linkage. Pulling, campaign detection, clustering, the Federal Register fetch and
the text diff are all free.

The cost projection is built from **what this docket actually cost**, not a
generic per-comment rate — because the two variables that drive the bill, the
collapse ratio and comment length, differ enormously between dockets. A
campaign-heavy docket of 40,000 can cost less to analyze than a technical one of
400, since 39,000 of those comments are the same letter. Prices are editable;
published rates change and a stale constant misstating costs is worse than none.

---

## Verification

The fixture seeds problems with known answers, so the pipeline can be *scored*
rather than eyeballed. Current results, TF-IDF fallback backend, 257 comments:

| Check | Result |
|---|---|
| Exact-duplicate campaign caught | 100% |
| Near-duplicate campaign (personal inserts) caught | 100% |
| Personal inserts recovered from templates | 100% |
| Paraphrase family caught by MinHash | 0% — *by design* |
| Paraphrase family recovered by embeddings | 100% |
| Substantive letters wrongly swept into a campaign | 0% |
| Answered submissions correctly linked to their response | 100% |
| Unanswered submissions correctly left unlinked | 100% |

The 0% row is the point. MinHash cannot see a campaign whose participants each
ran the sponsor's talking points through a chatbot — no shared 5-grams. If the
embedding stage is skipped, those comments look like 30 independent citizens.

**Adversarial suite** (`python stress.py`) — 30 checks across malformed HTML,
unparseable preambles, empty and single-comment dockets, degenerate text,
concurrent reads during writes, and scaling. Findings it produced, all fixed:

- **Dedup was quadratic.** The containment pass compared all pairs, measuring
  ~100 minutes projected at 40,000 comments — precisely the campaign-heavy case
  the pass exists for. Rebuilt on LSH Ensemble; now measured at 3.1x cost for 3x
  data, roughly 3 minutes at 43,000.
- **The pagination cursor was malformed.** regulations.gov returns
  `lastModifiedDate` as ISO-8601 but its own filter accepts only
  `yyyy-MM-dd HH:mm:ss`. Handing the value straight back 400s — and only on
  dockets past the 5,000-result wall, i.e. exactly the ones the cursor exists
  for.
- **A connection per query.** DuckDB was opened and closed once per comment
  during ingest, and a UI read during a write could collide. Now one guarded
  process-wide connection.
- **Unbounded attachment downloads.** Now streamed with a 60MB ceiling and a
  1,200-page PDF cap, so one oversized exhibit can't stall a pull.
- **Reports had no row cap.** A large docket would produce an unopenable file.
  Capped at 1,500 rows with the aggregate figures still computed over all.

**Known limits, stated plainly:**

- The preamble parser handles three agency conventions. Agencies that organize
  responses thematically rather than as comment/response pairs will parse
  poorly. The parser reports which convention matched and what fraction of the
  preamble it covered — treat low coverage as "unknown," not "no response."
- A "no response" mark is ambiguous between an agency that did not engage and a
  parser that missed. Check parse coverage before drawing conclusions.
- Linkage was validated on the fixture, where the correct answer is known. It
  has not yet been validated against a real preamble. That is the first thing
  the CMMC run is for.
- Sentence-transformers could not be exercised in the build sandbox (model
  download blocked), so the TF-IDF fallback is what the numbers above reflect.
  The real backend should do better, not worse — but confirm it on first run;
  the console prints which backend loaded.

---

## Doctrine

- Raw API payloads are written verbatim and never edited.
- Every derived number walks back to a comment ID, and every comment ID walks
  back to a document on regulations.gov.
- Collapsing a campaign is a *display* operation. Nothing is deleted, counts
  always report true submission numbers. A campaign of 40,000 is a real
  political fact even when it contributes one argument.
- Absent ≠ zero. An unparsed preamble is unknown, not unanswered.
