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

"""Every page renders, and the not-yet-ready states say so rather than erroring.

A real file rather than Python embedded in the workflow YAML. Heredocs are a
shell feature and PowerShell has no such thing, so `python - <<'PY'` parses as a
redirection operator on Windows runners and the step dies before Python starts.
Scripts in the repository run identically on every platform, and can be run by
hand while debugging.
"""
import sys
from pathlib import Path

# Running `python ci/check_x.py` puts ci/ on sys.path, not the repository root,
# so the package would not import. Add the root explicitly rather than relying
# on the caller's working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docketlab import dedup, fixtures, semantic, store
from docketlab.server import app


def main() -> int:
    store.init()
    fixtures.build()
    client = app.test_client()

    # Before the pipeline runs there is nothing to report. That is a normal
    # state, not a server error, and it must not return a 500.
    pre = client.get(f"/export?docket={fixtures.DOCKET}").status_code
    if pre != 409:
        print(f"FAIL pre-pipeline export returned {pre}, expected 409")
        return 1

    dedup.run(fixtures.DOCKET)
    semantic.cluster(fixtures.DOCKET)

    expect = {
        "/": 200,
        "/guide": 200,
        "/usage": 200,
        "/dockets": 200,
        "/settings": 200,
        "/watch": 200,
        f"/metrics?docket={fixtures.DOCKET}": 200,
        f"/ledger?docket={fixtures.DOCKET}": 200,
        f"/export?docket={fixtures.DOCKET}": 200,
        "/export": 400,                        # no docket given
        "/ledger?docket=NOPE-9999-0001": 200,  # unknown docket, empty not broken
        "/metrics?docket=NOPE-9999-0001": 200,
    }

    bad = []
    for path, want in expect.items():
        got = client.get(path).status_code
        if got != want:
            bad.append(f"{path} -> {got}, expected {want}")

    if bad:
        for line in bad:
            print(f"FAIL {line}")
        return 1

    print(f"OK {len(expect)} routes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
