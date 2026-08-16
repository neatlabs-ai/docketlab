# Contributing to DOCKETLAB

Thanks for looking. This is a small, opinionated tool with a specific job, so
the most useful contributions are usually narrow ones.

## The highest-value contribution

**Preamble conventions.** The parser currently recognizes three ways agencies
structure their responses to comments. There are more. If you hit a final rule
that parses to zero pairs or low coverage, that's a bug worth reporting even if
you don't want to write the fix — attach the docket ID and the Federal Register
document number and we can work from there.

The parser reporting *which* convention matched and *what fraction* of the
preamble it covered is deliberate. A linkage layer built on a bad parse is worse
than no linkage, because it looks authoritative.

## Setup

```bash
git clone https://github.com/neatlabs-ai/docketlab
cd docketlab
pip install -r requirements.txt
python -m docketlab fixture      # ten seconds, no keys, no network
```

The fixture is the contract. It seeds problems at known positions and grades the
pipeline against them. **A change that drops any of the eight scores is a
regression**, including the one that is supposed to read 0% — MinHash genuinely
cannot see a paraphrase campaign, and a change that makes it appear to would
mean the check has stopped measuring anything.

```bash
python stress.py                 # ~30 adversarial and scaling checks
```

Both must pass before a pull request.

## Changing the schema

Add the column to `SCHEMA` in `store.py` and stop. `store.migrate()` diffs
declared columns against actual ones on every start and adds what's missing, so
existing databases upgrade in place.

What it deliberately does **not** do: drop columns, change types, or backfill.
Those lose data or silently reinterpret it. If a change needs any of that, it
needs a real migration with a version marker — raise it in an issue first.

The suite builds an older database and asserts both the upgrade and the survival
of its rows. Keep that passing.

## What we look for

- **New behaviour comes with a fixture case.** If you add a detection path, seed
  something in `fixtures.py` that exercises it and add the check to `score()`.
  Untested detection is indistinguishable from confident guessing.
- **Honest degradation.** When something can't be determined, say so. Silence
  that reads as a finding is the failure mode this tool exists to avoid.
- **Watch the scaling.** Dedup runs on every comment. The containment pass was
  quadratic once and projected to ~100 minutes at 40,000 comments before it was
  rebuilt on LSH. `stress.py` measures the curve; keep it linear.
- **No telemetry, ever.** Zero custody is a design constraint, not a preference.
  Nothing phones home.

## Style

Standard Python, 4-space indent, type hints where they help. Comments should
explain *why* — the code already says what. Where a constant encodes a real
finding (a threshold, a cap), say what the finding was.

## Reporting problems

Open an issue with the docket ID, the stage that failed, and the run log line.
For anything involving keys or a corpus you can't share, redact freely — the
docket ID and the stage are usually enough.

## Security

See [SECURITY.md](SECURITY.md). Don't open a public issue for a vulnerability.
