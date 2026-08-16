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

"""DOCKETLAB console — local Flask app on 127.0.0.1.

Stages run in a background thread and stream progress to a ring buffer the page
polls, so a two-hour ingest doesn't block the browser and a browser refresh
doesn't kill the run.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
import traceback
from collections import deque

from flask import Flask, jsonify, redirect, render_template, request, url_for

from . import (analyze, config, dedup, discover, fedreg, fixtures, ingest,
               linkage, metrics, report, semantic, settings, store, textdiff,
               usage, watch)
from . import brand

app = Flask(__name__)


@app.context_processor
def _brand():
    return {"B": brand}

LOG: deque[str] = deque(maxlen=400)
STATE = {"running": None, "last": None}
_lock = threading.Lock()


def say(msg: str):
    LOG.append(msg)


def _bg(name: str, fn, *args, **kwargs):
    def wrapper():
        try:
            result = fn(*args, progress=say, **kwargs)
            STATE["last"] = {"stage": name, "result": result}
            say(f"— {name} finished")
        except Exception as e:
            say(f"!! {name} failed: {type(e).__name__}: {e}")
            say(traceback.format_exc().splitlines()[-1])
            STATE["last"] = {"stage": name, "error": str(e)}
        finally:
            STATE["running"] = None

    with _lock:
        if STATE["running"]:
            return False
        STATE["running"] = name
    say(f"— {name} started")
    threading.Thread(target=wrapper, daemon=True).start()
    return True


# ── Views ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    store.init()
    dockets = store.query(
        """
        SELECT d.docket_id, d.title, d.agency,
               (SELECT count(*) FROM comments c WHERE c.docket_id = d.docket_id) AS comments
        FROM dockets d ORDER BY d.docket_id
        """
    ).to_dict("records")
    active = request.args.get("docket") or (dockets[0]["docket_id"] if dockets else None)
    return render_template(
        "index.html", dockets=dockets, active=active, stats=_stats(active),
        running=STATE["running"], last=STATE["last"],
        has_key=bool(settings.get("anthropic_key")), backend=semantic.BACKEND,
        starters=discover.starters(),
    )


def _stats(docket_id):
    if not docket_id:
        return {}
    q = store.query
    s = {
        "comments": store.scalar("SELECT count(*) FROM comments WHERE docket_id=?", [docket_id]) or 0,
        "with_attachments": store.scalar(
            "SELECT count(*) FROM comments WHERE docket_id=? AND n_attachments>0", [docket_id]) or 0,
        "attachment_only": store.scalar(
            "SELECT count(*) FROM comments WHERE docket_id=? AND text_source='attachment'", [docket_id]) or 0,
        "campaigns": store.scalar(
            "SELECT count(DISTINCT campaign_id) FROM dedup d JOIN comments c USING(comment_id) "
            "WHERE c.docket_id=? AND campaign_id IS NOT NULL", [docket_id]) or 0,
        "units": store.scalar(
            "SELECT count(*) FROM dedup d JOIN comments c USING(comment_id) "
            "WHERE c.docket_id=? AND (campaign_id IS NULL OR is_exemplar)", [docket_id]) or 0,
        "analyzed": store.scalar(
            "SELECT count(*) FROM analysis a JOIN comments c USING(comment_id) "
            "WHERE c.docket_id=?", [docket_id]) or 0,
        # Scoped to the docket. A global count made another docket's
        # adjudications look like this one's.
        "responses": store.scalar(
            "SELECT count(*) FROM responses r JOIN documents d "
            "ON d.fr_doc_number = r.document_id WHERE d.docket_id = ?", [docket_id]) or 0,
        "linked": store.scalar(
            "SELECT count(DISTINCT l.comment_id) FROM linkage l JOIN comments c USING(comment_id) "
            "WHERE c.docket_id=?", [docket_id]) or 0,
    }
    tok = q("SELECT coalesce(sum(tokens_in),0) i, coalesce(sum(tokens_out),0) o FROM analysis")
    s["tokens_in"], s["tokens_out"] = int(tok.i[0]), int(tok.o[0])
    return s


@app.route("/ledger")
def ledger():
    docket_id = request.args.get("docket")
    sort = request.args.get("sort", "unanswered")
    rows = store.query(
        """
        SELECT c.comment_id, c.organization, c.submitter, c.word_count,
               c.text_source, c.n_attachments,
               d.campaign_id, d.template_ratio,
               coalesce(cs.n, 1) AS campaign_size,
               a.stance, a.significance, a.summary, a.novel_evidence,
               a.argument_types, a.provisions, a.requested,
               l.response_id, l.verdict, l.rationale, l.score,
               r.fr_page
        FROM comments c
        JOIN dedup d USING (comment_id)
        LEFT JOIN (SELECT campaign_id, count(*) n FROM dedup GROUP BY 1) cs
               ON cs.campaign_id = d.campaign_id
        LEFT JOIN analysis a USING (comment_id)
        LEFT JOIN linkage l USING (comment_id)
        LEFT JOIN responses r ON r.response_id = l.response_id
        WHERE c.docket_id = ?
          AND (d.campaign_id IS NULL OR d.is_exemplar)
        """,
        [docket_id],
    )
    if rows.empty:
        return render_template("ledger.html", rows=[], docket=docket_id, sort=sort)

    rows["significance"] = rows["significance"].fillna(0).astype(int)
    rows["answered"] = rows["response_id"].notna()
    if sort == "unanswered":
        rows = rows.sort_values(
            ["answered", "significance", "campaign_size"], ascending=[True, False, False]
        )
    elif sort == "weight":
        rows = rows.sort_values("campaign_size", ascending=False)
    else:
        rows = rows.sort_values("significance", ascending=False)

    maxw = max(int(rows.campaign_size.max()), 1)
    recs = rows.to_dict("records")
    for r in recs:
        r["bar"] = max(2, round(100 * r["campaign_size"] / maxw))
        for f in ("argument_types", "provisions", "requested"):
            try:
                r[f] = json.loads(r[f]) if r[f] else []
            except Exception:
                r[f] = []
    return render_template("ledger.html", rows=recs, docket=docket_id, sort=sort)


@app.route("/comment/<path:cid>")
def comment(cid):
    c = store.query("SELECT * FROM comments WHERE comment_id=?", [cid])
    if c.empty:
        return "No such comment", 404
    c = c.to_dict("records")[0]
    d = store.query("SELECT * FROM dedup WHERE comment_id=?", [cid]).to_dict("records")
    a = store.query("SELECT * FROM analysis WHERE comment_id=?", [cid]).to_dict("records")
    l = store.query(
        "SELECT l.*, r.comment_para, r.response_para, r.fr_page FROM linkage l "
        "LEFT JOIN responses r USING (response_id) WHERE l.comment_id=?", [cid]
    ).to_dict("records")
    siblings = []
    if d and d[0].get("campaign_id"):
        siblings = store.query(
            "SELECT comment_id, template_ratio, insert_text FROM dedup "
            "WHERE campaign_id=? AND insert_text IS NOT NULL LIMIT 25",
            [d[0]["campaign_id"]],
        ).to_dict("records")
    for rec in a:
        for f in ("argument_types", "provisions", "requested"):
            try:
                rec[f] = json.loads(rec[f]) if rec[f] else []
            except Exception:
                rec[f] = []
    return render_template(
        "comment.html", c=c, d=d[0] if d else None, a=a[0] if a else None,
        links=l, siblings=siblings,
    )


# ── Stage triggers ───────────────────────────────────────────────────────────

@app.post("/run/<stage>")
def run_stage(stage):
    docket = request.form.get("docket") or request.args.get("docket")
    started = False
    if stage == "fixture":
        started = _bg("fixture", fixtures.build)
    elif stage == "ingest":
        cap = request.form.get("limit") or request.args.get("limit")
        cap = int(cap) if (cap or "").isdigit() and int(cap) > 0 else None
        started = _bg("ingest", ingest.pull_docket, docket, limit=cap)
        # Follow what was just pulled. Otherwise a pull started from the Dockets
        # tab leaves the console pointed at the previous docket, and the next
        # stage runs against the wrong corpus without saying so.
        if started:
            clean = discover.normalize_id(docket)
            if clean:
                docket = clean
    elif stage == "dedup":
        started = _bg("dedup", dedup.run, docket)
    elif stage == "cluster":
        started = _bg("cluster", semantic.cluster, docket)
    elif stage == "fedreg":
        started = _bg("federal register", fedreg.load, docket)
    elif stage == "analyze":
        started = _bg("analysis", analyze.run, docket)
    elif stage == "textdiff":
        started = _bg("text diff", textdiff.run, docket)
    elif stage == "linkage":
        started = _bg("linkage", linkage.run, docket,
                      adjudicate=bool(settings.get("anthropic_key")))
    elif stage == "score":
        started = _bg("fixture score", fixtures.score)
    if not started:
        say("!! another stage is already running")
    return redirect(url_for("index", docket=docket))


@app.get("/log")
def log():
    return jsonify({"lines": list(LOG), "running": STATE["running"]})


# ── Settings ─────────────────────────────────────────────────────────────────

@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    notice = None
    if request.method == "POST":
        action = request.form.get("action", "save")
        if action == "save":
            updates = {}
            for field in ("regs_key", "anthropic_key"):
                val = request.form.get(field, "")
                # An untouched masked field means "leave it alone".
                if val and not val.startswith("\u2022"):
                    updates[field] = val
                elif request.form.get(f"clear_{field}"):
                    updates[field] = ""
            for field in ("model_triage", "model_deep"):
                if request.form.get(field):
                    updates[field] = request.form[field]
            settings.save(updates)
            notice = ("ok", "Saved.")
        elif action == "test_regs":
            ok, msg = settings.test_regs()
            notice = ("ok" if ok else "bad", msg)
        elif action == "test_anthropic":
            ok, msg = settings.test_anthropic()
            notice = ("ok" if ok else "bad", msg)

    cur = settings.load(force=True)
    return render_template(
        "settings.html",
        notice=notice,
        regs_mask=settings.mask(settings.get("regs_key")),
        anth_mask=settings.mask(settings.get("anthropic_key")),
        regs_src=settings.source("regs_key"),
        anth_src=settings.source("anthropic_key"),
        model_triage=settings.get("model_triage"),
        model_deep=settings.get("model_deep"),
        models=settings.available_models(),
        path=str(settings.PATH),
    )


# ── Docket discovery ─────────────────────────────────────────────────────────

@app.route("/dockets")
def dockets_page():
    term = request.args.get("q", "")
    check = request.args.get("check", "")
    results, pre, error = [], None, None
    try:
        if term:
            results = discover.search(term)
        if check:
            pre = discover.preflight(check.strip())
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    return render_template(
        "dockets.html", starters=discover.starters(), q=term, results=results,
        pre=pre, error=error, check=check,
        has_regs=settings.source("regs_key") != "not set",
    )


@app.route("/watch", methods=["GET", "POST"])
def watch_page():
    notice, error = None, None
    profiles = watch.load()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "reset":
            watch.save(list(watch.STARTER_PROFILES))
            notice = ("ok", "Starter profiles restored.")
        elif action == "delete":
            name = request.form.get("name", "").strip()
            profiles = [p for p in profiles if p.get("name") != name]
            watch.save(profiles)
            notice = ("ok", f"Deleted {name}.")
        elif action == "save":
            name = (request.form.get("name") or "").strip()
            if not name:
                notice = ("bad", "A profile needs a name.")
            else:
                months = request.form.get("months", "24")
                prof = {
                    "name": name,
                    "terms": (request.form.get("terms") or "").strip(),
                    "months": int(months) if months.isdigit() else 24,
                    "agencies": request.form.getlist("agencies"),
                }
                profiles = [p for p in profiles if p.get("name") != name] + [prof]
                watch.save(profiles)
                notice = ("ok", f"Saved {name}.")
        profiles = watch.load()

    idx = request.args.get("profile")
    closing = request.args.get("closing")
    active, results, counts, heading, scanned = None, [], {}, "", False

    try:
        if closing:
            days = int(closing) if str(closing).isdigit() else 30
            results = watch.closing_soon(days, progress=say)
            counts = {"open": len(results), "analyzable": 0, "closed": 0}
            heading = f"Comment windows closing within {days} days"
            scanned = True
        elif idx is not None and str(idx).isdigit() and int(idx) < len(profiles):
            active = profiles[int(idx)]
            out = watch.scan(active, progress=say)
            results, counts = out["results"], out["counts"]
            heading = active["name"]
            scanned = True
    except Exception as e:
        error = f"Scan failed: {type(e).__name__}: {e}"

    return render_template(
        "watch.html", profiles=profiles, active=active, results=results,
        counts=counts, heading=heading, scanned=scanned, notice=notice,
        error=error, agency_list=watch.agencies(),
    )


@app.route("/usage", methods=["GET", "POST"])
def usage_page():
    notice = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "reset_prices":
            try:
                usage.PRICE_PATH.unlink(missing_ok=True)
            except Exception:
                pass
            notice = ("ok", "Prices reset to defaults.")
        elif action == "save_prices":
            new = {}
            for k, v in request.form.items():
                if k.startswith(("in__", "out__")):
                    side, name = k.split("__", 1)
                    try:
                        new.setdefault(name, {})[side] = float(v)
                    except ValueError:
                        pass
            clean = {k: v for k, v in new.items() if "in" in v and "out" in v}
            if clean:
                usage.save_prices(clean)
                notice = ("ok", f"Saved prices for {len(clean)} models.")
            else:
                notice = ("bad", "Nothing saved — prices must be numbers.")

    docket = request.args.get("docket")
    total = request.args.get("total")
    total = int(total) if (total or "").isdigit() else None
    est = usage.estimate(docket, total) if docket else None
    recent = store.query(
        "SELECT ts, service, endpoint, status, model, tokens_in, tokens_out "
        "FROM api_calls ORDER BY ts DESC LIMIT 25"
    ).to_dict("records")
    for r in recent:
        r["ts"] = str(r["ts"])[:19]
    return render_template(
        "usage.html", notice=notice,
        quotas=[usage.quota("regulations.gov"), usage.quota("anthropic")],
        spend=usage.spend(), est=est, prices=usage.prices(), recent=recent,
    )


@app.route("/guide")
def guide_page():
    return render_template("guide.html", home=str(config.ROOT))


# ── Metrics ──────────────────────────────────────────────────────────────────

@app.route("/metrics")
def metrics_page():
    docket = request.args.get("docket")
    m = metrics.compute(docket) if docket else {}
    return render_template("metrics.html", m=m, caution=metrics.caution)


@app.get("/export")
def export_report():
    from flask import Response

    docket = request.args.get("docket")
    if not docket:
        return render_template("notready.html", reason="No docket selected."), 400
    have = store.scalar(
        "SELECT count(*) FROM dedup d JOIN comments c USING (comment_id) "
        "WHERE c.docket_id = ?", [docket]
    ) or 0
    if not have:
        # Not an error — the pipeline simply hasn't run yet. Say which stage.
        pulled = store.scalar(
            "SELECT count(*) FROM comments WHERE docket_id = ?", [docket]) or 0
        reason = (
            f"{docket} has {pulled} comments but no analysis units yet — run "
            "<b>Find campaigns</b> first."
            if pulled else
            f"Nothing pulled for {docket} yet — run <b>Pull comments</b> first."
        )
        return render_template("notready.html", reason=reason, docket=docket), 409
    try:
        body = report.build(docket, progress=say)
    except Exception as e:
        return render_template(
            "notready.html", docket=docket,
            reason=f"The report could not be built: {e}"
        ), 500
    stamp = datetime.now().strftime("%Y%m%d")
    name = f"docketlab_{docket.replace('/', '-')}_{stamp}.html"
    return Response(
        body,
        mimetype="text/html",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


def main():
    try:
        store.init()
    except store.AlreadyRunning as e:
        print(f"\n{e}")
        return 1
    print(f"\n  {brand.ORG_TM} {brand.PRODUCT} v{brand.VERSION} — {brand.TAGLINE}")
    print(f"  {brand.SITE} · {brand.EMAIL}")
    print(f"\n  → http://127.0.0.1:{config.PORT}")
    print(f"  data: {config.ROOT}")
    print(f"  regulations.gov key: {settings.source('regs_key')}")
    print(f"  anthropic key: {'set' if config.ANTHROPIC_KEY else 'not set — analysis stages disabled'}\n")
    app.run(host="127.0.0.1", port=config.PORT, debug=False)


if __name__ == "__main__":
    main()
