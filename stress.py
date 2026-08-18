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

"""Adversarial checks. Not unit tests — a hunt for the ways this breaks.

Run: python3 stress.py
"""
import os
import sys
import time

import tempfile

_ROOT = os.path.dirname(os.path.abspath(__file__))
# tempfile.gettempdir() rather than a hardcoded /tmp — Windows has no /tmp, and
# these subprocess probes have to run on the same platforms as the product.
os.environ.setdefault("DL_HOME", os.path.join(tempfile.gettempdir(), "dl_stress"))
sys.path.insert(0, _ROOT)

from docketlab import (dedup, extract, fedreg, metrics, provisions, report,  # noqa
                       semantic, store)
from docketlab import textdiff as _td  # noqa

FAIL = []
def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  — ' + detail if detail else ''}")
    if not cond:
        FAIL.append(name)

print("\n=== text normalization edge cases ===")
check("empty", extract.normalize("") == "")
check("none-safe", extract.normalize(None) == "")
check("nested html", "script" not in extract.normalize("<script>alert(1)</script>hi").lower())
check("unclosed tag", extract.normalize("a <div class='x' b") .startswith("a"))
check("entity soup", extract.normalize("&amp;amp; &lt;b&gt;") == "&amp; <b>")
check("huge tag no catastrophe", len(extract.normalize("<" + "a"*5000 + ">x")) < 6000)
t0=time.time(); extract.normalize("<br/>x"*20000); dt=time.time()-t0
check("normalize 20k tags fast", dt < 2.0, f"{dt:.2f}s")

print("\n=== provision guard ===")
check("url rejected", provisions.clean(["https://x.gov/d/p-1"]) == [])
check("page anchor rejected", provisions.clean(["p-146"]) == [])
check("bare number rejected", provisions.clean(["1435"]) == [])
check("prose rejected", provisions.clean(["the scoping section generally"]) == [])
check("real cite kept", provisions.clean(["170.14(c)(4)"]) == ["170.14(c)(4)"])
check("dfars kept", provisions.clean(["252.204-7012"]) == ["252.204-7012"])
check("dedup within list", provisions.clean(["170.20","§170.20"]) == ["170.20"])
check("non-list input", provisions.clean("170.20") == ["170.20"])
check("garbage types", provisions.clean([None, 5, {}, "170.20"]) == ["170.20"])
check("caps at 8", len(provisions.clean([f"170.{i}" for i in range(20)])) == 8)

print("\n=== preamble parser edge cases ===")
check("empty doc", fedreg.parse_responses("T-EMPTY", "")["pairs"] == 0)
check("no convention", fedreg.parse_responses("T-NONE", "Some rule text with no pairs at all. "*50)["pairs"] == 0)
runaway = "Comment: " + "x"*100 + " Response: " + "y"*60000
check("runaway match rejected", fedreg.parse_responses("T-RUN", runaway)["pairs"] == 0)
tiny = "Comment: short. Response: also short."
check("too-short pairs skipped", fedreg.parse_responses("T-TINY", tiny)["pairs"] == 0)
good = ("Comment: " + "word "*30 + ".\nResponse: " + "reply "*30 + ".\n\n") * 6
d = fedreg.parse_responses("T-GOOD", good)
check("well-formed parsed", d["pairs"] == 6, str(d["pairs"]))
check("confidence flag", d["confident"] is True)

print("\n=== dedup edge cases ===")
store.init()
def seed(docket, texts):
    with store.db() as con:
        con.execute("DELETE FROM comments WHERE docket_id=?", [docket])
        con.execute("DELETE FROM dedup WHERE comment_id LIKE ?", [docket+"%"])
    store.upsert("comments", [
        {"comment_id": f"{docket}-{i:05d}", "docket_id": docket, "document_id": "D",
         "posted_date": None, "received_date": None, "submitter": None, "organization": None,
         "submitter_type": None, "title": None, "body": t, "attach_text": None,
         "full_text": t, "n_attachments": 0, "text_source": "inline",
         "word_count": len(t.split())} for i, t in enumerate(texts)])

