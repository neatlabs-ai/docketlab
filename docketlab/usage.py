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

"""Usage and cost accounting.

Two questions this answers, both of which you otherwise find out the hard way:
*how much quota do I have left right now*, and *what will finishing this cost*.

The regulations.gov quota is the harder one because it is invisible until you
hit it. Every response carries `X-RateLimit-Remaining`, so rather than guessing
from a local counter that drifts, we record what the server itself reported on
the last call and fall back to our own rolling count when no header arrived.

Token spend is recorded per call with its model, so the estimator extrapolates
from what *this* docket actually cost rather than from a generic assumption.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from . import config, store

# Published list prices, USD per million tokens. Editable in Settings because
# these change and a stale hardcoded number is worse than no number.
DEFAULT_PRICES = {
    "claude-opus-4":      {"in": 15.00, "out": 75.00},
    "claude-opus-4-1":    {"in": 15.00, "out": 75.00},
    "claude-sonnet-4-5":  {"in": 3.00,  "out": 15.00},
    "claude-sonnet-4-6":  {"in": 3.00,  "out": 15.00},
    "claude-haiku-4-5":   {"in": 1.00,  "out": 5.00},
    "_default":           {"in": 3.00,  "out": 15.00},
}

PRICE_PATH = config.ROOT / "prices.json"


def prices() -> dict:
    if PRICE_PATH.exists():
        try:
            p = dict(DEFAULT_PRICES)
            p.update(json.loads(PRICE_PATH.read_text(encoding="utf-8")))
            return p
        except Exception:
            pass
    return dict(DEFAULT_PRICES)


def save_prices(d: dict):
    PRICE_PATH.write_text(json.dumps(d, indent=1), encoding="utf-8")


def price_for(model: str) -> dict:
    p = prices()
    if model in p:
        return p[model]
    for k, v in p.items():
        if k != "_default" and model and model.startswith(k):
            return v
    return p["_default"]


def _init():
    """The api_calls table lives in the base schema; this just ensures it's up."""
    store.init()


def record(service: str, endpoint: str = "", status: int | None = None,
           headers=None, model: str = "", tokens_in: int = 0, tokens_out: int = 0):
    """Log one API call. Never raises — accounting must not break a pipeline."""
    try:
        _init()
        rem = lim = None
        if headers:
            for k in ("X-RateLimit-Remaining", "x-ratelimit-remaining"):
                if k in headers:
                    try:
                        rem = int(headers[k])
                    except (TypeError, ValueError):
                        pass
                    break
            for k in ("X-RateLimit-Limit", "x-ratelimit-limit"):
                if k in headers:
                    try:
                        lim = int(headers[k])
                    except (TypeError, ValueError):
                        pass
                    break
        with store.db() as con:
            con.execute(
                "INSERT INTO api_calls VALUES (current_timestamp,?,?,?,?,?,?,?,?)",
                [service, endpoint[:120], status, rem, lim, model or None,
                 int(tokens_in or 0), int(tokens_out or 0)],
            )
    except Exception:
        pass


# ── Reads ────────────────────────────────────────────────────────────────────

def quota(service: str = "regulations.gov", window_hours: int = 1) -> dict:
    """What's left this hour, preferring what the server told us."""
    _init()
    since = datetime.now() - timedelta(hours=window_hours)
    df = store.query(
        "SELECT ts, status, remaining, limit_total FROM api_calls "
        "WHERE service = ? AND ts >= ? ORDER BY ts",
        [service, since],
    )
    used = len(df)
    reported = None
    limit = None
    if not df.empty:
        rem = df[df.remaining.notna()]
        if not rem.empty:
            reported = int(rem.remaining.iloc[-1])
        lim = df[df.limit_total.notna()]
        if not lim.empty:
            limit = int(lim.limit_total.iloc[-1])
    limit = limit or config.REQS_PER_HOUR
    remaining = reported if reported is not None else max(limit - used, 0)

    # When the window resets: an hour after the oldest call still inside it.
    resets_in = None
    if not df.empty:
        oldest = df.ts.iloc[0]
        try:
            resets_in = max(
                0, int((oldest + timedelta(hours=window_hours) - datetime.now()).total_seconds())
            )
        except Exception:
            resets_in = None

    throttled = int((df.status == 429).sum()) if not df.empty else 0
    return {
        "service": service,
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "source": "server header" if reported is not None else "local count",
        "resets_in": resets_in,
        "throttled": throttled,
        "pct": round(100 * remaining / limit, 1) if limit else None,
    }


