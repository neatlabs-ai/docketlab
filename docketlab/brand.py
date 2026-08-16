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

"""NEATLABS™ identity, in one place.

Kept as constants rather than scattered through templates so the wordmark,
contact, and attribution stay consistent across the console, the exported
report, and anything generated later.
"""

ORG = "NEATLABS"
ORG_TM = "NEATLABS\u2122"
LEGAL = "Security 360, LLC DBA NEATLABS\u2122"
PRODUCT = "DOCKETLAB"
TAGLINE = "public comment adjudication"
POSITIONING = "Tech for Civic Good"

SITE = "neatlabs.ai"
EMAIL = "info@neatlabs.ai"
REPO = "https://github.com/neatlabs-ai/docketlab"
GITHUB_ORG = "https://github.com/neatlabs-ai"

VERSION = "0.7.3"
LICENSE = "Apache-2.0"

# Required by the regulations.gov API terms of use. Kept verbatim.
API_ATTRIBUTION = (
    "This product uses the Regulations.gov Data API but is neither endorsed "
    "nor certified by Regulations.gov."
)

MISSION = (
    "Federal agencies must respond to significant public comments. DOCKETLAB "
    "measures whether they do \u2014 and makes the answer checkable by anyone, "
    "from public data, on their own machine."
)

# The design rules the tool is built to. Surfaced in the UI and the report so
# the constraints travel with the numbers.
DOCTRINE = [
    ("Absent is not zero",
     "An unparsed preamble is unknown, not unanswered."),
    ("Collapsing is display, never deletion",
     "Campaign members keep their rows; counts always report true submissions."),
    ("Everything walks back",
     "Every figure traces to a comment ID, and every comment ID to a public document."),
    ("Zero custody",
     "Runs entirely on your machine. No corpus, no keys, and no analysis leave it."),
    ("Two channels, not one",
     "A comment succeeds by drawing a response or by moving the text. Score both."),
]
