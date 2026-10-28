# Agent Runtime Operations

Use for bridge health, queue, scheduler, session, pause, restart, and recovery work.

- Read `GET /runtime/status` and `GET /runtime/scheduler/status` before acting.
- Treat scheduler membership, live process locks, recent sessions, job files, and
  the restart manifest as evidence; do not trust an old SQLite status alone.
- Pause through `POST /runtime/pause` before restart. Wait for in-flight work to
  finish when possible; capture queued work in the manifest.
- Restart only the intended bridge process using ordinary OS process controls.
  Do not suspend processes, inject code, use obfuscation, or bypass security tools.
- Verify readiness, auto-resume state, queue counts, running lanes, and manifest
  completion after restart.
- Interrupted external writes require readback before replay.
