<!-- AgentChat/coding_agent 2026-07-10T18:20:00-04:00 -->

# Agent Tool Runbooks

This secret-free index is the cached starting point for live service work. Read
only the card relevant to the current task. Do not rediscover a service from a
browser when a connector, MCP tool, native API, established client, or CLI can
do the work.

Required order: purpose-built MCP/app connector, native service API or
established application client, trusted CLI/local helper, browser only for a
confirmed UI-only operation or documented API limitation.

A verified user task is authorization for the exact mutation it requests. It
does not authorize unrelated writes. Do not ask for a second confirmation or a
magic approval word. Every mutation needs independent readback before it is
reported complete; after a timeout, read before retrying.

| Service | Runbook | Primary lanes |
| --- | --- | --- |
| Gmail / Taylor email watch | `docs/agent-tools/gmail.md` | Taylor / coding |
| Nova OpenAPI (typed read-only) | `docs/agent-tools/nova-openapi.md` | Alex, Jamie, Taylor |
| Nova SQL, guarded account copy, and table recovery | `docs/agent-tools/nova-sql.md` | Reads: Alex, Jamie, Taylor; writes: Taylor |
| Nova invoice spare and minimum-price deep diagnosis | `docs/agent-tools/nova-invoice-spare.md` | Alex, Jamie, Taylor |
| Chargify / Maxio | `docs/agent-tools/chargify-maxio.md` | Jamie / billing, Taylor / coding |
| Salesforce | `docs/agent-tools/salesforce.md` | Alex / tickets, Jamie / billing, Taylor / coding |
| Zoom | `docs/agent-tools/zoom.md` | Taylor / coding and Alex / tickets; Thor has only the separate fixed-roster quality readers |
| Google Cloud and GitHub | `docs/agent-tools/google-cloud.md` | Rory / direct, operator-only full cloud runtime |
| LogMeIn Rescue | `docs/agent-tools/logmein-rescue.md` | Alex / tickets and Thor / support quality, read-only |
| Support quality | `docs/agent-tools/support-quality.md` | Thor, fixed-roster Zoom and exact four-tool Rescue reads only |
| Pasted screenshots / image vision | `docs/agent-tools/image-attachments.md` | All Command Center agents |
| Receive, edit, create, and return files | `docs/agent-tools/agent-file-delivery.md` | All agent lanes |

Credential values stay in connected tools, environment files, or the secure
vault. Runbooks may name variables and paths but must never contain values.
