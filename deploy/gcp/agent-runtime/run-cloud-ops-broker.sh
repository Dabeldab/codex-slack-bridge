#!/bin/sh
set -eu

lane="${1:-}"
case "$lane" in
  direct_codex|raw_codex|coding_agent) ;;
  *) echo "invalid cloud operations lane" >&2; exit 64 ;;
esac
cd /

secret_root=/run/nova-secrets
token_path=/run/nova-cloud-identity/access-token
for name in github-app-id github-app-installation-id github-app-private-key; do
  test -s "$secret_root/$name" || { echo "required GitHub App credential is unavailable" >&2; exit 78; }
done
test -s "$token_path" || { echo "Rory's short-lived Google Cloud token is unavailable" >&2; exit 78; }

export SCOPED_AGENT_LANE="$lane"
export GCP_PROJECT_ID=gen-lang-client-0051653266
export GCP_DEFAULT_REGION=us-central1
export GCP_RORY_SERVICE_ACCOUNT=nova-rory-cloud-ops@gen-lang-client-0051653266.iam.gserviceaccount.com
export GCP_RORY_ACCESS_TOKEN_PATH="$token_path"
export GITHUB_APP_ID_PATH="$secret_root/github-app-id"
export GITHUB_APP_INSTALLATION_ID_PATH="$secret_root/github-app-installation-id"
export GITHUB_APP_PRIVATE_KEY_PATH="$secret_root/github-app-private-key"
export GITHUB_ALLOWED_REPOSITORIES=dariusmakesstuff/codex-slack-bridge,dariusmakesstuff/logmein-connector,dariusmakesstuff/FTPUploader
case "$lane" in
  coding_agent) export GITHUB_WORKSPACE_ROOT=/srv/nova/workspaces/taylor ;;
  *) export GITHUB_WORKSPACE_ROOT=/srv/nova/workspaces/rory ;;
esac
export GITHUB_WRITE_JOURNAL_PATH=/var/lib/nova/broker/cloud/github-writes.jsonl

exec /opt/nova/venv/bin/python -m scoped_operations_mcp.cloud_ops_server
