#!/bin/sh
set -eu

: "${CREDENTIALS_DIRECTORY:?systemd credentials are required}"
install -d -m 0700 /var/lib/nova/gmail /run/nova-runtime/relay-readiness
install -m 0600 "$CREDENTIALS_DIRECTORY/gmail-oauth-token" /var/lib/nova/gmail/token.json
export SLACK_BOT_TOKEN="$(cat "$CREDENTIALS_DIRECTORY/slack-bot-token")"
export BRIDGE_CONFIG=/opt/nova/current/config/agents.chatgpt-runtime.yaml
export COMMAND_CENTER_HOST="${COMMAND_CENTER_HOST:-127.0.0.1}"
export COMMAND_CENTER_PORT="${COMMAND_CENTER_PORT:-17866}"
export COMMAND_CENTER_DISABLE_WATCHERS="${COMMAND_CENTER_DISABLE_WATCHERS:-1}"
export COMMAND_CENTER_TRUSTED_BEARER_PATH=/run/nova-runtime/command-center-proxy.token
export NOVA_AGENT_RUNTIME_MODE=primary
export REASONING_RELAY_ENABLED=1
export REASONING_RELAY_REPOSITORY=dariusmakesstuff/codex-slack-bridge
export REASONING_RELAY_BRANCH=reasoning-relay-bus
export REASONING_RELAY_BROKER_COMMAND="/usr/bin/sudo -n -H -u nova-cloud-broker -- /opt/nova/bin/run-reasoning-relay-broker"
# AgentProviderReadiness only needs non-secret configuration markers. The real
# GitHub App files remain readable solely by nova-cloud-broker.
for marker in app-id installation-id private-key; do
  : > "/run/nova-runtime/relay-readiness/$marker"
  chmod 0400 "/run/nova-runtime/relay-readiness/$marker"
done
export GITHUB_APP_ID_PATH=/run/nova-runtime/relay-readiness/app-id
export GITHUB_APP_INSTALLATION_ID_PATH=/run/nova-runtime/relay-readiness/installation-id
export GITHUB_APP_PRIVATE_KEY_PATH=/run/nova-runtime/relay-readiness/private-key
export GITHUB_ALLOWED_REPOSITORIES=dariusmakesstuff/codex-slack-bridge
export PATH=/usr/local/bin:/usr/bin:/bin

exec /opt/nova/venv/bin/python -m codex_slack_bridge.command_center_server