seed("EDGE-1", [])
check("empty docket handled", "error" in dedup.run("EDGE-1"))
seed("EDGE-2", ["only one comment here with some words in it"])
r = dedup.run("EDGE-2")
check("single comment", r.get("campaigns") == 0 and r.get("comments") == 1, str(r))
seed("EDGE-3", ["a", "a", "b"])
r = dedup.run("EDGE-3")
check("ultra-short texts survive", r.get("comments") == 3, str(r))
seed("EDGE-4", ["identical text here"] * 200)
r = dedup.run("EDGE-4")
check("200 identical -> 1 unit", r["units_to_analyze"] == 1, str(r["units_to_analyze"]))
check("reduction ~99.5%", r["reduction"] > 0.99, f"{r['reduction']}")

print("\n=== dedup scaling (the containment pass is O(n^2)) ===")
import random
rng = random.Random(1)
vocab = [f"w{i}" for i in range(400)]
texts = [" ".join(rng.choice(vocab) for _ in range(120)) for _ in range(1500)]
seed("SCALE-1", texts)
t0 = time.time(); dedup.run("SCALE-1"); dt = time.time() - t0
check("1,500 distinct comments dedup < 30s", dt < 30, f"{dt:.1f}s")
print(f"      → extrapolated to 40,000 comments: {dt*(40000/1500)**2/60:.0f} min if quadratic")

print("\n=== report scaling ===")
seed("REPORT-1", [f"comment number {i} " + "filler words here " * 40 for i in range(600)])
dedup.run("REPORT-1")
try:
    t0 = time.time(); h = report.build("REPORT-1"); dt = time.time() - t0
    check("600-unit report builds", len(h) > 0, f"{len(h)/1e6:.1f}MB in {dt:.1f}s")
    check("report under 5MB", len(h) < 5_000_000, f"{len(h)/1e6:.2f}MB")
except Exception as e:
    check("600-unit report builds", False, f"{type(e).__name__}: {e}")

print("\n=== metrics with no analysis ===")
try:
    m = metrics.compute("REPORT-1")
    check("metrics on unanalyzed corpus", m.get("units", 0) > 0, str(m.get("analyzed")))
except Exception as e:
    check("metrics on unanalyzed corpus", False, f"{type(e).__name__}: {e}")
check("metrics on unknown docket", metrics.compute("NOPE-9999").get("units") == 0)

print("\n=== embedding cache incrementality ===")
texts_a = [f"document about topic {i}" for i in range(300)]
t0 = time.time(); semantic.embed(texts_a, cache_key="inc"); t_first = time.time() - t0
t0 = time.time(); semantic.embed(texts_a, cache_key="inc"); t_cached = time.time() - t0
check("cache hit is fast", t_cached < max(t_first * 0.5, 0.3), f"{t_first:.2f}s -> {t_cached:.2f}s")
t0 = time.time(); semantic.embed(texts_a + ["one more document"], cache_key="inc"); t_grow = time.time() - t0
check("adding 1 doc reuses cache", t_grow < max(t_first * 0.5, 0.3),
      f"{t_grow:.2f}s vs first {t_first:.2f}s")

print("\n=== concurrent access (UI reads while a stage writes) ===")
import threading
err = []
def writer():
    try:
        for i in range(30):
            store.log("stress", f"write {i}")
    except Exception as e:
        err.append(f"writer: {type(e).__name__}: {e}")
def reader():
    try:
        for _ in range(30):
            store.query("SELECT count(*) FROM comments")
    except Exception as e:
        err.append(f"reader: {type(e).__name__}: {e}")
ts = [threading.Thread(target=writer), threading.Thread(target=reader)]
[t.start() for t in ts]; [t.join() for t in ts]
check("no lock contention", not err, "; ".join(err[:2]))

