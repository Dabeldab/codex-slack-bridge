#!/bin/sh
set -eu

lane="${1:-}"
case "$lane" in
  tickets_agent|claude_agent) ;;
  *) echo "invalid scoped Rescue lane" >&2; exit 64 ;;
esac
cd /

secret_root=/run/nova-secrets
for name in rescue-user rescue-password rescue-base rescue-node-id; do
  test -s "$secret_root/$name" || { echo "required Rescue broker secret is unavailable" >&2; exit 78; }
done

export RESCUE_USER="$(cat "$secret_root/rescue-user")"
export RESCUE_PASS="$(cat "$secret_root/rescue-password")"
export RESCUE_BASE="$(cat "$secret_root/rescue-base")"
export RESCUE_GROUP_NODE_ID="$(cat "$secret_root/rescue-node-id")"
export RESCUE_NODE_REF=CHANNEL
export RESCUE_VERIFY_SSL=1

exec /opt/nova/venv/bin/python -m rescue_console_mcp.server
