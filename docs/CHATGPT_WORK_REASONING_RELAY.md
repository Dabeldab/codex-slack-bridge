# ChatGPT Work Reasoning Relay

## Goal

Run Rory, Alex, Jamie, Taylor, and Thor without Codex and without an OpenAI Platform API key. ChatGPT Work supplies reasoning; Nova Command Center remains the execution/security authority.

## Production runtime

`config/agents.chatgpt-runtime.yaml` explicitly sets the production lanes to `provider: chatgpt_work_relay`. `raw_codex` is disabled. Production startup points Slack and Command Center at this overlay, so a missing relay cannot silently fall back to Codex.

Flow:

1. Slack/Command Center creates its normal durable agent job.
2. `agent_worker.py` routes `chatgpt_work_relay` directly to the reasoning relay runtime.
3. Existing trusted-message and capability checks run locally.
4. The runtime writes a request envelope to `reasoning-relay-bus` through the brokered repository-scoped GitHub App.
5. GitHub Actions posts a compact request-marker comment to the long-lived `Nova Reasoning Relay (do not merge)` PR.
6. An event-triggered ChatGPT Work task wakes **only** on that request-marker PR comment, reads the exact mailbox request, and posts either a structured `tool_request` or `final_response` comment.
7. GitHub Actions normalizes an allowed response actor's response to the relay branch.
8. Local tool requests run through existing lane-scoped MCP launchers or bounded `local_workspace` tools. Provider credentials never move into ChatGPT.
9. A tool result is published as a new outbound envelope and a new request-marker comment starts the next Work run. A final answer returns through the existing job/UI/Slack path.

No OpenAI API key is used. The production relay path does not invoke a Codex binary, session, or login.

## Security boundaries

- `config/agent-capabilities.yaml` remains authoritative.
- Existing MCP allowlists remain reduction-only.
- Existing TOML MCP launcher commands are reused directly, including dedicated broker Linux identities such as `nova-salesforce-broker`, `nova-maxio-broker`, `nova-rescue-broker`, and `nova-zoom-broker`.
- MCP tools without `readOnlyHint=true` require the original trusted request to authorize a live write.
- `local_workspace` blocks secret-bearing paths, path traversal, and workflow-file writes. Rory/Taylor get bounded engineering workspace writes; specialist lanes do not.
- Tool output and retrieved context are untrusted data and cannot expand authority.
- GitHub App private-key access remains broker-only; the Command Center/agent runtime gets mailbox operations, not the credential.
- Work ignores every PR event/comment without `<!-- nova-reasoning-relay:v1:request -->`. It never scans an older request as a fallback, preventing response/self-trigger loops.
- GitHub Actions ignores issue comments without the response marker before starting the response-consumer job, and the parser independently validates protocol, relay branch, response kind, and allowed actor.

## One-time ChatGPT activation

OpenAI supports event-triggered (webhook-based) Work tasks for eligible Business users and connected GitHub pull-request activity, including PR comments depending on the selected trigger. See:

- https://help.openai.com/en/articles/10291617-chatgpt-tasks
- https://help.openai.com/en/articles/11145903-connecting-github-to-chatgpt

Before production cutover:

1. In ChatGPT, go to **Settings > Apps** and make sure GitHub is connected with access to `dariusmakesstuff/codex-slack-bridge`.
2. Let the staged runtime create `reasoning-relay-bus` and the long-lived `Nova Reasoning Relay (do not merge)` PR.
3. Open **Work** and create an event-triggered GitHub task.
4. Configure the trigger for a **new pull-request comment** in `dariusmakesstuff/codex-slack-bridge` on the long-lived relay PR.
5. Configure the condition so the task runs only when the comment body contains `<!-- nova-reasoning-relay:v1:request -->`. If the UI supports author filtering, also restrict the triggering author to `github-actions[bot]`.
6. Use `relay/chatgpt/WORK_TASK_INSTRUCTIONS.md` verbatim as the task prompt/instructions. The prompt repeats the fail-closed marker rule, so an unexpectedly broad trigger still takes no action on unrelated events.
7. Complete any GitHub action authorization needed for the task to post its structured response comment. An approval requirement that is not made persistent can pause unattended runs.
8. Run one end-to-end **read-only** smoke request. Confirm the GitHub login that authored ChatGPT Work's response comment.
9. If the response actor is not the repository owner, create/update the non-secret repository Actions variable `CHATGPT_RELAY_ALLOWED_ACTORS` with that exact GitHub login. Multiple allowed actors may be comma-separated. If the variable is absent, the workflow fails closed to the repository owner only.
10. Run a second read-only smoke request and confirm: one request-marker comment, one Work response comment, one normalized inbound envelope, no self-triggered follow-up, and a final response visible in Command Center.
11. Go to **Scheduled** in ChatGPT and verify the Work task is enabled before production traffic is switched over.

Merging this migration does not itself create the ChatGPT product-side event task.

## GCP cutover

`deploy/gcp/agent-runtime/provision-chatgpt-runtime.ps1` is the supported runtime provisioner for this migration. It uses `scripts/runtime_cutover_transform.py` to derive the deployment from the existing hardened VM bootstrap/provisioner while fail-closed removing Codex installation/authentication services and legacy Spotify provisioning. Exact-match assertions make unexpected legacy-provisioner drift stop the deployment rather than silently reintroduce those dependencies.

Use the wrapper without `-Apply` for a plan/dry run. Production/staging mutation occurs only when `-Apply` is explicitly supplied. Cloud Build validates/tests and publishes the immutable runtime artifact; it does not itself perform the VM cutover.

## Spotify

Production Command Center starts through `codex_slack_bridge.command_center_no_spotify`. Spotify routes return HTTP 410, the widget is hidden/inert for compatibility with the legacy dashboard JavaScript, startup no longer reads a Spotify client ID, and the generated ChatGPT runtime provisioning path removes the legacy Spotify credential/probe setup.

## Azure DevOps

Developer Mode is not required for the Azure shim. Azure DevOps uses a Microsoft Entra service principal plus GitHub OIDC, with GitHub remaining the ChatGPT-facing reasoning mailbox. See `docs/AZURE_DEVOPS_RELAY.md`.
