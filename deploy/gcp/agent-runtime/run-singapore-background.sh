#!/bin/sh
set -eu
umask 0007

shared_output=/var/lib/nova/broker/singapore-shared/ops_singapore_ftp.json
recipient=Julio
include_non_submissions=0
reactivation_target=
trusted_domains=
preflight=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --output-path)
      [ "$#" -ge 2 ] || exit 64
      [ "$2" = "$shared_output" ] || { echo "invalid Singapore output path" >&2; exit 64; }
      shift 2 ;;
    --recipient-hint)
      [ "$#" -ge 2 ] || exit 64
      [ "$2" = Julio ] || { echo "invalid Singapore recipient hint" >&2; exit 64; }
      recipient="$2"; shift 2 ;;
    --trusted-config-sender-domain)
      [ "$#" -ge 2 ] || exit 64
      case "$2" in synthesis.bz) trusted_domains="$trusted_domains --trusted-config-sender-domain synthesis.bz" ;; *) echo "invalid trusted domain" >&2; exit 64 ;; esac
      shift 2 ;;
    --include-non-submissions)
      include_non_submissions=1; shift ;;
    --preflight)
      preflight=1; shift ;;
    --reactivation-target)
      [ "$#" -ge 2 ] || exit 64
      case "$2" in *[!0-9]*|'') echo "invalid reactivation target" >&2; exit 64 ;; esac
      reactivation_target="$2"; shift 2 ;;
    *) echo "unsupported Singapore runner argument" >&2; exit 64 ;;
  esac
done

component=/opt/nova/components/singapore/current
state=/var/lib/nova/broker/singapore
secret_root=/run/nova-secrets
test -f "$component/headless_upload_runner.py" || { echo "Singapore component is unavailable" >&2; exit 78; }
for name in singapore-gmail-client singapore-gmail-token singapore-server-catalog; do
  test -s "$secret_root/$name" || { echo "required Singapore broker secret is unavailable" >&2; exit 78; }
done

install -d -m 0700 "$state"
[ -s "$state/credentials.json" ] || install -m 0600 "$secret_root/singapore-gmail-client" "$state/credentials.json"
[ -s "$state/token.json" ] || install -m 0600 "$secret_root/singapore-gmail-token" "$state/token.json"
[ -s "$state/servers.json" ] || install -m 0600 "$secret_root/singapore-server-catalog" "$state/servers.json"
if [ -s "$secret_root/singapore-salesforce-identity-map" ] && [ ! -s "$state/salesforce-identity-map.json" ]; then
  install -m 0600 "$secret_root/singapore-salesforce-identity-map" "$state/salesforce-identity-map.json"
fi

if [ "$preflight" -eq 1 ]; then
  exec /opt/nova/venv/bin/python -m codex_slack_bridge.singapore_ftp_runner \
    --preflight \
    --uploader-root "$component" \
    --state-dir "$state" \
    --server-config-path "$state/servers.json"
fi

for name in \
  zoom-s2s-account-id \
  zoom-s2s-client-id \
  zoom-s2s-client-secret \
  zoom-team-chat-sender-user-id \
  zoom-singapore-julio-contact; do
  test -s "$secret_root/$name" || { echo "required Singapore Zoom credential is unavailable" >&2; exit 78; }
done
ops_env="$state/ops.env"
if [ ! -s "$ops_env" ]; then
  umask 077
  {
    printf 'ZOOM_SINGAPORE_JULIO_CONTACT=%s\n' "$(cat "$secret_root/zoom-singapore-julio-contact")"
  } >"$ops_env"
fi
export ZOOM_ACCOUNT_ID="$(cat "$secret_root/zoom-s2s-account-id")"
export ZOOM_CLIENT_ID="$(cat "$secret_root/zoom-s2s-client-id")"
export ZOOM_CLIENT_SECRET="$(cat "$secret_root/zoom-s2s-client-secret")"
export ZOOM_TEAM_CHAT_SENDER_USER_ID="$(cat "$secret_root/zoom-team-chat-sender-user-id")"
export ZOOM_SINGAPORE_JULIO_CONTACT="$(cat "$secret_root/zoom-singapore-julio-contact")"
export NOVA_INTERNAL_COMMUNICATION_JOURNAL_PATH=/var/lib/nova/broker/internal-comms/verified-requests.jsonl

set -- \
  --uploader-root "$component" \
  --state-dir "$state" \
  --server-config-path "$state/servers.json" \
  --ops-env-path "$ops_env" \
  --output-path "$shared_output" \
  --recipient-hint "$recipient"
[ "$include_non_submissions" -eq 0 ] || set -- "$@" --include-non-submissions
[ -z "$reactivation_target" ] || set -- "$@" --reactivation-target "$reactivation_target"
# trusted_domains contains only one fixed allowlisted expansion above.
# shellcheck disable=SC2086
set -- "$@" $trusted_domains

exec /opt/nova/venv/bin/python -m codex_slack_bridge.singapore_ftp_runner "$@"
