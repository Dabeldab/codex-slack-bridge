#!/bin/sh
set -eu

secret_root=/run/nova-secrets
for name in github-app-id github-app-installation-id github-app-private-key; do
  test -s "$secret_root/$name" || { echo "required GitHub App credential is unavailable" >&2; exit 78; }
done

export REASONING_RELAY_REPOSITORY=dariusmakesstuff/codex-slack-bridge
export REASONING_RELAY_BRANCH=reasoning-relay-bus
export GITHUB_APP_ID_PATH="$secret_root/github-app-id"
export GITHUB_APP_INSTALLATION_ID_PATH="$secret_root/github-app-installation-id"
export GITHUB_APP_PRIVATE_KEY_PATH="$secret_root/github-app-private-key"
export GITHUB_ALLOWED_REPOSITORIES=dariusmakesstuff/codex-slack-bridge
export PATH=/usr/local/bin:/usr/bin:/bin
cd /

exec /opt/nova/venv/bin/python -m codex_slack_bridge.reasoning_relay_broker
