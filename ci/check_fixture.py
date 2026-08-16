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

"""The eight ground-truth checks, asserted rather than eyeballed.

Runs the fixture pipeline in-process and compares every score against its
expected value. Note that `paraphrase_caught_by_minhash` is expected to be 0.0:
lexical hashing genuinely cannot see a campaign whose members each reworded the
same talking points, and a change that made it pass would mean the check had
stopped measuring anything. That is why it is asserted, not merely printed.
"""
import sys
from pathlib import Path

# Running `python ci/check_x.py` puts ci/ on sys.path, not the repository root,
# so the package would not import. Add the root explicitly rather than relying
# on the caller's working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docketlab import dedup, fixtures, linkage, semantic, store

EXPECTED = {
    "exact_campaign_caught": 1.0,
    "near_campaign_caught": 1.0,
    "near_inserts_recovered": 1.0,
    "paraphrase_caught_by_minhash": 0.0,      # by design — see the docstring
    "paraphrase_grouped_by_embedding": 1.0,
    "substantive_not_swept_into_campaign": 1.0,
    "answered_linked": 1.0,
    "unanswered_correctly_unlinked": 1.0,
}


def main() -> int:
    store.init()
    fixtures.build()
    dedup.run(fixtures.DOCKET)
    semantic.cluster(fixtures.DOCKET)
    linkage.run(fixtures.DOCKET, adjudicate=False)
    scores = fixtures.score()

    bad = {k: (scores.get(k), v) for k, v in EXPECTED.items() if scores.get(k) != v}
    if bad:
        for key, (got, want) in bad.items():
            print(f"FAIL {key}: got {got}, expected {want}")
        return 1

    print(f"OK fixture {len(EXPECTED)}/{len(EXPECTED)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
