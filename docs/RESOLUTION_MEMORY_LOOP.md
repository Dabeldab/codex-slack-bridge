# Resolution memory and read-only playbook loop

Durable, Firestore-backed learning for the Cloud Run Command Center. Ported from
the Hermes G14 profile (`nova_vector_memory` recall, curator lifecycle). Code:
`src/codex_slack_bridge/resolution_memory.py`.

| Step | Where | What happens |
| --- | --- | --- |
| Recall | `run_ticket_recon_batch` | Similar closed resolutions and live playbooks for the same lane are appended to the proactive investigation prompt as read-only evidence. Served playbook ids are stored on the ticket doc (`reconPlaybookIds`). |
| Capture | board refresh (`_learn_from_board_refresh`) | A ticket that leaves the open board with a completed investigation becomes one redacted `resolutions` doc. Account, contact, owner names, emails, phones and long numbers are scrubbed. |
| Playbook | same refresh | 3+ distinct closed tickets with the same issue pattern and recurring diagnostic lines draft a `playbooks` doc in `canary`. 2 clean closes of tickets it informed promote it to `active`. |
| Rollback | same refresh | A captured ticket that reopens is marked `reopened`; a canary is rolled back on 1 strike, an active playbook on 2. Rolled-back guidance returns only after 3 more supporting tickets. |
| Lifecycle | same refresh | Live playbooks go `stale` after 30 idle days and `archived` after 90. |

Guarantees:

- Playbooks are guidance text only. They have no capability, tool or approval
  field, and write-shaped lines (refund, update, close, send, ...) are filtered
  out. Nothing here changes agent permissions or the capability contract.
- Every method is fail-safe: a Firestore error degrades to a no-op and never
  blocks an investigation or a board refresh.
- Disable with `resolution_memory_enabled: false`. Without Firestore it is off.

Also in this change: `disabled_capability_surfaces` / `disabled_skills` config
keys. The production overlay uses them to retire Gmail (no token is mounted and
all mailbox watchers are off) from the three active lanes' capability summary
and skills, without touching the legacy local configs.
