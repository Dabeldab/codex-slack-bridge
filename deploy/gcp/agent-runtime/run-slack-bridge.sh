#!/bin/bash
set -euo pipefail

export CREDENTIALS_DIRECTORY=/run/credentials/nova-runtime
install -d -m 0700 /run/nova-runtime/relay-readiness
export SLACK_BOT_TOKEN="$(cat "$CREDENTIALS_DIRECTORY/slack-bot-token")"
export BRIDGE_CONFIG=/opt/nova/current/config/agents.chatgpt-runtime.yaml
export REASONING_RELAY_ENABLED=1
export REASONING_RELAY_REPOSITORY=dariusmakesstuff/codex-slack-bridge
export REASONING_RELAY_BRANCH=reasoning-relay-bus
export REASONING_RELAY_BROKER_COMMAND="/usr/bin/sudo -n -H -u nova-cloud-broker -- /opt/nova/bin/run-reasoning-relay-broker"
for marker in app-id installation-id private-key; do
  : > "/run/nova-runtime/relay-readiness/$marker"
  chmod 0400 "/run/nova-runtime/relay-readiness/$marker"
done
export GITHUB_APP_ID_PATH=/run/nova-runtime/relay-readiness/app-id
export GITHUB_APP_INSTALLATION_ID_PATH=/run/nova-runtime/relay-readiness/installation-id
export GITHUB_APP_PRIVATE_KEY_PATH=/run/nova-runtime/relay-readiness/private-key
export GITHUB_ALLOWED_REPOSITORIES=dariusmakesstuff/codex-slack-bridge
export PATH=/usr/local/bin:/usr/bin:/bin

# Provider-system credentials stay broker-side. The reasoning provider is ChatGPT Work.
exec /opt/nova/venv/bin/python -m codex_slack_bridge.app
