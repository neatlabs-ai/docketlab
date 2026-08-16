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

"""Deduplication and campaign detection.

Order matters. Exact hashing is free, MinHash is cheap, embeddings cost real
compute — so run them in that order and let each stage shrink the input to the
next. On a form-letter-heavy docket this is the difference between a $150 run
and a $5 one.

Doctrine: collapsing is a *display* operation. Nothing is deleted, every
member of a campaign keeps its own row, and counts always report the true
number of submissions. A campaign of 40,000 is a real political fact even when
it contributes one argument.
"""
from __future__ import annotations

import difflib
import hashlib
import re

from datasketch import MinHash, MinHashLSH, MinHashLSHEnsemble

from . import config, store

_WORD = re.compile(r"[a-z0-9']+")

# Share of the shorter text's shingles that must appear in the longer one for
# the pair to count as the same campaign scaffold plus an addition.
CONTAINMENT_THRESHOLD = 0.75


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _shingles(tokens: list[str], k: int = 5) -> set[str]:
    if len(tokens) < k:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


def _exact_hash(text: str) -> str:
    canon = " ".join(_tokens(text))
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


def _minhash(text: str) -> MinHash:
    m = MinHash(num_perm=config.MINHASH_PERM)
    for sh in _shingles(_tokens(text)):
        m.update(sh.encode())
    return m


def split_template(exemplar: str, member: str) -> tuple[float, str]:
    """Return (share of member that is campaign scaffold, the personal insert).

    Form letters increasingly carry a "and here's my story" paragraph. That
    insert is genuine content and is the single most-discarded signal in
    comment analysis — a campaign of 40,000 with 3,000 substantive inserts is
    a different object than a campaign of 40,000 identical texts.
    """
    a, b = _tokens(exemplar), _tokens(member)
    if not b:
        return 1.0, ""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    matched = sum(blk.size for blk in sm.get_matching_blocks())
    ratio = matched / len(b)
    kept: list[str] = []
    idx = 0
    for blk in sm.get_matching_blocks():
        if blk.b > idx:
            kept.extend(b[idx : blk.b])
        idx = blk.b + blk.size
    if idx < len(b):
        kept.extend(b[idx:])
    insert = " ".join(kept)
    return round(ratio, 4), insert if len(kept) >= 12 else ""


