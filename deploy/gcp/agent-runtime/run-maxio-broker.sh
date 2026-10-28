#!/bin/sh
set -eu

lane="${1:-}"
case "$lane" in
  coding_agent|billing_agent) ;;
  *) echo "invalid scoped Maxio lane" >&2; exit 64 ;;
esac

# Keep the secret-bearing broker outside the invoking model user's workspace.
cd /

secret_root=/run/nova-secrets
for name in chargify-api-key chargify-base-url; do
  test -s "$secret_root/$name" || { echo "required Maxio broker secret is unavailable" >&2; exit 78; }
done

export SCOPED_AGENT_LANE="$lane"
export CHARGIFY_API_KEY="$(cat "$secret_root/chargify-api-key")"
export CHARGIFY_BASE_URL="$(cat "$secret_root/chargify-base-url")"
export MAXIO_OPERATION_JOURNAL_PATH="/var/lib/nova/broker/maxio/operations.jsonl"
export MAXIO_REPORT_OUTPUT_DIR="/var/lib/nova/broker/maxio-reports"

exec /opt/nova/venv/bin/python -m scoped_operations_mcp.maxio_server
