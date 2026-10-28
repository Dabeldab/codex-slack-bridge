#!/bin/sh
set -eu
umask 077

[ "$#" -eq 0 ] || { echo "deterministic support-email ticket readback accepts JSON on stdin only" >&2; exit 64; }
cd /

secret_root=/run/nova-secrets
for name in salesforce-client-id salesforce-client-secret salesforce-login-url salesforce-instance-url; do
  test -s "$secret_root/$name" || { echo "required Salesforce broker secret is unavailable" >&2; exit 78; }
done

export SALESFORCE_USE_CLIENT_CREDENTIALS=true
export SALESFORCE_CLIENT_ID="$(cat "$secret_root/salesforce-client-id")"
export SALESFORCE_CLIENT_SECRET="$(cat "$secret_root/salesforce-client-secret")"
export SALESFORCE_LOGIN_URL="$(cat "$secret_root/salesforce-login-url")"
export SALESFORCE_INSTANCE_URL="$(cat "$secret_root/salesforce-instance-url")"

exec /opt/nova/venv/bin/python -m scoped_operations_mcp.salesforce_support_email_readback_cli
