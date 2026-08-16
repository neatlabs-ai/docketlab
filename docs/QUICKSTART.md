# Quickstart

## 1. Install

```bash
pip install -r requirements.txt
```

The two heavy optional pieces can wait. `sentence-transformers` pulls torch
(~2GB) and is only needed for the better embedding backend; `anthropic` is only
needed for the two analysis stages. Everything else runs without them.

## 2. Verify the install — no keys, no network

```bash
python -m docketlab fixture
```

Eight checks. Seven should read `1.0`. `paraphrase_caught_by_minhash` should
read `0.0` — that one is a demonstration, not a failure. See
[CONTRIBUTING.md](../CONTRIBUTING.md).

## 3. Launch

```bash
python -m docketlab serve
```

Windows: run `LAUNCH_DOCKETLAB.bat`. If the port is taken (Windows error 10013
usually means Hyper-V reserved it), set `DL_PORT` and relaunch.

## 4. Keys

**Settings** tab. Both have Test buttons.

- regulations.gov — free at <https://api.data.gov/signup/>. 1,000 requests/hour.
- Anthropic — only for argument extraction and adjudication.

Keys are saved outside the source tree, never logged, and only the last four
characters are ever sent back to the browser.

## 5. First real docket

**Dockets** tab → `DOD-2023-OS-0063` → **Check size** → **Pull comments**.

~361 comments, roughly 20 minutes, fits inside one hourly quota. Then:

**Find campaigns** → **Cluster** → **Load final rule** → **Diff rule text** →
**Extract arguments** → **Link outcomes**

Read it on **Ledger**, measure it on **Metrics**, then **Download report**.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `DL_HOME` | `~/DOCKETLAB_DATA` | Where the database, raw payloads, and attachments live |
| `DL_PORT` | `7910` | Console port |
| `DL_REGS_KEY` | `DEMO_KEY` | Overrides the saved regulations.gov key |
| `ANTHROPIC_API_KEY` | — | Overrides the saved Anthropic key |
| `DL_REQS_PER_HOUR` | `950` | Self-throttle ceiling |
| `DL_NEARDUP` | `0.85` | MinHash near-duplicate threshold |
| `DL_MINCLUSTER` | `3` | Minimum semantic cluster size |

Environment variables win over saved settings, which keeps scripted runs
reproducible.

## CLI

```bash
python -m docketlab fixture                    # build + run + score
python -m docketlab pipeline DOD-2023-OS-0063  # everything, end to end
python -m docketlab report DOD-2023-OS-0063    # standalone HTML
python -m docketlab serve                      # console
```
