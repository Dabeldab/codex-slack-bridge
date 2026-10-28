# Nova Command Center — Agent Tool-Stack Smoke Tests
# Purpose: verify each production agent's `scoped_operations_mcp` broker answers live
# after the IAP login is unblocked. Every task is READ-ONLY and scoped strictly to
# that agent's permitted operations (agent-capabilities.yaml) so no capability
# contract is tripped and no production mutation occurs.
#
# Use: once signed into https://nova-command-center-shadow-3qcpmfwo7a-uc.a.run.app,
# dispatch each prompt via /agent-chat/send to the named agent (payload: {"agent": "<name>", "prompt": "..."}).
# Then check /jobs?limit=5 and /usage for the job's usage blob.

---
## 1) ALEX — tickets_agent
## Broker under test: scoped_operations_mcp.salesforce_server (salesforce_support_ops)
## Permitted ops exercised: salesforce.ticket.read, salesforce.account_360.read,
##                          salesforce.ticket_board.read_all_record_types, nova_sql.read/bounded_select
## Verify: returns a real support ticket (Nova Classic/Support record type), NOT test/demo/template.

Agent: Alex
Prompt:
"Ignore any default behavior. We are smoke-testing the Salesforce tool broker. Do NOT
make any writes. Run a READ-ONLY check: list the most recent 5 open Nova support tickets
(Nova Classic / Nova Wave support record type, excluding accounts named test/demo/template),
and for the single most recent one return its ticket number, subject, account name, and status.
If the Salesforce or Nova SQL read tools are unavailable, say exactly 'BROKER_UNAVAILABLE'
and list which tools you tried to call. Otherwise return a short result and confirm the tool
used. Do not create, update, post chatter, or email anything."

---
## 2) JAMIE — billing_agent
## Broker under test: scoped_operations_mcp.maxio_server (maxio_billing_ops)
## Permitted ops exercised: salesforce.billing_account.read, maxio.read, nova_billing.locations.read_authoritative
## Verify: returns a real subscription/location from the billing source of truth, read-only.

Agent: Jamie
Prompt:
"Ignore any default behavior. We are smoke-testing the Maxio/Chargify billing broker. Do NOT
make any writes. Run a READ-ONLY check: pick one active billing account shown in Salesforce
(billing record type, not test/demo/template) and return its Chargify/Maxio subscription id,
the subscription status, and the total locations count as Maxio reports it. If the Maxio or
Chargify read tools are unavailable, say exactly 'BROKER_UNAVAILABLE' and list which tools you
tried to call. Otherwise return a short result and confirm the tool used. Do not cancel, refund,
credit, change cards, or modify anything."

---
## 3) TAYLOR — coding_agent
## Broker under test: scoped_operations_mcp.cloud_ops_server (gcp_github_ops)
## Permitted ops exercised: github.read, gcp.read, salesforce.ticket.read, nova_sql.read
## Verify: returns a real GitHub/GCP read, read-only.

Agent: Taylor
Prompt:
"Ignore any default behavior. We are smoke-testing the GCP/GitHub tool broker. Do NOT make
any writes, do NOT open PRs, do NOT push. Run a READ-ONLY check: list the branches of the
repository dariusmakesstuff/codex-slack-bridge and report the latest commit short-sha on
origin/main, OR list the running Cloud Run services in project gen-lang-client-0051653266
region us-central1. If the GitHub or GCP read tools are unavailable, say exactly
'BROKER_UNAVAILABLE' and list which tools you tried to call. Otherwise return a short result
and confirm the tool used. No writes, no merges, no deploys."

---
## Expected good result
# Each agent returns a real artifact (ticket / subscription / branch-or-service) and the
# name of the broker tool it used. If any returns BROKER_UNAVAILABLE, that broker failed to
# start in the Cloud Run container despite the package being installed — that's the gap to fix.

## How to confirm usage capture
# After each dispatch: GET /jobs?limit=5 (per-job usage field) and GET /usage (per-agent totals).