print("\n=== docket id normalization ===")
from docketlab.discover import normalize_id
check("FR 'Docket ' prefix stripped", normalize_id("Docket DARS-2020-0034") == "DARS-2020-0034")
check("label + colon", normalize_id("Docket ID: EPA-HQ-OAR-2023-0072") == "EPA-HQ-OAR-2023-0072")
check("lowercase upcased", normalize_id("  dod-2023-os-0063 ") == "DOD-2023-OS-0063")
check("quotes stripped", normalize_id('"DOD-2023-OS-0063"') == "DOD-2023-OS-0063")
check("prose returns None", normalize_id("just some words") is None)
check("empty returns None", normalize_id("") is None)
check("section number is not a docket", normalize_id("170.14") is None)
check("clean id untouched", normalize_id("DEA-2024-0059") == "DEA-2024-0059")

print("\n=== rule text section detection (all GPO shapes) ===")
from docketlab import textdiff as _td
SAME = "List of Subjects in 32 CFR Part 170\nPART 170—X\n§ 170.4  Acronyms.\nBody one here.\n§ 170.17  Level 2.\nBody two here."
NEXT = "List of Subjects in 32 CFR Part 170\nPART 170—X\n§ 170.4\nAcronyms.\nBody one here.\n§ 170.17\nLevel 2.\nBody two changed."
SEC  = "For the reasons stated in the preamble\nSec. 170.4  Acronyms.\nBody one here."
XREF = "List of Subjects in 32 CFR Part 170\nThe rules in §§ 170.4 and 170.5 apply.\nPART 170—X\n§ 170.4  Real.\nBody."
check("heading and title on one line", sorted(_td.sections(SAME)) == ["170.17", "170.4"])
check("title on the next line", sorted(_td.sections(NEXT)) == ["170.17", "170.4"])
check("Sec. style", sorted(_td.sections(SEC)) == ["170.4"])
check("cross-references not treated as headings", sorted(_td.sections(XREF)) == ["170.4"])
_a, _b = _td.sections(SAME), _td.sections(NEXT)
check("identical body across formats reads unchanged",
      _td._summarize(_a["170.4"]["body"], _b["170.4"]["body"])[0] == "unchanged")
check("real edit reads modified",
      _td._summarize(_a["170.17"]["body"], _b["170.17"]["body"])[0] in ("modified", "rewritten"))
_d = _td.diagnose("preamble prose only, no sections. " * 40)
check("diagnostics on a headingless document", _d["section_tokens"] == 0 and "samples" in _d)

print("\n=== text diff: magnitude, sorting, base rate ===")
check("numeric section sort", [_td._sort_key(x) for x in ("170.2","170.10")] ==
      sorted([_td._sort_key(x) for x in ("170.2","170.10")]))
check("170.2 sorts before 170.10", _td._sort_key("170.2") < _td._sort_key("170.10"))

store.init()
def seed_diff(mags):
    rows=[{"section":f"170.{i+1}","sort_key":_td._sort_key(f"170.{i+1}"),
           "change_kind":"modified" if m > 0 else "unchanged",
           "similarity":round(1-m,4),"magnitude":round(m,4),
           "words_proposed":300,"words_final":300,
           "proposed_text":"a","final_text":"b"} for i,m in enumerate(mags)]
    with store.db() as con: con.execute("DELETE FROM textdiff")
    store.upsert("textdiff", rows)

seed_diff([0.0]*18 + [0.5]*6)                       # 25% changed — informative
sm = _td.summary()
check("low change rate is discriminating", sm["discriminating"] is True, f"{sm['change_rate']}")
seed_diff([0.05,0.1,0.2,0.4,0.6,0.8] * 4)           # 100% changed — not
sm = _td.summary()
check("wholesale rewrite flagged non-discriminating", sm["discriminating"] is False,
      f"{sm['change_rate']}")
check("median magnitude recorded", sm["median_magnitude"] > 0, str(sm["median_magnitude"]))

print("\n=== read-only access while the write lock is held ===")
store.init()                                         # take the write lock
try:
    n = store.read_query("SELECT count(*) c FROM textdiff").c[0]
    check("read_query works alongside the writer", int(n) == 24, str(n))
except Exception as e:
    check("read_query works alongside the writer", False, f"{type(e).__name__}: {e}")

