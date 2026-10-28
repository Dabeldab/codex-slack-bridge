#!/bin/sh
set -eu

lane="${1:-}"
case "$lane" in
  direct_codex|coding_agent|tickets_agent|billing_agent|claude_agent) ;;
  *) echo "invalid scoped Salesforce lane" >&2; exit 64 ;;
esac

# Codex starts stdio MCP processes from the model user's workspace.  The
# broker identity intentionally cannot traverse that workspace, so move to a
# neutral directory before Python performs any relative fallback checks.
cd /

secret_root=/run/nova-secrets
for name in salesforce-client-id salesforce-client-secret salesforce-login-url salesforce-instance-url; do
  test -s "$secret_root/$name" || { echo "required Salesforce broker secret is unavailable" >&2; exit 78; }
done

export SCOPED_AGENT_LANE="$lane"
export SALESFORCE_USE_CLIENT_CREDENTIALS=true
export SALESFORCE_CLIENT_ID="$(cat "$secret_root/salesforce-client-id")"
export SALESFORCE_CLIENT_SECRET="$(cat "$secret_root/salesforce-client-secret")"
export SALESFORCE_LOGIN_URL="$(cat "$secret_root/salesforce-login-url")"
export SALESFORCE_INSTANCE_URL="$(cat "$secret_root/salesforce-instance-url")"
export SALESFORCE_OPERATION_JOURNAL_PATH=/var/lib/nova/broker/salesforce/operations.jsonl
export NOVA_INTERNAL_COMMUNICATION_JOURNAL_PATH=/var/lib/nova/broker/internal-comms/verified-requests.jsonl
export SALESFORCE_SUPPORT_EMAIL_TICKET_CREATED_BY="Darius Parlor"
export NOVA_SQL_DRIVER="ODBC Driver 18 for SQL Server"
export NOVA_SQL_WRITE_STATE_DIR=/var/lib/nova/broker/sql-write
if [ "$lane" = coding_agent ]; then
  test -s "$secret_root/pos-main-api-cohort-ro" || {
    echo "required Taylor API cohort credential is unavailable" >&2
    exit 78
  }
  for name in novapos-developer-username novapos-developer-password; do
    test -s "$secret_root/$name" || {
      echo "required fixed Nova developer broker credential is unavailable" >&2
      exit 78
    }
  done
  export NOVA_POS_MAIN_API_COHORT_CREDENTIAL_FILE="$secret_root/pos-main-api-cohort-ro"
  export NOVA_SQL_DEVELOPER_USERNAME_FILE="$secret_root/novapos-developer-username"
  export NOVA_SQL_DEVELOPER_PASSWORD_FILE="$secret_root/novapos-developer-password"
fi

exec /opt/nova/venv/bin/python -m scoped_operations_mcp.salesforce_server
