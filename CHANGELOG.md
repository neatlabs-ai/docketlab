# Changelog

All notable changes to DOCKETLAB.

## [0.8.0] — 2026-08-17

Four bugs reported by [@abigailhaddad](https://github.com/abigailhaddad), each
with a reproduction script and measured evidence. All four were real, and two of
them meant the tool produced wrong output on most dockets while appearing to
work on the one it had been validated against.

### Fixed
- **#1 — document selection picked a correction instead of the final rule.**
  Corrections, interim final rules and technical amendments all carry
  `type: "Rule"`; supplemental proposals carry `type: "Proposed Rule"`. Choosing
  on type alone selected a 78-page correction over a 408-page final rule on
  `EPA-HQ-OAR-2021-0317`, and the superseded 2021 proposal over the 2022
  supplemental — so the preamble parse and the text diff both ran on the wrong
  documents. Selection now reads the `action` field, rejects ancillary actions,
  prefers a plain final rule over an interim one, breaks ties on page count, and
  logs which document it chose and why. `find_documents` is also paginated; it
  previously asked for fifty and stopped.
- **#2 — the `plain` convention opened pairs on ordinary prose.** The label
  accepted a full stop as well as a colon, so any sentence ending "...we
  received comments." started a match, and because `finditer` resumes at the end
  of each match one spurious start shifted every following boundary. Measured
  recall was 37% on SSA `2026-13420`, where the first match began 5,628
  characters before the document's first real label and 17 of 26 surviving pairs
  began inside a Response. Labels are now anchored to the start of a line and
  require a colon.
- **#3 — the comment side of a pair had no size bound.** Only the response side
  was checked against 20,000 characters; the comment side was then truncated to
  12,000 on the way into the store, so an overlong match was kept rather than
  rejected. On CMMC the largest comment side ran 153,766 characters from
  preamble prose into codified rule text, and the stored 12,000-character
  fragment is what linkage embedded and what the adjudicator was shown as the
  agency's paraphrase. Both sides are now bounded and an overlong match is
  dropped whole.
- **#4 — `textdiff` and `responses` were global, so a second docket overwrote
  the first.** `textdiff` had no `docket_id` and was cleared unconditionally;
  `linkage` fell back to selecting every row in `responses` with no docket
  filter, which linked one docket's comments against another's adjudications;
  and the metrics counted the whole table. All three are now scoped, and the
  linkage fallback is gone — reporting nothing is better than reporting the
  wrong docket.

### Added
- **Structural parsing, preferred over the regex conventions.** Following #5:
  the Federal Register publishes full text as XML in which each paragraph is its
  own element and a Comment or Response label opens a paragraph. Matching on
  element boundaries removes the whole class of failure that regex over
  flattened text creates — prose cannot open a pair because it is not the start
  of a paragraph, and a match cannot run past its paragraph into rule text. The
  regex conventions remain as a fallback, and the parse reports which was used.

### Note on what this means for earlier results
The CMMC run reported in the README was unaffected by #1 and #2 by luck:
`DOD-2023-OS-0063` has no correction document, and its preamble scores 100%
recall on the `plain` convention. Every other docket was exposed. The "validated
against one agency" caveat in the README was carrying more weight than its
phrasing conveyed.

## [0.7.3] — 2026-08-16

### Changed
- **CI checks are now scripts in `ci/`, not Python embedded in workflow YAML.**
  Heredocs (`python - <<'PY'`) are a shell feature; PowerShell reads `<<` as a
  redirection operator, so those steps died on Windows runners before Python
  started. Real files run identically on every platform and can be run by hand
  when something breaks: `python ci/check_fixture.py`, `python ci/check_routes.py`.
- The stress suite no longer assumes `/tmp` exists or that the working directory
  is the repository root — it uses `tempfile.gettempdir()` and passes
  `PYTHONPATH` to every subprocess it spawns.
- CI runs the fixture twice on every platform: once normally and once under
  `PYTHONIOENCODING=cp1252`.

## [0.7.2] — 2026-08-16

### Fixed
- **The CLI crashed on Windows terminals.** The Windows console defaults to
  cp1252, which cannot encode an arrow — so `collapsed 257 → 44 analysis units`
  raised `UnicodeEncodeError` and killed the run. It never surfaced in the web
  console, because that output goes to a browser rather than a terminal, so the
  entire command line was broken on Windows without either of us seeing it.
  Console streams are now reconfigured to UTF-8 with `errors="replace"` on
  import, so an unmappable character degrades to a placeholder rather than
  aborting an hour-long ingest, and decorative characters have been removed
  from console strings regardless.
- CI now forces `PYTHONIOENCODING=cp1252` on the Windows matrix, and the stress
  suite runs the CLI under it, so this fails in testing rather than on someone's
  machine.

## [0.7.1] — 2026-08-16

### Fixed
- **Requesting a report before running the pipeline returned a 500.** Asking for
  output that doesn't exist yet is an ordinary thing to do, not a server fault.
  It now returns a page naming the stage to run first. Found by CI on its first
  run, which is what CI is for.
- The routes step in CI asserted only the happy path. It now covers the
  pre-pipeline case, a missing docket parameter, and an unknown docket ID.

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
