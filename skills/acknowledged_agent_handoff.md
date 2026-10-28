# Acknowledged Agent Handoff

Use this workflow when another specialist lane must continue the same operator
request, ticket, or repair.

1. Finish every safe step owned by the current lane. Preserve the original
   authority, exact targets, evidence, limits, ticket number, and idempotency
   boundary.
2. Emit one final-line `TAYLOR_HANDOFF_REQUEST` JSON object to the exact owning
   specialist: `coding_agent`, `tickets_agent`, `billing_agent`, or
   `claude_agent` when its support-quality contract applies. Attach only files
   the receiving lane actually needs and omit `attachmentPaths` otherwise.
3. Never target Rory, `direct_codex`, or `raw_codex`. Rory is operator-only
   ingress and cannot receive agent communication, tool-repair requests, or
   return handoffs. Never ask Darius to relay the work.
4. A handoff counts as received only when Command Center returns the named
   receiving agent, `received and acknowledged`, and the durable child job ID.
   Queue acceptance is not business completion.
5. Keep the source obligation active until the terminal child receipt returns.
   If a distinct specialist step remains, make one new bounded acknowledged
   handoff from the current owner.
6. Route a missing typed operation or runtime repair to `coding_agent`. Use
   Needs Review only for a concrete business decision that authoritative data
   cannot answer after safe discovery and repair paths are exhausted.

If attachment staging rejects a file, omit a nonessential file or return a
supported deliberate deliverable from the source workspace. Do not abandon the
underlying task or convert the failed attachment into a Rory handoff.
