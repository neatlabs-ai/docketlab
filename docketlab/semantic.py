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

"""Embeddings and semantic clustering — all local, no API calls.

Lexical dedup catches copy-paste campaigns. It does not catch the newer
pattern: a campaign whose participants each ran the sponsor's talking points
through a chatbot, producing texts that share no 5-grams but one argument.
Embeddings catch those, and running them locally means you can re-cluster
fifty times while tuning thresholds without watching a meter.

Backend order:
  1. sentence-transformers (best quality, ~90MB model, CPU is fine)
  2. TF-IDF + truncated SVD (always available, decent for near-neighbors)
"""
from __future__ import annotations

import hashlib
import pickle

import numpy as np

from . import config, store

_MODEL = None
BACKEND = "none"


def _load_st():
    global _MODEL, BACKEND
    if _MODEL is not None:
        return _MODEL
    try:
        from sentence_transformers import SentenceTransformer

        _MODEL = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        BACKEND = "sentence-transformers/all-MiniLM-L6-v2"
        return _MODEL
    except Exception:
        BACKEND = "tfidf-svd"
        return None


def embed(texts: list[str], cache_key: str = "") -> np.ndarray:
    """Return L2-normalized embeddings. Cached to disk by content hash."""
    if not texts:
        return np.zeros((0, 8), dtype="float32")

    digest = hashlib.sha256(
        (cache_key + "||" + "||".join(t[:400] for t in texts)).encode()
    ).hexdigest()[:20]
    cache_file = config.CACHE / f"emb_{digest}.pkl"
    if cache_file.exists():
        with cache_file.open("rb") as fh:
            vecs, backend = pickle.load(fh)
        globals()["BACKEND"] = backend
        return vecs

    model = _load_st()
    if model is not None:
        vecs = model.encode(
            [t[:6000] for t in texts],
            batch_size=32,
            show_progress_bar=False,
            normalize_embeddings=True,
        ).astype("float32")
    else:
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.preprocessing import normalize

        tfidf = TfidfVectorizer(
            max_features=60000, ngram_range=(1, 2), min_df=1, sublinear_tf=True,
            stop_words="english",
        )
        X = tfidf.fit_transform([t[:20000] for t in texts])
        dims = int(min(256, max(2, X.shape[1] - 1, ), X.shape[0] - 1)) if X.shape[0] > 2 else 2
        vecs = normalize(TruncatedSVD(n_components=dims, random_state=0).fit_transform(X)).astype("float32")

    with cache_file.open("wb") as fh:
        pickle.dump((vecs, BACKEND), fh)
    return vecs


def cluster(docket_id: str, progress=None) -> dict:
    """Cluster the analysis units (campaign exemplars + singletons)."""
    say = progress or (lambda m: None)
    df = store.query(
        """
        SELECT c.comment_id, c.full_text
        FROM comments c JOIN dedup d USING (comment_id)
        WHERE c.docket_id = ?
          AND (d.campaign_id IS NULL OR d.is_exemplar)
          AND c.full_text IS NOT NULL
        ORDER BY c.comment_id
        """,
        [docket_id],
    )
    if df.empty:
        return {"error": "nothing to cluster — run dedup first"}

    say(f"embedding {len(df)} analysis units")
    vecs = embed(df.full_text.tolist(), cache_key=docket_id)
    say(f"backend: {BACKEND}")

    labels = _fit(vecs)
    rows, medoids = [], {}
    for lab in set(labels):
        if lab < 0:
            continue
        idx = np.where(labels == lab)[0]
        centroid = vecs[idx].mean(axis=0)
        medoids[lab] = idx[int(np.argmax(vecs[idx] @ centroid))]
    for i, cid in enumerate(df.comment_id):
        lab = int(labels[i])
        rows.append(
            {
                "cluster_id": lab,
                "comment_id": cid,
                "is_medoid": bool(lab >= 0 and medoids.get(lab) == i),
            }
        )
    with store.db() as con:
        con.execute(
            "DELETE FROM clusters WHERE comment_id IN "
            "(SELECT comment_id FROM comments WHERE docket_id = ?)",
            [docket_id],
        )
    store.upsert("clusters", rows)

    n_clusters = len({l for l in labels if l >= 0})
    n_noise = int(sum(1 for l in labels if l < 0))
    out = {
        "units": len(df),
        "clusters": n_clusters,
        "unclustered": n_noise,
        "backend": BACKEND,
    }
    store.log("cluster", str(out))
    say(f"{n_clusters} semantic clusters, {n_noise} standalone")
    return out


def _fit(vecs: np.ndarray) -> np.ndarray:
    n = len(vecs)
    if n < max(config.MIN_CLUSTER_SIZE * 2, 6):
        return np.array([-1] * n)
    try:
        from sklearn.cluster import HDBSCAN

        return HDBSCAN(
            min_cluster_size=config.MIN_CLUSTER_SIZE,
            metric="euclidean",
            store_centers=None,
        ).fit_predict(vecs)
    except Exception:
        from sklearn.cluster import AgglomerativeClustering

        return AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=config.SEMANTIC_EPS,
            metric="cosine",
            linkage="average",
        ).fit_predict(vecs)