print("\n=== schema migration from an older database ===")
import duckdb as _dd, tempfile as _tf, shutil as _sh, subprocess as _sp
_old = _tf.mkdtemp(prefix="dl_mig_")
os.makedirs(os.path.join(_old, "derived"), exist_ok=True)
_dbp = os.path.join(_old, "derived", "docketlab.duckdb")
_c = _dd.connect(_dbp)
# a v0.6.1-era textdiff: no sort_key, similarity, magnitude, or word counts
_c.execute("CREATE TABLE textdiff (section VARCHAR, change_kind VARCHAR, "
           "proposed_text VARCHAR, final_text VARCHAR)")
_c.execute("INSERT INTO textdiff VALUES ('170.4','modified','old body','new body')")
_c.close()
_probe = f"""
import os; os.environ["DL_HOME"] = {_old!r}
from docketlab import store
store.init()
cols = set(store.read_query("SELECT * FROM textdiff").columns)
need = {{"sort_key","similarity","magnitude","words_proposed","words_final"}}
rows = store.read_query("SELECT section, proposed_text FROM textdiff").to_dict("records")
print("MIGRATED" if need <= cols else "MISSING", rows)
"""
_out = _sp.run([sys.executable, "-c", _probe], capture_output=True, text=True,
               errors="replace", cwd=_ROOT, env={**os.environ, "PYTHONPATH": _ROOT})
check("old database gains new columns", "MIGRATED" in _out.stdout,
      (_out.stdout + _out.stderr).strip().splitlines()[-1] if (_out.stdout or _out.stderr) else "")
check("existing rows survive migration", "170.4" in _out.stdout and "old body" in _out.stdout)
_sh.rmtree(_old, ignore_errors=True)

print("\n=== asking for output before the pipeline has run ===")
import subprocess as _sp2, tempfile as _tf2, shutil as _sh2
_nr = _tf2.mkdtemp(prefix="dl_nr_")
_p2 = f"""
import os; os.environ["DL_HOME"] = {_nr!r}
from docketlab.server import app
from docketlab import dedup, fixtures, semantic, store
store.init(); fixtures.build()
c = app.test_client()
pre = c.get("/export?docket=" + fixtures.DOCKET).status_code
none = c.get("/export").status_code
dedup.run(fixtures.DOCKET); semantic.cluster(fixtures.DOCKET)
post = c.get("/export?docket=" + fixtures.DOCKET).status_code
unk = c.get("/ledger?docket=NOPE-9999-0001").status_code
print("RESULT", pre, none, post, unk)
"""
_o2 = _sp2.run([sys.executable, "-c", _p2], capture_output=True, text=True,
               cwd=_ROOT, env={**os.environ, "PYTHONPATH": _ROOT})
_line = [l for l in _o2.stdout.splitlines() if l.startswith("RESULT")]
_got = _line[0] if _line else (_o2.stderr.strip().splitlines() or [""])[-1]
check("export before pipeline explains rather than 500s", "RESULT 409" in _got, _got)
check("export with no docket is a 400", " 400 " in _got, _got)
check("export after pipeline succeeds", _got.endswith("200 200"), _got)
_sh2.rmtree(_nr, ignore_errors=True)

print("\n=== legacy console encoding (the Windows cp1252 default) ===")
_enc = _tf2.mkdtemp(prefix="dl_enc_")
_eo = _sp2.run([sys.executable, "-m", "docketlab", "fixture"],
               capture_output=True, text=True, errors="replace",
               cwd=_ROOT,
               env={**os.environ, "DL_HOME": _enc, "PYTHONIOENCODING": "cp1252",
                    "PYTHONPATH": _ROOT})
check("CLI survives a cp1252 console", _eo.returncode == 0,
      (_eo.stderr.strip().splitlines() or ["?"])[-1][:120])
check("no UnicodeEncodeError", "UnicodeEncodeError" not in (_eo.stdout + _eo.stderr))
_sh2.rmtree(_enc, ignore_errors=True)

print("\n=== reported by abigailhaddad, issues #1-#4 ===")
from docketlab import fedreg as _fr, textdiff as _td2

