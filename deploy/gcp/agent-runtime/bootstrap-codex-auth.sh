#!/bin/sh
set -eu
umask 077

token=/run/nova-secrets/codex-access-token
mode_file=/etc/nova/codex-auth-mode
test -s "$mode_file"
mode=$(cat "$mode_file")

case "$mode" in
  access-token|device) ;;
  *) echo "Unsupported Codex authentication mode" >&2; exit 1 ;;
esac

for mapping in \
  nova-rory:rory \
  nova-raw:raw \
  nova-claude:claude \
  nova-taylor:taylor \
  nova-alex:alex \
  nova-jamie:jamie
do
  user=${mapping%%:*}
  template=${mapping##*:}
  home=$(getent passwd "$user" | cut -d: -f6)
  install -d -m 0700 -o "$user" -g "$user" "$home/.codex"
  install -m 0640 -o "$user" -g "$user" "/opt/nova/current/deploy/gcp/agent-runtime/codex-home/$template.toml" "$home/.codex/config.toml"
done

if [ "$mode" = device ]; then
  if [ -e "$token" ]; then
    echo "Device-auth mode must not materialize a Codex access token" >&2
    exit 1
  fi
  echo '{"ok":true,"status":"codex_device_auth_pending","users":5}'
  exit 0
fi

if [ ! -s "$token" ]; then
  echo "Codex access-token mode requires a non-empty pinned secret" >&2
  exit 1
fi

for mapping in \
  nova-rory:rory \
  nova-claude:thor \
  nova-taylor:taylor \
  nova-alex:alex \
  nova-jamie:jamie
do
  user=${mapping%%:*}
  home=$(getent passwd "$user" | cut -d: -f6)
  if ! runuser -u "$user" -- env HOME="$home" /usr/local/bin/codex login --with-access-token < "$token" >/dev/null; then
    echo "Codex ChatGPT login failed for an isolated agent identity" >&2
    exit 1
  fi
  chmod 0600 "$home/.codex/auth.json"
done

echo '{"ok":true,"status":"codex_chatgpt_login_initialized","users":5}'
