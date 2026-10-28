# Three-agent production runtime

The ChatGPT relay and Cloud Run deployment have exactly three active lanes:

| Display name | Runtime lane | Responsibility |
| --- | --- | --- |
| Taylor | `coding_agent` | Engineering, automation, and approved technical operations |
| Jamie | `billing_agent` | Billing and subscription support |
| Alex | `tickets_agent` | Support tickets and customer investigations |

Thor (`claude_agent`) is disabled. Rory (`direct_codex`) is removed from the active roster. Raw Codex remains disabled. Their historical profiles, audit records, and legacy policy tests are not erased. They are not production workers or fallback agents.

## Enforcement

`defaults.active_agents` in both production relay overlays is applied after configuration inheritance. Inactive agents and their inherited Slack routes are omitted from `BridgeConfig`. Policy validation rejects inactive/disabled providers before loading their capabilities. Direct job submission rejects missing lanes before allocating a job. Nova Control loads the same effective roster, so an old signed outbound request cannot re-enable a retired lane.

Thor's weekly support-quality watcher is forced off when Thor is absent from an explicit roster, even if a parent configuration enables it. The scheduler derives its lanes from the effective inherited configuration. Dashboard assignment choices, voice profiles, animated agent controls, and fallback activity contain only Alex, Jamie, and Taylor. Retired workspace directories are no longer created by the production Dockerfile.

The three active agents retain their existing MCP allowlists and business/security restrictions. Rory's unrestricted operator permissions are not transferred to Taylor or any other agent. Existing Thor/Rory work must not be silently reassigned; an operator should inspect and explicitly reassign any still-relevant tasks. Historical messages are evidence, not runnable assignments.

## Release and verification

The existing `main` -> Cloud Build -> Docker image -> Cloud Run pipeline is unchanged. This consolidation does not fix or bypass any separate OAuth, provider-credential, or infrastructure deployment failure.

Run:

```sh
python -m pytest -q tests/test_active_agent_roster.py tests/test_chatgpt_runtime_capability_contract.py tests/test_nova_control_mcp.py
```

After deployment, verify both Command Center and Nova Control serve the intended revision and their effective roster contains only the three lanes above. Confirm retired-lane direct requests and old mailbox requests are rejected, no quality watcher starts, and an active-agent read-only task still returns to the correct conversation. Check any externally configured Cloud Scheduler jobs separately; pause only jobs exclusively targeting retired agents, not shared sync jobs.

These are logical lanes inside shared services. Removing them stops their new jobs, probes, and scheduled work; it does not by itself reduce the shared Cloud Run CPU/memory allocation or establish a specific billing reduction. No new service or always-on instance is introduced.
