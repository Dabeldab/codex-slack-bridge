#!/bin/sh
set -eu

lane="${1:-}"
[ "$lane" = direct_codex ] || { echo "invalid Rory operator lane" >&2; exit 64; }
cd /

secret_root=/run/nova-secrets
for name in \
  github-user-token google-workspace-adc command-center-proxy-token \
  salesforce-client-id salesforce-client-secret salesforce-login-url salesforce-instance-url \
  chargify-api-key chargify-base-url \
  rescue-user rescue-password rescue-base rescue-node-id \
  zoom-oauth-client-id zoom-oauth-client-secret zoom-oauth-refresh-token; do
  test -s "$secret_root/$name" || { echo "required Rory operator credential is unavailable" >&2; exit 78; }
done
test -s /run/nova-cloud-identity/access-token || { echo "Rory's Google Cloud token is unavailable" >&2; exit 78; }

export SCOPED_AGENT_LANE=direct_codex
export GCP_RORY_ACCESS_TOKEN_PATH=/run/nova-cloud-identity/access-token
export RORY_GITHUB_USER_TOKEN_PATH="$secret_root/github-user-token"
export RORY_GOOGLE_WORKSPACE_ADC_PATH="$secret_root/google-workspace-adc"
export RORY_COMMAND_CENTER_TOKEN_PATH="$secret_root/command-center-proxy-token"
export RORY_OPERATOR_JOURNAL_PATH=/var/lib/nova/broker/cloud/operator-writes.jsonl
export SALESFORCE_USE_CLIENT_CREDENTIALS=true
export SALESFORCE_CLIENT_ID="$(cat "$secret_root/salesforce-client-id")"
export SALESFORCE_CLIENT_SECRET="$(cat "$secret_root/salesforce-client-secret")"
export SALESFORCE_LOGIN_URL="$(cat "$secret_root/salesforce-login-url")"
export SALESFORCE_INSTANCE_URL="$(cat "$secret_root/salesforce-instance-url")"
export CHARGIFY_API_KEY="$(cat "$secret_root/chargify-api-key")"
export CHARGIFY_BASE_URL="$(cat "$secret_root/chargify-base-url")"
export RESCUE_USER="$(cat "$secret_root/rescue-user")"
export RESCUE_PASS="$(cat "$secret_root/rescue-password")"
export RESCUE_BASE="$(cat "$secret_root/rescue-base")"
export RESCUE_GROUP_NODE_ID="$(cat "$secret_root/rescue-node-id")"
export ZOOM_OAUTH_CLIENT_ID="$(cat "$secret_root/zoom-oauth-client-id")"
export ZOOM_OAUTH_CLIENT_SECRET="$(cat "$secret_root/zoom-oauth-client-secret")"
export ZOOM_OAUTH_REFRESH_TOKEN="$(cat "$secret_root/zoom-oauth-refresh-token")"
export ZOOM_OAUTH_STATE_PATH=/var/lib/nova/broker/zoom/oauth.env
export ZOOM_OAUTH_SHARED_STATE=true

exec /opt/nova/venv/bin/python -m scoped_operations_mcp.operator_services_server
