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

"""Persisted settings.

Keys live in a JSON file under DL_HOME, not in the source tree and not in the
launcher, so re-extracting the zip never clobbers them and nothing secret ends
up in a folder you might share. Environment variables still win when set, which
keeps scripted runs reproducible.

Keys are never written to the run log or echoed back to the browser in full —
the UI only ever sees the last four characters.
"""
from __future__ import annotations

import json
import os
import stat

from . import config

PATH = config.ROOT / "settings.json"

DEFAULTS = {
    "regs_key": "",
    "anthropic_key": "",
    "model_triage": "claude-haiku-4-5-20251001",
    "model_deep": "claude-sonnet-4-6",
}

_cache: dict | None = None


def load(force: bool = False) -> dict:
    global _cache
    if _cache is not None and not force:
        return _cache
    data = dict(DEFAULTS)
    if PATH.exists():
        try:
            data.update(json.loads(PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    _cache = data
    return data


def save(updates: dict) -> dict:
    data = load(force=True)
    for k, v in updates.items():
        if k in DEFAULTS:
            data[k] = (v or "").strip()
    PATH.write_text(json.dumps(data, indent=1), encoding="utf-8")
    try:  # best effort on Windows; a no-op on some filesystems
        PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass
    global _cache
    _cache = data
    return data


def get(key: str) -> str:
    """Environment wins, then the saved file, then the default."""
    env_names = {
        "regs_key": "DL_REGS_KEY",
        "anthropic_key": "ANTHROPIC_API_KEY",
        "model_triage": "DL_MODEL_TRIAGE",
        "model_deep": "DL_MODEL_DEEP",
    }
    env = os.environ.get(env_names.get(key, ""), "")
    if env and env != "DEMO_KEY":
        return env
    return load().get(key) or env or DEFAULTS.get(key, "")


def mask(value: str) -> str:
    if not value:
        return ""
    return f"{'•' * 8}{value[-4:]}" if len(value) > 4 else "•" * len(value)


def source(key: str) -> str:
    env_names = {"regs_key": "DL_REGS_KEY", "anthropic_key": "ANTHROPIC_API_KEY"}
    if os.environ.get(env_names.get(key, ""), "") not in ("", "DEMO_KEY"):
        return "environment"
    if load().get(key):
        return "saved"
    return "not set"


# ── Key tests ────────────────────────────────────────────────────────────────

def test_regs() -> tuple[bool, str]:
    import requests

    key = get("regs_key") or "DEMO_KEY"
    try:
        r = requests.get(
            f"{config.REGS_BASE}/dockets",
            params={"page[size]": 5, "filter[searchTerm]": "cybersecurity"},
            headers={"X-Api-Key": key},
            timeout=30,
        )
    except Exception as e:
        return False, f"could not reach regulations.gov: {type(e).__name__}"
    if r.status_code == 403:
        return False, "key rejected (403) — check for stray spaces"
    if r.status_code == 429:
        return False, "key valid but hourly quota is spent right now"
    if r.status_code != 200:
        return False, f"unexpected status {r.status_code}"
    remaining = r.headers.get("X-RateLimit-Remaining", "?")
    label = "DEMO_KEY" if key == "DEMO_KEY" else "key"
    return True, f"{label} works — {remaining} requests left this hour"


def test_anthropic() -> tuple[bool, str]:
    key = get("anthropic_key")
    if not key:
        return False, "no key set"
    try:
        import anthropic
    except ImportError:
        return False, "anthropic package not installed (pip install anthropic)"
    try:
        client = anthropic.Anthropic(api_key=key)
        models = [m.id for m in client.models.list(limit=20).data]
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:160]}"
    return True, f"key works — {len(models)} models reachable"


def available_models() -> list[str]:
    """Read the model list from the user's own key rather than hardcoding."""
    key = get("anthropic_key")
    if not key:
        return []
    try:
        import anthropic

        return [m.id for m in anthropic.Anthropic(api_key=key).models.list(limit=40).data]
    except Exception:
        return []