# #1 - a correction is typed "Rule" and was selected over the real final rule.
_DOCS = [
 {"document_number":"2021-24202","type":"Proposed Rule","publication_date":"2021-11-15",
  "action":"Proposed rule.","start_page":1,"end_page":154},
 {"document_number":"2021-27312","type":"Proposed Rule","publication_date":"2021-12-17",
  "action":"Proposed rulemaking; extension of public comment period.","start_page":1,"end_page":2},
 {"document_number":"2022-24675","type":"Proposed Rule","publication_date":"2022-12-06",
  "action":"Supplemental notice of proposed rulemaking.","start_page":1,"end_page":146},
 {"document_number":"2024-00366","type":"Rule","publication_date":"2024-03-08",
  "action":"Final rule.","start_page":1,"end_page":408},
 {"document_number":"2024-13206","type":"Rule","publication_date":"2024-08-01",
  "action":"Interim final rule; correction; request for comments.","start_page":1,"end_page":78},
]
_f, _fw = _fr._pick(_DOCS, "Rule")
_n, _nw = _fr._pick(_DOCS, "Proposed Rule")
check("the final rule is chosen over a later correction",
      _f["document_number"] == "2024-00366", f"chose {_f['document_number']}")
check("the supplemental proposal supersedes the original",
      _n["document_number"] == "2022-24675", f"chose {_n['document_number']}")
check("a comment-period extension is not treated as a proposal",
      _n["document_number"] != "2021-27312")
check("the selection explains itself", any("chose" in x for x in _fw), str(_fw[:2]))

# The checks above hand _pick documents that carry an "action". find_documents
# does not request that field, so in the live pipeline every action test above
# is vacuous and selection falls through to the ordering rules. Both are checked
# here: that the field is actually requested, and that the ordering is right
# even when it is absent.
_asked = {}
def _capture(path, params=None):
    _asked.update(params or {})
    return {"results": []}
_real_get, _fr._get = _fr._get, _capture
try:
    _fr.find_documents("X-0001")
finally:
    _fr._get = _real_get
_fields = set(_asked.get("fields[]") or [])
check("find_documents requests the action field", "action" in _fields, str(sorted(_fields)))
check("find_documents requests the XML url, without which structural parsing "
      "never runs", "full_text_xml_url" in _fields)

# A docket carries ancillary documents typed "Proposed Rule" that no action
# keyword predicts - a notice of posting a video, of data availability, of a
# hearing. Ranking proposals by date first gave the NPRM slot to whichever came
# last. This is the real CMMC docket with the action text stripped, as
# find_documents currently returns it.
_NOACTION = [
 {"document_number":"2023-27280","type":"Proposed Rule","publication_date":"2023-12-26",
  "start_page":1,"end_page":81},
 {"document_number":"2024-03460","type":"Proposed Rule","publication_date":"2024-02-21",
  "start_page":1,"end_page":1},
 {"document_number":"2024-22905","type":"Rule","publication_date":"2024-10-15",
  "start_page":1,"end_page":146},
]
_n2, _ = _fr._pick(_NOACTION, "Proposed Rule")
check("a later one-page notice does not displace the NPRM",
      _n2["document_number"] == "2023-27280", f"chose {_n2['document_number']}")

# #2 - prose ending "...we received comments." opened a pair.
_PROSE = ("The agency reviewed the record. In response to the notice we received comments. "
          "Commenters raised concerns about methodology and the underlying data at length.\n\n"
          "Comment: " + "a real comment sentence " * 4 + "\n"
          "Response: " + "a real response sentence " * 4 + "\n")
_d2 = _fr.parse_responses("T-PROSE", _PROSE)
_rows = store.read_query(
    "SELECT comment_para FROM responses WHERE document_id='T-PROSE'").to_dict("records")
check("ordinary prose no longer opens a pair",
      _rows and "we received comments" not in _rows[0]["comment_para"],
      (_rows[0]["comment_para"][:60] if _rows else "no pairs"))
