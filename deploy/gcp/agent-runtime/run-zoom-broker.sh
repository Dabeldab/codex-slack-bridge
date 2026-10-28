#!/bin/sh
# AgentChat/coding_agent 2026-08-07T12:14:00Z: preserve shared OAuth state
# when another approved broker owns the rotated file.
set -eu

lane="${1:-}"
case "$lane" in
  direct_codex|billing_agent|coding_agent|tickets_agent|claude_agent) ;;
  *) echo "invalid scoped Zoom lane" >&2; exit 64 ;;
esac
cd /

secret_root=/run/nova-secrets
for name in zoom-s2s-account-id zoom-s2s-client-id zoom-s2s-client-secret; do
  test -s "$secret_root/$name" || { echo "required Zoom broker secret is unavailable" >&2; exit 78; }
done

export SCOPED_AGENT_LANE="$lane"
export ZOOM_ACCOUNT_ID="$(cat "$secret_root/zoom-s2s-account-id")"
export ZOOM_CLIENT_ID="$(cat "$secret_root/zoom-s2s-client-id")"
export ZOOM_CLIENT_SECRET="$(cat "$secret_root/zoom-s2s-client-secret")"
export ZOOM_WEEKLY_SUPPORT_AGENT_ROSTER_FILE=/opt/nova/current/config/zoom-weekly-support-agents.json

# The configured Julio/Wiko automation remains S2S-only and is not used by
# Thor. Other lanes retain those fixed contacts for the existing workflows.
if [ "$lane" != claude_agent ]; then
  for name in \
    zoom-singapore-julio-contact \
    zoom-internal-wiko-contact \
    zoom-team-chat-sender-user-id; do
    test -s "$secret_root/$name" || { echo "required Zoom broker secret is unavailable" >&2; exit 78; }
  done
  export ZOOM_SINGAPORE_JULIO_CONTACT="$(cat "$secret_root/zoom-singapore-julio-contact")"
  export ZOOM_INTERNAL_REQUEST_WIKO_CONTACT="$(cat "$secret_root/zoom-internal-wiko-contact")"
  export ZOOM_TEAM_CHAT_SENDER_USER_ID="$(cat "$secret_root/zoom-team-chat-sender-user-id")"
  export NOVA_INTERNAL_COMMUNICATION_JOURNAL_PATH=/var/lib/nova/broker/internal-comms/verified-requests.jsonl
fi

# Explicit operator messaging, Team Chat history, and the fixed Chat Overview
# use the dedicated user OAuth app in every lane.
for name in \
  zoom-oauth-client-id \
  zoom-oauth-client-secret \
  zoom-oauth-refresh-token; do
  test -s "$secret_root/$name" || { echo "required Zoom user OAuth secret is unavailable" >&2; exit 78; }
done
install -d -m 2770 /var/lib/nova/broker/zoom
chgrp nova-zoom-credentials /var/lib/nova/broker/zoom
state_path=/var/lib/nova/broker/zoom/oauth.env
if [ ! -s "$state_path" ]; then
  umask 0007
  printf 'ZOOM_OAUTH_REFRESH_TOKEN=%s\n' "$(cat "$secret_root/zoom-oauth-refresh-token")" >"$state_path"
  chmod 0660 "$state_path"
fi
test -r "$state_path" && test -w "$state_path" || {
  echo "shared Zoom OAuth state is unavailable" >&2
  exit 78
}
export ZOOM_OAUTH_CLIENT_ID="$(cat "$secret_root/zoom-oauth-client-id")"
export ZOOM_OAUTH_CLIENT_SECRET="$(cat "$secret_root/zoom-oauth-client-secret")"
export ZOOM_OAUTH_REFRESH_TOKEN="$(cat "$secret_root/zoom-oauth-refresh-token")"
export ZOOM_OAUTH_STATE_PATH="$state_path"
export ZOOM_OAUTH_SHARED_STATE=true

exec /opt/nova/venv/bin/python -m scoped_operations_mcp.zoom_server
