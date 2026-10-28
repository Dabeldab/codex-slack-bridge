#!/bin/sh
set -eu
umask 077

[ "$#" -eq 0 ] || {
  echo "deterministic location-region update accepts JSON on stdin only" >&2
  exit 64
}
cd /

secret_root=/run/nova-secrets
for name in salesforce-client-id salesforce-client-secret salesforce-login-url salesforce-instance-url; do
  test -s "$secret_root/$name" || {
    echo "required Salesforce broker secret is unavailable" >&2
    exit 78
  }
done

export SALESFORCE_USE_CLIENT_CREDENTIALS=true
export SALESFORCE_CLIENT_ID="$(cat "$secret_root/salesforce-client-id")"
export SALESFORCE_CLIENT_SECRET="$(cat "$secret_root/salesforce-client-secret")"
export SALESFORCE_LOGIN_URL="$(cat "$secret_root/salesforce-login-url")"
export SALESFORCE_INSTANCE_URL="$(cat "$secret_root/salesforce-instance-url")"
export NOVA_SQL_DRIVER="ODBC Driver 18 for SQL Server"
export NOVA_SQL_WRITE_STATE_DIR=/var/lib/nova/broker/sql-write

exec /opt/nova/venv/bin/python -m scoped_operations_mcp.nova_sql_location_region_cli