def run(docket_id: str, progress=None) -> dict:
    say = progress or (lambda m: None)
    df = store.query(
        "SELECT comment_id, full_text, word_count FROM comments "
        "WHERE docket_id = ? AND full_text IS NOT NULL ORDER BY comment_id",
        [docket_id],
    )
    if df.empty:
        return {"error": "no comments with text — run ingest first"}

    texts = dict(zip(df.comment_id, df.full_text))
    say(f"hashing {len(texts)} comments")

    # ── Stage 1: exact duplicates ────────────────────────────────────────────
    by_hash: dict[str, list[str]] = {}
    hashes = {}
    for cid, txt in texts.items():
        h = _exact_hash(txt)
        hashes[cid] = h
        by_hash.setdefault(h, []).append(cid)
    exact_families = {h: ids for h, ids in by_hash.items() if len(ids) > 1}
    say(f"{len(exact_families)} exact-duplicate families")

    # ── Stage 2: near duplicates over exact-family representatives ───────────
    reps = [ids[0] for ids in by_hash.values()]
    lsh = MinHashLSH(threshold=config.NEAR_DUP_THRESHOLD, num_perm=config.MINHASH_PERM)
    sigs = {}
    for cid in reps:
        m = _minhash(texts[cid])
        sigs[cid] = m
        lsh.insert(cid, m)
    say(f"MinHash indexed {len(reps)} representatives")

    parent: dict[str, str] = {c: c for c in reps}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[max(rx, ry)] = min(rx, ry)

    for cid in reps:
        for other in lsh.query(sigs[cid]):
            if other != cid:
                union(cid, other)

    # ── Stage 2b: containment ────────────────────────────────────────────────
    # Jaccard alone splits a campaign whenever participants append a personal
    # paragraph: a 55-word scaffold inside an 80-word submission scores ~0.69
    # and falls under any sane near-duplicate threshold. But the scaffold is
    # *contained* in the variant, which is the relation we actually mean by
    # "same campaign." Without this pass the same form letter shows up as three
    # separate campaigns and the personalized inserts are never isolated.
    #
    # This was originally an all-pairs scan. That is fine at 1,500 comments and
    # ruinous at 40,000 — measured, the quadratic version extrapolated to about
    # 100 minutes on a large campaign docket, which is exactly the case the
    # feature exists for. LSH Ensemble indexes on containment directly, so only
    # plausible pairs are ever compared exactly.
    shingle_sets = {cid: _shingles(_tokens(texts[cid])) for cid in reps}
    candidates = [c for c in reps if len(shingle_sets[c]) >= 8]
    if len(candidates) > 1:
        try:
            ensemble = MinHashLSHEnsemble(
                threshold=CONTAINMENT_THRESHOLD,
                num_perm=config.MINHASH_PERM,
                num_part=16,
            )
            ensemble.index(
                (cid, sigs[cid], len(shingle_sets[cid])) for cid in candidates
            )
            for cid in candidates:
                s_small = shingle_sets[cid]
                for other in ensemble.query(sigs[cid], len(s_small)):
                    if other == cid:
                        continue
                    s_big = shingle_sets[other]
                    if len(s_big) > 4 * len(s_small):
                        continue  # too much longer to be the same campaign
                    # LSH is approximate; confirm exactly before merging.
                    if len(s_small & s_big) / len(s_small) >= CONTAINMENT_THRESHOLD:
                        union(cid, other)
        except Exception as e:  # never let an optimization lose the pass
            say(f"containment index unavailable ({type(e).__name__}); exact scan")
            by_size = sorted(candidates, key=lambda c: len(shingle_sets[c]))
            for i, small in enumerate(by_size[:4000]):
                s_small = shingle_sets[small]
                for big in by_size[i + 1 :]:
                    s_big = shingle_sets[big]
                    if len(s_big) > 4 * len(s_small):
                        break
                    if len(s_small & s_big) / len(s_small) >= CONTAINMENT_THRESHOLD:
                        union(small, big)

    groups: dict[str, list[str]] = {}
    for cid in reps:
        groups.setdefault(find(cid), []).append(cid)

    # ── Stage 3: assign campaign ids and split templates ─────────────────────
    rows = []
    campaign_of_rep: dict[str, str | None] = {}
    n_campaigns = 0
    for root, members in groups.items():
        total = sum(len(by_hash[hashes[m]]) for m in members)
        if total < 2:
            campaign_of_rep[root] = None
            for m in members:
                campaign_of_rep[m] = None
            continue
        n_campaigns += 1
        camp = f"C{n_campaigns:04d}"
        for m in members:
            campaign_of_rep[m] = camp

    # The exemplar should be the *shortest* member, which approximates the bare
    # scaffold. Picking an arbitrary member means a long personalized variant
    # can become the reference and every other member's "insert" is then
    # measured against someone else's personal story.
    exemplars: dict[str, str] = {}
    for camp in {c for c in campaign_of_rep.values() if c}:
        members = [cid for cid, c in campaign_of_rep.items() if c == camp]
        exemplars[camp] = min(members, key=lambda m: len(texts[m]))

    for cid, txt in texts.items():
        h = hashes[cid]
        rep = by_hash[h][0]
        camp = campaign_of_rep.get(rep)
        if camp:
            ex = exemplars[camp]
            if cid == ex:
                ratio, insert = 1.0, ""
            else:
                ratio, insert = split_template(texts[ex], txt)
        else:
            ratio, insert = 0.0, ""
        rows.append(
            {
                "comment_id": cid,
                "exact_hash": h,
                "campaign_id": camp,
                "is_exemplar": bool(camp and cid == exemplars[camp]),
                "template_ratio": ratio,
                "insert_text": insert or None,
            }
        )

    with store.db() as con:
        con.execute("DELETE FROM dedup WHERE comment_id IN (SELECT comment_id FROM comments WHERE docket_id = ?)", [docket_id])
    store.upsert("dedup", rows)

    campaigned = sum(1 for r in rows if r["campaign_id"])
    unique = len(rows) - campaigned + n_campaigns
    with_inserts = sum(1 for r in rows if r["insert_text"])
    summary = {
        "comments": len(rows),
        "campaigns": n_campaigns,
        "in_campaigns": campaigned,
        "singletons": len(rows) - campaigned,
        "units_to_analyze": unique,
        "personal_inserts": with_inserts,
        "reduction": round(1 - unique / max(len(rows), 1), 4),
    }
    store.log("dedup", str(summary))
    say(f"collapsed {len(rows)} → {unique} analysis units")
    return summary
