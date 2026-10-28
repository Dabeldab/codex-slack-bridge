#!/bin/sh
set -eu
cd /

secret_root=/run/nova-secrets
for name in zoom-oauth-client-id zoom-oauth-client-secret zoom-oauth-refresh-token; do
  test -s "$secret_root/$name" || { echo "required Zoom monitor secret is unavailable" >&2; exit 78; }
done

install -d -m 2770 /var/lib/nova/broker/zoom
chgrp nova-zoom-credentials /var/lib/nova/broker/zoom
state_path=/var/lib/nova/broker/zoom/oauth.env
if [ ! -s "$state_path" ]; then
  printf 'ZOOM_OAUTH_REFRESH_TOKEN=%s\n' "$(cat "$secret_root/zoom-oauth-refresh-token")" >"$state_path"
fi
chgrp nova-zoom-credentials "$state_path"
chmod 0660 "$state_path"
export ZOOM_OAUTH_CLIENT_ID="$(cat "$secret_root/zoom-oauth-client-id")"
export ZOOM_OAUTH_CLIENT_SECRET="$(cat "$secret_root/zoom-oauth-client-secret")"
export ZOOM_OAUTH_REFRESH_TOKEN="$(cat "$secret_root/zoom-oauth-refresh-token")"
export ZOOM_OAUTH_STATE_PATH="$state_path"
export ZOOM_OAUTH_SHARED_STATE=true
export ZOOM_CHAT_MONITOR_LOOKBACK_HOURS=24

exec /opt/nova/venv/bin/python -m codex_slack_bridge.zoom_chat_monitor \
  --cache /var/lib/nova/broker/zoom-shared/zoom_chat_monitor.json \
  --since-hours 24
