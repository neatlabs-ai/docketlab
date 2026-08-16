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

"""Provision citation cleanup.

The extractor was returning things like
`https://www.federalregister.gov/d/2023-27280/p-1375` and `p-146` as cited
provisions. Cosmetically that's a bad chip in the ledger. Substantively it's
worse: the provision field is the join key for the text-diff channel, so junk
here silently breaks the ability to ask "did the section this comment attacked
actually change."

So provisions get validated on the way in rather than trusted.
"""
from __future__ import annotations

import re

# What a real CFR-style citation looks like: 170.14, 170.14(c), 170.14(c)(4),
# 252.204-7012, 4.2(b). Optionally prefixed with a part word we discard.
_CITE = re.compile(
    r"""^\s*(?:§+\s*)?(?:section\s+|sec\.\s*|part\s+)?
        (\d{1,3}\.\d{1,3}(?:[-–]\d{3,4})?      # 170.14  or 252.204-7012
         (?:\([a-z0-9]{1,4}\))*                # (c)(4)
        )\s*$""",
    re.I | re.X,
)

# Things that look like citations but are not: Federal Register page anchors,
# URLs, bare page numbers, and the FR's own paragraph ids.
_REJECT = re.compile(r"^(https?://|www\.|p-\d+$|page\s|\d{4,}$)", re.I)

# Named standards worth keeping even though they aren't CFR sections.
_NAMED = re.compile(
    r"^(NIST\s+SP\s+800-\d+[A-Za-z0-9.\- ]*|DFARS\s+252[\d.\-]+|"
    r"FAR\s+52[\d.\-]+|DoD\s+Manual\s+\d[\d.]*|CMMC\s+Level\s+[123][\w ]*)$",
    re.I,
)

MAX_LEN = 60


def clean(raw) -> list[str]:
    """Normalize a model-supplied provision list. Drops anything unrecognizable."""
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        v = item.strip().strip(",;")
        v = re.sub(r"\s+", " ", v)
        if not v or len(v) > MAX_LEN or _REJECT.match(v):
            continue
        m = _CITE.match(v)
        if m:
            val = m.group(1)
        elif _NAMED.match(v):
            val = v
        else:
            continue
        if val not in out:
            out.append(val)
    return out[:8]


def section_of(provision: str) -> str | None:
    """The bare section a citation belongs to: 170.14(c)(4) -> 170.14."""
    m = re.match(r"^(\d{1,3}\.\d{1,3})", provision or "")
    return m.group(1) if m else None
