#!/bin/sh
# AgentChat/direct_codex 2026-08-04T15:00:00Z
set -eu
cd /

set +e
automation_window="$(/opt/nova/venv/bin/python -m codex_slack_bridge.automation_window)"
automation_window_status=$?
set -e
printf '%s\n' "$automation_window"
if [ "$automation_window_status" -eq 3 ]; then
  echo "support reminder automation deferred until the daily window opens"
  exit 0
fi
if [ "$automation_window_status" -ne 0 ]; then
  echo "automation window check failed" >&2
  exit "$automation_window_status"
fi

secret_root=/run/nova-secrets
for name in google-workspace-adc zoom-oauth-client-id zoom-oauth-client-secret zoom-oauth-refresh-token; do
  test -s "$secret_root/$name" || { echo "required support reminder credential is unavailable" >&2; exit 78; }
done

install -d -m 0700 -o nova-cloud-broker -g nova-cloud-broker /var/lib/nova/broker/cloud
install -d -m 2770 -o nova-cloud-broker -g nova-runtime /var/lib/nova/broker/support-shared
install -d -m 2770 -o nova-zoom-broker -g nova-zoom-credentials /var/lib/nova/broker/zoom

state_path=/var/lib/nova/broker/zoom/oauth.env
if [ ! -s "$state_path" ]; then
  printf 'ZOOM_OAUTH_REFRESH_TOKEN=%s\n' "$(cat "$secret_root/zoom-oauth-refresh-token")" >"$state_path"
fi
test -r "$state_path" && test -w "$state_path" || {
  echo "shared Zoom OAuth state is unavailable to the support reminder service" >&2
  exit 78
}

export RORY_GOOGLE_WORKSPACE_ADC_PATH="$secret_root/google-workspace-adc"
export ZOOM_OAUTH_CLIENT_ID="$(cat "$secret_root/zoom-oauth-client-id")"
export ZOOM_OAUTH_CLIENT_SECRET="$(cat "$secret_root/zoom-oauth-client-secret")"
export ZOOM_OAUTH_REFRESH_TOKEN="$(cat "$secret_root/zoom-oauth-refresh-token")"
export ZOOM_OAUTH_STATE_PATH="$state_path"
export ZOOM_OAUTH_SHARED_STATE=true

exec /opt/nova/venv/bin/python -m codex_slack_bridge.support_shift_reminders \
  --state /var/lib/nova/broker/cloud/support-shift-reminders.jsonl \
  --cache /var/lib/nova/broker/support-shared/support_shift_reminders.json
