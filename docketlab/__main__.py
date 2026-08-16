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

"""Headless CLI. The UI is the console; this is for scripted runs.

    python -m docketlab fixture
    python -m docketlab pipeline DOD-2023-OS-0063
    python -m docketlab serve
    python -m docketlab report DOD-2023-OS-0063
    python -m docketlab inspect diff          # section-by-section rule changes
    python -m docketlab inspect tables        # row counts
    python -m docketlab sql "SELECT ..."      # ad-hoc, read-only

`inspect` and `sql` open the database read-only, so they work while the console
is running. Everything else needs the write lock.
"""
import sys

from . import (analyze, dedup, fedreg, fixtures, ingest, linkage, report,
               semantic, store, textdiff)


def _inspect(rest):
    """Read-only views of a live instance. No write lock, no shutdown needed."""
    import pandas as pd

    what = rest[0] if rest else "tables"
    opts = dict(zip(("display.max_columns", "display.width", "display.max_colwidth"),
                    (None, 200, 70)))
    try:
        if what == "tables":
            names = ["dockets", "documents", "comments", "dedup", "clusters",
                     "analysis", "responses", "linkage", "textdiff", "api_calls"]
            for n in names:
                try:
                    c = store.read_query(f"SELECT count(*) c FROM {n}").c[0]
                    print(f"  {n:<12} {int(c):>8,}")
                except Exception as e:
                    print(f"  {n:<12} {type(e).__name__}")
            return 0

        if what == "diff":
            df = store.read_query(
                "SELECT section, change_kind, similarity, magnitude, "
                "words_proposed, words_final FROM textdiff ORDER BY sort_key"
            )
            if df.empty:
                print("No text diff recorded. Run the 'Diff rule text' stage first.")
                return 1
            with pd.option_context(*[x for kv in opts.items() for x in kv]):
                print(df.to_string(index=False))
            moved = df[df.change_kind.isin(("modified", "rewritten", "added", "removed"))]
            rate = len(moved) / len(df)
            print(f"\n  {len(moved)}/{len(df)} sections changed ({rate:.0%})")
            if rate >= 0.80:
                print("  Wholesale rewrite: 'cited section changed' does not discriminate "
                      "between comments here. Magnitude is what separates them.")
            return 0

        if what == "quota":
            from . import usage
            for svc in ("regulations.gov", "anthropic"):
                q = usage.quota(svc)
                print(f"  {svc:<18} {q['remaining']:>6,} of {q['limit']:,} left "
                      f"({q['used']} used, from {q['source']})")
            return 0

        print("usage: python -m docketlab inspect [tables|diff|quota]")
        return 1
    except FileNotFoundError as e:
        print(f"  {e}")
        return 1


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        print(__doc__)
        return 1
    cmd, rest = argv[0], argv[1:]
    try:
        store.init()
    except store.AlreadyRunning as e:
        print(f"\n{e}")
        return 1
    say = print

    # Read-only commands run before store.init(), which would take the lock.
    if cmd == "inspect":
        return _inspect(rest)
    if cmd == "sql":
        if not rest:
            print('usage: python -m docketlab sql "SELECT ..."')
            return 1
        import pandas as pd
        with pd.option_context("display.max_columns", None, "display.width", 200,
                               "display.max_colwidth", 60):
            print(store.read_query(" ".join(rest)).to_string())
        return 0

    if cmd == "serve":
        from .server import main as serve
        return serve()
    if cmd == "fixture":
        print(fixtures.build(progress=say))
        print(dedup.run(fixtures.DOCKET, progress=say))
        print(semantic.cluster(fixtures.DOCKET, progress=say))
        print(linkage.run(fixtures.DOCKET, adjudicate=False, progress=say))
        print(fixtures.score(progress=say))
        return 0
    if cmd == "pipeline":
        if not rest:
            print("usage: python -m docketlab pipeline <DOCKET-ID>")
            return 1
        d = rest[0]
        print(ingest.pull_docket(d, progress=say))
        print(dedup.run(d, progress=say))
        print(semantic.cluster(d, progress=say))
        print(fedreg.load(d, progress=say))
        print(textdiff.run(d, progress=say))
        try:
            print(analyze.run(d, progress=say))
        except RuntimeError as e:
            print(f"skipping analysis: {e}")
        print(linkage.run(d, progress=say))
        out = store.config.ROOT / f"report_{d}.html"
        out.write_text(report.build(d, progress=say), encoding="utf-8")
        print(f"report: {out}")
        return 0
    if cmd == "report":
        if not rest:
            print("usage: python -m docketlab report <DOCKET-ID>")
            return 1
        out = store.config.ROOT / f"report_{rest[0]}.html"
        out.write_text(report.build(rest[0], progress=say), encoding="utf-8")
        print(f"report: {out}")
        return 0
    print(f"unknown command: {cmd}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
