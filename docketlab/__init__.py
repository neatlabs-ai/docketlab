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

"""DOCKETLAB - local-first federal rulemaking comment analysis.

Console output is forced to UTF-8 on import. The Windows console defaults to
cp1252, which cannot encode an arrow or an em dash, so a single decorative
character in a progress line kills the whole run with a UnicodeEncodeError —
and only on Windows, and only when output goes to a terminal rather than a
browser. `errors="replace"` means an unmappable character degrades to a
placeholder instead of aborting an hour-long ingest.
"""
import sys as _sys

for _stream in ("stdout", "stderr"):
    _s = getattr(_sys, _stream, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
__version__ = "0.8.0"