check("the real pair is still found", len(_rows) == 1, f"{len(_rows)} pairs")

# #3 - the comment side had no bound and was truncated into the store.
_LONG = ("Comment: " + "x" * 60000 + "\nResponse: " + "y" * 200 + "\n"
         "Comment: " + "a short real comment sentence " * 3 + "\n"
         "Response: " + "a short real response sentence " * 3 + "\n")
_fr.parse_responses("T-LONG", _LONG)
_lrows = store.read_query(
    "SELECT comment_para FROM responses WHERE document_id='T-LONG'").to_dict("records")
check("an overlong comment side is rejected, not truncated",
      all(len(r["comment_para"]) < 20000 for r in _lrows) and
      not any(r["comment_para"].startswith("xxx") for r in _lrows),
      f"{len(_lrows)} pairs kept")
check("nothing stored is a fragment of a dropped match",
      all(len(r["comment_para"]) <= _fr.MAX_SIDE for r in _lrows))

# #4 - textdiff and responses were global.
with store.db() as _c9:
    _c9.execute("DELETE FROM textdiff")
store.upsert("textdiff", [
    {"docket_id": "DOCKET-A", "section": "170.1", "sort_key": 170.001,
     "change_kind": "modified", "similarity": 0.5, "magnitude": 0.5,
     "words_proposed": 10, "words_final": 12, "proposed_text": "a", "final_text": "b"},
    {"docket_id": "DOCKET-B", "section": "72.210", "sort_key": 72.21,
     "change_kind": "modified", "similarity": 0.5, "magnitude": 0.5,
     "words_proposed": 10, "words_final": 12, "proposed_text": "a", "final_text": "b"},
])
_a_rows = store.read_query(
    "SELECT section FROM textdiff WHERE docket_id='DOCKET-A'").section.tolist()
check("a second docket's diff does not displace the first",
      _a_rows == ["170.1"], str(_a_rows))
_sa = _td2.summary("DOCKET-A")
check("the diff summary is scoped to one docket", _sa["sections"] == 1, str(_sa["sections"]))

print("\n=== structural parsing prefers element boundaries ===")
_SXML = ("<?xml version='1.0'?><RULE>"
         "<P>In response to the notice we received comments.</P>"
         "<P>Comment: " + "a genuine comment sentence " * 4 + "</P>"
         "<P>continuation of that comment, longer than forty characters here.</P>"
         "<P>Response: " + "a genuine response sentence " * 4 + "</P>"
         "</RULE>")
_sp, _sd = _fr.parse_structural("T-STRUCT", _SXML)
check("structural parsing finds the pair", len(_sp) == 1, str(len(_sp)))
check("a prose paragraph cannot open a pair",
      not any("we received comments" in c for _, c, _ in _sp))
check("continuation paragraphs join the comment",
      any("continuation" in c for _, c, _ in _sp))
_d5 = _fr.parse_responses("T-STRUCT2", _PROSE, _SXML)
check("structural is preferred when usable or falls back cleanly",
      _d5["convention"] in ("structural", "plain"), str(_d5["convention"]))

print("\n=== cold start: every page on a fresh install with no data ===")
import shutil, tempfile, subprocess
cold = tempfile.mkdtemp(prefix="dl_cold_")
probe = f"""
import os; os.environ["DL_HOME"] = {cold!r}
from docketlab.server import app
c = app.test_client()
paths = ["/","/guide","/usage","/dockets","/settings","/watch","/ledger","/metrics"]
bad = [(p, c.get(p).status_code) for p in paths if c.get(p).status_code != 200]
print("BAD" if bad else "OK", bad)
"""
out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                     cwd=_ROOT, env={**os.environ, "PYTHONPATH": _ROOT})
check("all pages render with zero data", "OK []" in out.stdout,
      (out.stdout + out.stderr).strip().splitlines()[-1] if (out.stdout or out.stderr) else "")
shutil.rmtree(cold, ignore_errors=True)

print("\n" + ("ALL CLEAR" if not FAIL else f"{len(FAIL)} FAILURES: " + ", ".join(FAIL)))
