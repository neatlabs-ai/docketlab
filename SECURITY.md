# Security

## Reporting a vulnerability

Email **info@neatlabs.ai** with "DOCKETLAB security" in the subject. Please
don't open a public issue.

Include what you can: the version, the affected component, and a way to
reproduce it. We'll acknowledge receipt and keep you updated on the fix.

## Threat model

DOCKETLAB runs locally and holds two things worth protecting: **your API keys**
and **whatever corpus you've pulled**.

- Keys are stored in `settings.json` under your data directory, outside the
  source tree, in plaintext. They are never logged, and the browser only ever
  receives the last four characters. Anyone with read access to your user
  profile can read them — treat that file the way you'd treat any credential on
  disk.
- Nothing is transmitted anywhere except to the APIs you configure:
  regulations.gov, the Federal Register, and Anthropic. There is no telemetry
  and no server component.
- The console binds to `127.0.0.1` only. Do not expose it to a network — it has
  no authentication because it is not designed to have any remote users.

## Untrusted input

Comment text is arbitrary public input from anyone who filed on a docket, and it
flows into a language model prompt. Treat model output as untrusted:
the extraction stage validates provisions against a strict format and discards
anything unrecognized, JSON is parsed defensively, and a malformed response
skips a unit rather than failing a run. Attachment downloads are streamed with a
size ceiling so a single oversized file can't stall a pull.

If you find a way to make crafted comment text change tool behaviour beyond its
own analysis row, that is a vulnerability and we want to hear about it.
