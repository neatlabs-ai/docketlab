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

"""Standalone HTML report.

One file, no assets, no network. It has to survive being emailed to someone who
will open it on a machine that has never heard of this tool, so every style is
inline and every font is a system stack.

It carries its own methodology and limits sections, because a report that
states a 66% response rate without saying how a "response" was matched, what
fraction of the preamble parsed, and how much of the docket was actually pulled
is a number someone will quote back at you in a meeting where you are not
present to caveat it.
"""
from __future__ import annotations

import html
import json
from datetime import datetime

from . import brand, metrics, store, textdiff


def _num(v, default=0) -> int:
    """pandas NA raises on truthiness, so numbers are coerced explicitly."""
    try:
        if v is None or str(v) in ("nan", "<NA>", "NaT", ""):
            return default
        return int(v)
    except Exception:
        return default


def _esc(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def _loads(v):
    try:
        return json.loads(v) if v else []
    except Exception:
        return []


def _bar(pct: float, cls: str = "") -> str:
    return (
        f'<div class="track"><div class="fill {cls}" '
        f'style="width:{max(0.0, min(100.0, pct)):.1f}%"></div></div>'
    )


CSS = """
:root{--onionskin:#EBEEF1;--paper:#F7F8F9;--ink:#14181C;--steel:#8E9AA6;--rule:#C8D0D8;
--stamp:#B0242E;--verdigris:#376A57;--ochre:#9C7020;
--display:"Bahnschrift","DIN Alternate","Roboto Condensed","Arial Narrow",sans-serif;
--body:Constantia,"Iowan Old Style",Cambria,Georgia,serif;
--data:"Cascadia Mono",Consolas,"SF Mono",ui-monospace,monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--onionskin);color:var(--ink);font-family:var(--body);
font-size:15px;line-height:1.55}
.wrap{max-width:1080px;margin:0 auto;padding:0 22px 80px}
header{border-bottom:2px solid var(--ink);padding:26px 0 14px;margin-bottom:8px}
.mark{font-family:var(--display);font-size:27px;font-weight:700;letter-spacing:.16em;
text-transform:uppercase}
.mark span{color:var(--stamp)}
.sub{font-family:var(--data);font-size:11px;color:var(--steel);letter-spacing:.05em;margin-top:5px}
h1{font-family:var(--display);font-size:31px;margin:26px 0 4px;letter-spacing:.01em;font-weight:700}
h2{font-family:var(--display);font-size:13px;letter-spacing:.18em;text-transform:uppercase;
color:var(--steel);margin:34px 0 10px;border-bottom:1px solid var(--rule);padding-bottom:5px;
font-weight:600}
p{margin:9px 0}
.card{background:var(--paper);border:1px solid var(--rule);padding:17px 19px}
.mono{font-family:var(--data);font-size:12px}
.muted{color:var(--steel)}
.grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}
.stat{background:var(--paper);border:1px solid var(--rule);padding:12px 14px}
.stat .n{font-family:var(--display);font-size:27px;font-weight:700;line-height:1}
.stat .k{font-family:var(--data);font-size:10px;letter-spacing:.09em;text-transform:uppercase;
color:var(--steel);margin-top:5px}
table{width:100%;border-collapse:collapse;background:var(--paper);border:1px solid var(--rule)}
th{font-family:var(--display);font-size:10px;letter-spacing:.13em;text-transform:uppercase;
color:var(--steel);text-align:left;font-weight:600;padding:9px 10px;border-bottom:1px solid var(--ink)}
td{padding:10px;border-bottom:1px solid var(--rule);vertical-align:top;font-size:14px}
.row{display:flex;align-items:center;gap:11px;margin:7px 0}
.lab{width:150px;flex:none;font-family:var(--data);font-size:11px;text-align:right;color:#4A545E}
.track{flex:1;height:15px;background:#E2E7EC;border:1px solid var(--rule)}
.fill{height:100%;background:var(--ink);opacity:.82}
.fill.ev{background:var(--verdigris);opacity:1}
.val{width:110px;flex:none;font-family:var(--data);font-size:11px}
.quad{display:grid;grid-template-columns:1fr 1fr;gap:11px;margin:14px 0}
.q{border:1px solid var(--rule);border-left-width:5px;padding:13px 15px;background:#EFF2F5}
.q-both{border-left-color:var(--verdigris)}.q-ans{border-left-color:var(--steel)}
.q-silent{border-left-color:var(--ochre)}.q-none{border-left-color:var(--stamp)}
.qn{font-family:var(--display);font-size:32px;font-weight:700;line-height:1}
.ql{font-family:var(--display);font-size:12px;letter-spacing:.1em;text-transform:uppercase;margin:5px 0 4px}
.qd{font-size:13px;color:#4A545E}
.chip{font-family:var(--data);font-size:10px;border:1px solid var(--rule);padding:2px 6px;
margin:0 4px 4px 0;display:inline-block;color:#4A545E;background:#EFF2F5}
.chip.ev{border-color:var(--verdigris);color:var(--verdigris)}
.void{font-family:var(--display);font-size:10px;letter-spacing:.13em;color:var(--stamp);
border:1.5px solid var(--stamp);padding:3px 7px;display:inline-block;transform:rotate(-3deg);
text-transform:uppercase}
.ok{font-family:var(--data);font-size:11px;color:var(--verdigris);border-left:3px solid var(--verdigris);padding-left:7px}
.v-accepted{color:var(--verdigris)}.v-partial{color:var(--ochre)}.v-rejected{color:var(--stamp)}
.sig{font-family:var(--display);font-size:16px;font-weight:700}
.stack{display:flex;height:11px;border:1px solid var(--rule);overflow:hidden;margin-bottom:3px}
.seg{display:block;height:100%}
.s-acc{background:var(--verdigris)}.s-par{background:var(--ochre)}.s-rej{background:var(--stamp)}
.warn{border-left:4px solid var(--stamp);background:var(--paper);padding:11px 15px;
font-family:var(--data);font-size:12px;margin:12px 0}
footer{margin-top:48px;padding-top:16px;border-top:2px solid var(--ink);
font-family:var(--data);font-size:11px;color:var(--steel);line-height:1.7}
footer a{color:inherit}
.fgrid{display:flex;gap:26px;justify-content:space-between;flex-wrap:wrap}
.fr{text-align:right;max-width:430px}
@media(max-width:700px){.fr{text-align:left}}
.org{font-family:var(--display);font-size:10.5px;font-weight:700;letter-spacing:.34em;
text-transform:uppercase;color:var(--steel);margin-bottom:3px}
dl.doc dt{font-family:var(--display);font-size:13px;letter-spacing:.05em;margin-top:11px}
dl.doc dd{margin:2px 0 0;color:#3A434C;font-size:14px}
@media print{body{background:#fff}.card,.stat,table{break-inside:avoid}h2{break-after:avoid}}
@media(max-width:760px){.quad{grid-template-columns:1fr}.lab{width:96px}.val{width:84px}}
"""


def build(docket_id: str, progress=None) -> str:
    say = progress or (lambda m: None)
    say("computing metrics")
    m = metrics.compute(docket_id)
    if not m.get("units"):
        raise RuntimeError("nothing to report — run the pipeline first")

    docket = store.query(
        "SELECT title, agency FROM dockets WHERE docket_id = ?", [docket_id]
    )
    title = docket.title[0] if len(docket) else docket_id
    agency = docket.agency[0] if len(docket) else ""

    fr = store.query(
        "SELECT document_id, count(*) n, min(fr_page) lo, max(fr_page) hi "
        "FROM responses GROUP BY 1"
    )
    changed = textdiff.outcome_map(docket_id)

    ledger = store.query(
        """
        SELECT c.comment_id, c.organization, c.submitter, c.word_count, c.text_source,
               d.campaign_id, a.significance, a.summary, a.stance, a.argument_types,
               a.provisions, a.novel_evidence,
               l.verdict, l.rationale, r.fr_page
        FROM comments c
        JOIN dedup d USING (comment_id)
        LEFT JOIN analysis a USING (comment_id)
        LEFT JOIN linkage l USING (comment_id)
        LEFT JOIN responses r ON r.response_id = l.response_id
        WHERE c.docket_id = ? AND (d.campaign_id IS NULL OR d.is_exemplar)
        ORDER BY a.significance DESC NULLS LAST
        """,
        [docket_id],
    )

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    P: list[str] = []
    A = P.append

    A(f"<!doctype html><html lang='en'><head><meta charset='utf-8'>")
    A("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    A(f"<title>{_esc(docket_id)} — comment adjudication report</title>")
    A(f"<style>{CSS}</style></head><body><div class='wrap'>")
    A(f"<header><div class='org'>{_esc(brand.ORG_TM)}</div>")
    A("<div class='mark'>Docket<span>Lab</span></div>")
    A(f"<div class='sub'>{_esc(brand.TAGLINE)} · generated {now} · "
      f"{_esc(brand.PRODUCT)} v{_esc(brand.VERSION)}</div></header>")
    A(f"<h1>{_esc(title)}</h1>")
    A(f"<p class='mono muted'>{_esc(docket_id)}{' · ' + _esc(agency) if agency else ''}</p>")

    # ── Headline ────────────────────────────────────────────────────────────
    A("<h2>At a glance</h2><div class='grid'>")
    for n, k in [
        (f"{m['submissions']:,}", "submissions"),
        (m["units"], "analysis units"),
        (m["responses"], "agency responses"),
        (f"{round(m['response_rate']*100)}%", "response rate"),
        (m["orphan_responses"], "orphan responses"),
        (m["tokens"]["per_unit"], "tokens per unit"),
    ]:
        A(f"<div class='stat'><div class='n'>{_esc(n)}</div><div class='k'>{k}</div></div>")
    A("</div>")

    # ── Outcome grid ────────────────────────────────────────────────────────
    g = m["outcome_grid"]
    A("<h2>How each submission fared</h2><div class='card'>")
    A("<p class='muted' style='margin-top:0'>A comment can land two ways: the agency writes a "
      "response to it, or the agency changes the text at the provision it cited. Counting only "
      "the first scores a commenter who got exactly what they asked for as though they were "
      "ignored.</p><div class='quad'>")
    for key, cls, lab, desc in [
        ("answered_changed", "q-both", "Answered and text changed",
         "Strongest evidence the argument landed."),
        ("answered_only", "q-ans", "Answered, text unchanged",
         "Engaged on the record; the provision stood."),
        ("changed_only", "q-silent", "Text changed, no response",
         "The silent grant — invisible to a preamble-only reading."),
        ("neither", "q-none", "Neither",
         "No engagement found, or the comment is absent from the corpus."),
    ]:
        A(f"<div class='q {cls}'><div class='qn'>{g[key]}</div>"
          f"<div class='ql'>{lab}</div><div class='qd'>{desc}</div></div>")
    A("</div>")
    td = m.get("textdiff") or {}
    if not m.get("textdiff_available"):
        A("<div class='warn'>Text diff was not run for this report, so the two right-hand "
          "cells are structurally zero rather than measured.</div>")
    elif not td.get("discriminating", True):
        A(f"<div class='warn'><b>Read the silent-grant column with care.</b> "
          f"{td.get('changed')} of {td.get('sections')} sections "
          f"({td.get('change_rate', 0) * 100:.0f}%) changed between proposal and final rule — "
          f"this rule was rewritten wholesale. At that base rate, 'the cited section changed' "
          f"is true of nearly every comment and distinguishes almost nothing on its own. Only "
          f"sections that moved substantially more than the rest of the rule are counted, each "
          f"shown with its magnitude.</div>")
    else:
        A(f"<p class='mono' style='color:#8E9AA6'>{td.get('changed')} of {td.get('sections')} "
          f"sections changed ({td.get('change_rate', 0) * 100:.0f}%), median magnitude "
          f"{td.get('median_magnitude')}.</p>")
    A("</div>")

    # ── Silent grants ───────────────────────────────────────────────────────
    if m["silent_wins"]:
        A("<h2>Silent grants</h2><div class='card'>")
        A("<p class='muted' style='margin-top:0'>No preamble response, but the cited section "
          "changed between proposal and final rule. Evidence of influence, not proof — a "
          "section can change for reasons unrelated to any comment.</p>")
        A("<table><thead><tr><th>Submitter</th><th>Sig</th><th>Argument</th>"
          "<th>Sections that moved</th></tr></thead><tbody>")
        for s in m["silent_wins"]:
            chips = "".join(
                f"<span class='chip ev'>§{_esc(c['section'])} {_esc(c['change'])}"
                + (f" · {c['magnitude'] * 100:.0f}% moved" if "magnitude" in c else "")
                + "</span>"
                for c in s["changed"]
            )
            A(f"<tr><td><b>{_esc(s['who'])}</b><div class='mono muted'>{_esc(s['comment_id'])}</div></td>"
              f"<td><span class='sig'>{s['significance']}</span></td>"
              f"<td>{_esc(s['summary'])}</td><td>{chips}</td></tr>")
        A("</tbody></table></div>")

    # ── Response rate by significance ───────────────────────────────────────
    A("<h2>Response rate by significance</h2><div class='card'>")
    A("<p class='muted' style='margin-top:0'>If the process works as designed the curve rises: "
      "a specific, supported, provision-anchored comment should be far likelier to draw a "
      "response than a general expression of preference.</p>")
    for b in m["by_significance"]:
        pct = (b["rate"] or 0) * 100
        val = "—" if b["rate"] is None else f"{round(pct)}%"
        A(f"<div class='row'><div class='lab'>{b['band']}</div>{_bar(pct)}"
          f"<div class='val'>{val} <span class='muted'>n={b['n']}</span></div></div>")
    A("</div>")

    # ── Grounds ─────────────────────────────────────────────────────────────
    A("<h2>Which grounds move the agency</h2><div class='card'><table>")
    A("<thead><tr><th>Argument type</th><th>Raised</th><th>Answered</th>"
      "<th>Outcome when answered</th><th>Reliability</th></tr></thead><tbody>")
    for a in m["by_argument"]:
        rate = "—" if a["rate"] is None else f"{round(a['rate']*100)}%"
        segs = ""
        if a["answered"]:
            for k, cls in (("accepted", "s-acc"), ("partial", "s-par"), ("rejected", "s-rej")):
                if a[k]:
                    segs += f"<span class='seg {cls}' style='width:{100*a[k]/a['answered']:.1f}%'></span>"
            segs = (f"<div class='stack'>{segs}</div><span class='mono muted'>"
                    f"{a['accepted']}a · {a['partial']}p · {a['rejected']}r</span>")
        else:
            segs = "<span class='mono muted'>—</span>"
        A(f"<tr><td class='mono'>{_esc(a['type'])}</td><td class='mono'>{a['n']}</td>"
          f"<td>{_bar((a['rate'] or 0)*100)}<span class='mono muted'>{rate}</span></td>"
          f"<td>{segs}</td><td class='mono muted'>{_esc(metrics.caution(a['n']) or 'ok')}</td></tr>")
    A("</tbody></table><p class='mono muted'>"
      "<span class='chip' style='background:#376A57;border-color:#376A57'>&nbsp;</span> accepted "
      "<span class='chip' style='background:#9C7020;border-color:#9C7020'>&nbsp;</span> partial "
      "<span class='chip' style='background:#B0242E;border-color:#B0242E'>&nbsp;</span> rejected"
      "</p></div>")

    # ── Evidence + provisions ───────────────────────────────────────────────
    e = m["evidence"]
    A("<h2>Does putting evidence on the record help?</h2><div class='card'>")
    for lab, d, cls in (("with evidence", e["with"], "ev"), ("without", e["without"], "")):
        pct = (d["rate"] or 0) * 100
        val = "—" if d["rate"] is None else f"{round(pct)}%"
        A(f"<div class='row'><div class='lab'>{lab}</div>{_bar(pct, cls)}"
          f"<div class='val'>{val} <span class='muted'>n={d['n']}</span></div></div>")
    A(f"<p class='mono muted' style='margin-bottom:0'>New data, a study, or a cost estimate the "
      f"agency did not already have. {_esc(metrics.caution(e['with']['n']) or 'sample adequate')}.</p></div>")

    if m["provisions"]:
        pmax = m["provisions"][0]["n"]
        A("<h2>Most contested provisions</h2><div class='card'>")
        for p in m["provisions"]:
            A(f"<div class='row'><div class='lab'>§{_esc(p['provision'])}</div>"
              f"{_bar(100*p['n']/pmax)}<div class='val'>{p['n']} "
              f"<span class='muted'>{p['answered']} ans</span></div></div>")
        A("</div>")

    # ── Full ledger ─────────────────────────────────────────────────────────
    LEDGER_CAP = 1500
    shown = ledger.head(LEDGER_CAP)
    A("<h2>Adjudication ledger</h2><div class='card'>")
    if len(ledger) > LEDGER_CAP:
        A(f"<div class='warn'>Showing the {LEDGER_CAP:,} highest-significance units of "
          f"{len(ledger):,}. A file with every row would be too large to open comfortably; "
          f"the aggregate figures above are computed over all of them.</div>")
    A("<table>")
    A("<thead><tr><th>Submitter</th><th>Sig</th><th>Argument</th>"
      "<th>Agency response</th></tr></thead><tbody>")
    for r in shown.itertuples():
        who = r.organization or r.submitter or "Individual commenter"
        chips = "".join(f"<span class='chip'>{_esc(t)}</span>" for t in _loads(r.argument_types))
        chips += "".join(f"<span class='chip'>§{_esc(p)}</span>" for p in _loads(r.provisions))
        if r.novel_evidence is True:
            chips += "<span class='chip ev'>new evidence</span>"
        has_page = r.fr_page is not None and str(r.fr_page) not in ("nan", "<NA>", "")
        if has_page:
            v = f" · <b class='v-{_esc(r.verdict)}'>{_esc(r.verdict)}</b>" if r.verdict else ""
            resp = f"<span class='ok'>{_esc(r.fr_page)} FR{v}</span>"
            if r.rationale:
                resp += f"<div class='mono muted'>{_esc(r.rationale)}</div>"
        elif r.comment_id in changed:
            secs = ", ".join(f"§{c['section']}" for c in changed[r.comment_id]["changed"])
            resp = f"<span class='chip ev'>text changed at {_esc(secs)}</span>"
        else:
            resp = "<span class='void'>no response</span>"
        A(f"<tr><td><b>{_esc(who)}</b><div class='mono muted'>{_esc(r.comment_id)}</div></td>"
          f"<td><span class='sig'>{_num(r.significance)}</span></td>"
          f"<td>{_esc(r.summary if _esc(r.summary) not in ('nan','<NA>') else '') or '—'}<div>{chips}</div></td><td>{resp}</td></tr>")
    A("</tbody></table></div>")

    # ── Methodology and limits ──────────────────────────────────────────────
    A("<h2>How these numbers were produced</h2><div class='card'>")
    A("<p><b>Corpus.</b> Comments pulled from the regulations.gov v4 API, including attachment "
      "text extracted from PDF and Word filings. Duplicate and near-duplicate submissions are "
      "collapsed into campaign families for analysis; counts of submissions always report the "
      "true number, and nothing is deleted.</p>")
    A("<p><b>Agency responses.</b> The final rule was retrieved from the Federal Register and its "
      "preamble parsed into comment/response pairs. ")
    if len(fr):
        row = fr.iloc[0]
        A(f"This report is built on <b>{int(row.n)}</b> parsed pairs from document "
          f"{_esc(row.document_id)}, spanning Federal Register pages {_esc(row.lo)}–{_esc(row.hi)}.")
    A("</p>")
    A("<p><b>Linkage.</b> Each comment is embedded locally and matched against the agency's own "
      "characterization of the comments it was answering. Candidate pairs are then adjudicated "
      "individually by a language model, which is asked first whether the passage addresses that "
      "comment's argument at all; candidates it rejects are discarded rather than counted.</p>")
    A("<p><b>Significance</b> estimates how likely an agency is to be obliged to respond — "
      "specific, supported, provision-anchored comments score high; general expressions of "
      "preference score low. It is not a measure of whether the comment is correct.</p></div>")

    A("<h2>Limits</h2><div class='card'>")
    A("<p><b>Absent is not zero.</b> A submission marked 'no response' either was not engaged, "
      "or its response fell in the part of the preamble the parser did not cover, or the agency "
      "addressed it without writing about it. These are different things and this report cannot "
      "always separate them.</p>")
    A(f"<p><b>Coverage.</b> {m['orphan_responses']} agency responses matched no comment in this "
      "corpus. Where the full docket has not been pulled, that number is mostly missing comments "
      "rather than parser error — but it is the figure to check before treating the response rate "
      "as complete.</p>")
    A("<p><b>Machine judgement.</b> Argument types, significance, and accepted/partial/rejected "
      "verdicts are model-generated. They are reproducible and every one links back to a specific "
      "comment ID and Federal Register page, but they are estimates and should be spot-checked "
      "before being quoted.</p>")
    A("<p><b>Reproducibility.</b> Ingest, campaign detection, clustering, and the text "
      "diff are deterministic. Linkage is not exactly so: retrieval proposes candidates "
      "and a model adjudicates each pair independently, so borderline matches can fall "
      "either way between runs. Aggregate rates are stable; an individual borderline "
      "row may not be.</p>")
    A("<p><b>Parser coverage.</b> The preamble parser recognizes a limited set of agency "
      "conventions and reports which one matched. Where coverage is low, treat unmatched "
      "comments as unknown rather than unanswered.</p>")
    A("<p><b>Correlation, not causation.</b> A section changing between proposal and final rule "
      "after a comment cited it is evidence that the comment mattered. It is not proof. Agencies "
      "change text for many reasons, including comments this corpus does not contain.</p></div>")

    A("<h2>Built to</h2><div class='card'><dl class='doc'>")
    for rule, gloss in brand.DOCTRINE:
        A(f"<dt>{_esc(rule)}</dt><dd>{_esc(gloss)}</dd>")
    A("</dl></div>")

    A("<footer><div class='fgrid'><div>")
    A(f"<b>{_esc(brand.ORG_TM)}</b> · {_esc(brand.POSITIONING)}<br>")
    A(f"<a href='https://{brand.SITE}'>{brand.SITE}</a> · "
      f"<a href='mailto:{brand.EMAIL}'>{brand.EMAIL}</a><br>")
    A(f"<a href='{brand.REPO}'>{brand.REPO}</a>")
    A("</div><div class='fr'>")
    A(f"{_esc(brand.LEGAL)}<br>{_esc(brand.PRODUCT)} v{_esc(brand.VERSION)} · "
      f"{_esc(brand.LICENSE)} · {_esc(docket_id)} · {now}<br>")
    A("Built from public data: the regulations.gov and Federal Register APIs.<br>")
    A(f"{_esc(brand.API_ATTRIBUTION)}")
    A("</div></div></footer>")
    A("</div></body></html>")

    say("report built")
    return "".join(P)