def spend(days: int = 30) -> dict:
    """Token spend and dollar cost, by model."""
    _init()
    since = datetime.now() - timedelta(days=days)
    df = store.query(
        "SELECT model, sum(tokens_in) i, sum(tokens_out) o, count(*) n "
        "FROM api_calls WHERE service='anthropic' AND ts >= ? GROUP BY 1",
        [since],
    )
    rows, total = [], 0.0
    for r in df.itertuples():
        if not r.model:
            continue
        p = price_for(r.model)
        cost = (int(r.i) / 1e6) * p["in"] + (int(r.o) / 1e6) * p["out"]
        total += cost
        rows.append(
            {"model": r.model, "calls": int(r.n), "tokens_in": int(r.i),
             "tokens_out": int(r.o), "cost": round(cost, 4)}
        )
    rows.sort(key=lambda x: -x["cost"])
    return {"days": days, "by_model": rows, "total": round(total, 4)}


def estimate(docket_id: str, total_comments: int | None = None) -> dict:
    """Project the cost of finishing this docket from what it has cost so far.

    Deliberately not a generic formula. The two things that decide the bill —
    how much a docket collapses under dedup, and how long its comments are —
    vary enormously between dockets, so anything extrapolated from a different
    docket is a guess dressed as a number.
    """
    from . import settings

    have = store.scalar(
        "SELECT count(*) FROM comments WHERE docket_id = ?", [docket_id]
    ) or 0
    units = store.scalar(
        "SELECT count(*) FROM dedup d JOIN comments c USING (comment_id) "
        "WHERE c.docket_id = ? AND (campaign_id IS NULL OR is_exemplar)", [docket_id]
    ) or 0
    done = store.query(
        "SELECT model, sum(tokens_in) i, sum(tokens_out) o, count(*) n "
        "FROM analysis a JOIN comments c USING (comment_id) "
        "WHERE c.docket_id = ? GROUP BY 1", [docket_id]
    )

    out: dict = {
        "docket_id": docket_id, "pulled": have, "units": units,
        "analyzed": int(done.n.sum()) if not done.empty else 0,
        "total_comments": total_comments,
    }

    observed_cost = 0.0
    tin = tout = 0
    for r in done.itertuples():
        p = price_for(r.model or settings.get("model_deep"))
        observed_cost += (int(r.i) / 1e6) * p["in"] + (int(r.o) / 1e6) * p["out"]
        tin += int(r.i)
        tout += int(r.o)
    out["spent_analysis"] = round(observed_cost, 4)
    out["tokens"] = {"in": tin, "out": tout}

    n_done = out["analyzed"]
    if n_done:
        out["per_unit_cost"] = round(observed_cost / n_done, 6)
        out["per_unit_tokens"] = round((tin + tout) / n_done)
    else:
        out["per_unit_cost"] = None
        out["per_unit_tokens"] = None

    # Remaining work on what's already pulled.
    left_now = max(units - n_done, 0)
    out["units_remaining"] = left_now
    if out["per_unit_cost"] is not None:
        out["cost_to_finish_pulled"] = round(left_now * out["per_unit_cost"], 4)

    # Whole docket, assuming the collapse ratio holds on the part not yet seen.
    if total_comments and have:
        ratio = units / have
        projected_units = round(total_comments * ratio)
        out["projected_units"] = projected_units
        out["collapse_ratio"] = round(1 - ratio, 4)
        if out["per_unit_cost"] is not None:
            analysis = projected_units * out["per_unit_cost"]
            # Linkage adds up to TOP_K adjudication calls per unit; observed
            # runs land near 2, and each is smaller than an extraction call.
            linkage = projected_units * out["per_unit_cost"] * 0.9
            out["projected_analysis"] = round(analysis, 2)
            out["projected_linkage"] = round(linkage, 2)
            out["projected_total"] = round(analysis + linkage, 2)
        out["api_requests"] = total_comments + max(1, total_comments // 250) + 3
        out["api_hours"] = round(out["api_requests"] / max(config.REQS_PER_HOUR, 1), 2)
    return out
