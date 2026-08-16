# Publishing checklist

Delete this file before making the repository public — it's for you, not readers.

## 1. Clean the working folder

```powershell
Remove-Item -Recurse -Force docketlab\__pycache__ -ErrorAction SilentlyContinue
Remove-Item probe.py -ErrorAction SilentlyContinue
```

`.gitignore` already excludes `DOCKETLAB_DATA/`, `settings.json`, `prices.json`,
`watchlists.json`, `starters.json`, and `probe.py` — but confirm before the first
commit. **`settings.json` holds your API keys in plaintext.** After `git add .`,
run `git status` and make sure it isn't listed.

## 2. Screenshots

Three images into `docs/img/` — see `docs/img/README.md` for what each should
show. Take them after re-running **Extract arguments**, so provision chips are
clean. Without them the README shows broken image links.

## 3. Push to a PRIVATE repo first

```bash
git init
git add .
git status              # verify no settings.json, no DOCKETLAB_DATA
git commit -m "DOCKETLAB v0.7.0"
git branch -M main
git remote add origin https://github.com/neatlabs-ai/docketlab.git
git push -u origin main
```

## 4. Let CI run once

Actions tab. Six jobs: Ubuntu and Windows across Python 3.11, 3.12, 3.13. It runs
the fixture's eight ground-truth checks, the adversarial suite, and a render pass
over every route.

The workflow has never executed on GitHub's runners — expect at least one
platform difference. Fix what it finds. **Do not make the repo public with a red
badge**; the README's whole argument is rigor.

## 5. Then go public

Settings → General → Change visibility.

Add repository topics so it's findable: `regulations-gov`, `federal-register`,
`rulemaking`, `public-comments`, `administrative-law`, `govtech`, `civic-tech`,
`notice-and-comment`.

Set the description to:
> What did the agency actually do with the public comments? Local-first analysis
> of federal rulemaking dockets.

## 6. Tag the release

```bash
git tag -a v0.7.0 -m "DOCKETLAB v0.7.0"
git push origin v0.7.0
```

## What to say when you announce it

Lead with the finding, not the tool. The 66% response rate on CMMC, the three
silent grants recovered from what looked like non-engagement, and the cost —
roughly a dollar in tokens for 369 comments — are the interesting parts. The
software is how you got there.

Be first to state the limitation: one agency validated, and the parser tells you
when it doesn't understand a preamble. People trust a tool that publishes its own
boundaries more than one that doesn't mention them.
