# Changelog

All notable changes to DOCKETLAB.

## [0.7.0] — 2026-08-16

First release prepared for publication.

### Added
- **Validation status** stated plainly in the README, the guide, and the exported
  report: the preamble parser is verified against one agency (DoD). Other
  agencies' conventions are unverified, the parser reports its own coverage, and
  a miss prints diagnostic samples that can be pasted into an issue.
- **Reproducibility note.** Ingest, campaign detection, clustering and the text
  diff are deterministic. Linkage is not exactly so — retrieval proposes
  candidates and a model adjudicates each independently, so a borderline match
  can fall either way. Observed variation: one link in thirty-seven.
- **Starter dockets are editable** (`starters.json`) and now include a third
  case, `EPA-HQ-OW-2023-0469`, which has no final rule — an example of the
  pipeline correctly declining to produce an answer that does not exist.
- Screenshots section and `docs/img/` scaffold.

### Changed
- The **significance prompt** now defines all five bands explicitly. The scale
  was compressed in practice, with nothing scoring above 79 on a real docket.
- **Rates over fewer than ten observations render hatched, not solid.** A
  full-width confident bar on n=2 overstated what the data supported.
- Starter descriptions rewritten in third person for a public audience.

### Fixed
- The **agency responses tile counted globally**, so one docket's adjudications
  appeared under another.
- **The console did not follow the docket you just pulled**, so a pull started
  from the Dockets tab could leave the next stage pointed at the previous
  corpus without saying so.

## [0.6.3] — 2026-08-16

### Fixed
- **Schema changes broke existing installs.** `CREATE TABLE IF NOT EXISTS` does
  nothing when the table already exists, so the columns added in 0.6.2 upgraded
  new databases and left upgraded ones without them — the text diff stage failed
  with a binder error on any database created before 0.6.2. `store.migrate()`
  now diffs declared columns against actual ones on every start and adds what's
  missing. Widening only: nothing is dropped or retyped, so an upgrade cannot
  lose data.

  This was a whole class of bug rather than one instance — without it, every
  future schema change would break every existing user. The stress suite now
  builds a database with the older schema and verifies both the upgrade and the
  survival of existing rows.

## [0.6.2] — 2026-08-16

Follow-up to the first live text diff on `DOD-2023-OS-0063`, which changed all
24 of 24 sections and exposed a measurement problem rather than a parsing one.

### Added
- **Change magnitude is recorded per section** (similarity, magnitude, and word
  counts), not just a category. A section rewritten at 0.06 similarity is
  different evidence from one nudged at 0.91.
- **Base-rate honesty.** When 80% or more of a rule's sections changed, "the
  cited section changed" is true of nearly every comment and distinguishes
  almost nothing. Metrics and the exported report now say so plainly, and the
  silent-grant channel falls back to counting only sections that moved
  substantially more than the rule as a whole.
- **Read-only database access** — `store.reader()` and `store.read_query()`.
  DuckDB's read-write handle takes an exclusive lock, which on Windows blocks
  even a file copy, so inspecting a live instance previously meant shutting the
  app down.
- **`inspect` and `sql` CLI commands**: `inspect tables`, `inspect diff`,
  `inspect quota`, and ad-hoc read-only SQL, all usable while the console runs.

### Fixed
- Sections sorted as strings, putting 170.10 before 170.2.

## [0.6.1] — 2026-08-16

Fixes from the first live run against `DOD-2023-OS-0063`.

### Fixed
- **Rule text sections were never detected.** The heading pattern required the
  section title on the same line as the number. Federal Register full text often
  puts it on the next line, so a real DoD rule matched nothing and reported zero
  sections without saying why. Detection now handles same-line, next-line, and
  `Sec.` forms, rejects cross-references (`§§ 170.4 and 170.5`), and prints
  diagnostics — token counts and verbatim samples — when it finds nothing.
- **A section title on its own line leaked into the body**, making otherwise
  identical sections read as `modified`. Spurious diffs are the one thing the
  silent-grant channel must not produce.
- **Docket IDs from the Federal Register carry labels.** `docket_ids` returns
  values like `Docket DARS-2020-0034`, so every hand-off from a Watch scan to a
  pull produced a 400. IDs are now normalized on entry, and records with no
  derivable ID are flagged in the UI instead of offering a button that fails.
- **`api_calls` was created lazily**, so `/usage` returned 500 on a fresh
  install before any API call had been made. Moved into the base schema.
- **A second instance produced a raw DuckDB traceback.** It now explains that
  another instance holds the data directory and what to do about it.
- **The Windows launcher retried with `py` on any failure**, burying the real
  error under an unrelated one. It now picks an interpreter once, up front.

### Changed
- The console shows **with attachments** alongside attachment-only. A comment
  carrying both inline text and a PDF counts as `both`, so attachment-only can
  read zero while extraction is working perfectly — as it was.

## [0.6.0] — 2026-08-16

Initial public release.

### Added
- Ingest from the regulations.gov v4 API with self-throttling, per-comment
  checkpointing, and `lastModifiedDate` re-anchoring past the pagination wall.
- Attachment text extraction (PDF, DOCX) with scanned-document flagging.
- Campaign detection: exact hashing, MinHash near-duplicates, LSH Ensemble
  containment, and template/insert separation.
- Local semantic clustering with a TF-IDF fallback.
- Federal Register preamble parsing into comment/response pairs across three
  agency conventions, with reported parse coverage.
- **Outcome linkage** — embedding retrieval plus per-pair model adjudication
  into accepted / partial / rejected.
- **Text diff** — proposed vs final codified text, giving a second channel by
  which a comment can be shown to have succeeded.
- Metrics: four-way outcome grid, response rate by significance, argument type
  against verdict, evidence effect, contested provisions, orphan responses.
- Self-contained HTML report with methodology and limits sections.
- Watchlists: agency and subject profiles scanned against the Federal Register,
  classified as open / analyzable / closed, plus a closing-soon sweep.
- Usage tab: live quota gauges from server rate-limit headers, spend by model,
  and a cost projection built from the docket's own observed per-unit cost.
- In-app guide, and a fixture harness that grades the pipeline against seeded
  ground truth.

### Notes
- Verified end to end against `DOD-2023-OS-0063` (CMMC, 32 CFR 170): 369
  comments, 114 parsed agency responses at 68% preamble coverage.
