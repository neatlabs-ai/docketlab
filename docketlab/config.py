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

"""DOCKETLAB configuration.

Everything is environment-overridable so the same code runs against a live
docket on Windows and against synthetic fixtures in a sandbox.
"""
from __future__ import annotations

import os
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT = Path(os.environ.get("DL_HOME", Path.home() / "DOCKETLAB_DATA")).expanduser()
RAW = ROOT / "raw"          # verbatim API payloads, never mutated
FILES = ROOT / "files"      # downloaded attachments
DERIVED = ROOT / "derived"  # parquet + duckdb
CACHE = ROOT / "cache"      # embeddings, model responses

for _p in (RAW, FILES, DERIVED, CACHE):
    _p.mkdir(parents=True, exist_ok=True)

DB_PATH = DERIVED / "docketlab.duckdb"

# ── Credentials ──────────────────────────────────────────────────────────────
# Free key: https://api.data.gov/signup/   (1,000 requests/hour)
REGS_API_KEY = os.environ.get("DL_REGS_KEY", "DEMO_KEY")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ── API endpoints ────────────────────────────────────────────────────────────
REGS_BASE = "https://api.regulations.gov/v4"
FEDREG_BASE = "https://www.federalregister.gov/api/v1"  # free, no key

# ── Rate limiting ────────────────────────────────────────────────────────────
# api.data.gov gives 1,000 req/hr per key. We self-throttle below the ceiling
# and checkpoint after every write so an exhausted quota is resumable.
REQS_PER_HOUR = int(os.environ.get("DL_REQS_PER_HOUR", "950"))
MIN_INTERVAL = 3600.0 / max(REQS_PER_HOUR, 1)

# ── Analysis tunables ────────────────────────────────────────────────────────
MINHASH_PERM = 128
NEAR_DUP_THRESHOLD = float(os.environ.get("DL_NEARDUP", "0.85"))
SEMANTIC_EPS = float(os.environ.get("DL_SEMEPS", "0.35"))
MIN_CLUSTER_SIZE = int(os.environ.get("DL_MINCLUSTER", "3"))

# Model routing: cheap model triages representatives, capable model reads the
# substantive tail. Both overridable; the picker in the UI writes these.
MODEL_TRIAGE = os.environ.get("DL_MODEL_TRIAGE", "claude-haiku-4-5-20251001")
MODEL_DEEP = os.environ.get("DL_MODEL_DEEP", "claude-sonnet-4-6")

PORT = int(os.environ.get("DL_PORT", "7910"))
