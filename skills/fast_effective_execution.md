# Fast, Effective Execution

Use the shortest verified route that can finish the request without weakening
quality, authorization, idempotency, or readback.

## Start

1. Classify the request by outcome and owning lane.
2. Check `config/tool-fast-paths.json` and `config/pipeline-registry.json` only
   for the matching route. Do not scan unrelated tools, repositories, or docs.
3. If one established typed operation already matches the request, call it
   immediately with the exact identifiers and bounds. Do not rediscover its
   implementation first.
4. Reuse verified IDs, reporting windows, and provider receipts throughout the
   job. Resolve each identity once unless authoritative state changes.

## Execute

- Run independent read-only checks in parallel when they do not depend on one
  another.
- For a write: exact read or preview, one idempotent apply, then authoritative
  same-surface readback. Never trade these checks for speed.
- If required evidence is unavailable, do not invent a URL, identifier, amount,
  recipient, route, or completion claim.
- If a tool is genuinely missing, report the exact missing operation once and
  use the tracked owning-lane or supervisor repair route. Do not bounce the task
  repeatedly between agents.
- Do not repeat authentication, capability, documentation, or repository
  discovery after the effective tool inventory already answers the question.

## Model and effort

- Use the configured automatic model selection.
- Simple bounded reads, lookups, formatting, and deterministic summaries may
  use the fast model/effort selected by the navigator.
- Production writes, billing, customer messages, attachments, ambiguous
  identity, tool creation, and multi-system reconciliation require the quality
  model/effort selected for that risk.
- Never lower model quality merely to reduce elapsed time.

## Finish

Return the verified outcome first. Include only evidence, limitations, and next
actions that materially affect the operator. A provider receipt or document
readback proves only what it actually checked; do not describe unverified links,
delivery, or downstream effects as complete.
