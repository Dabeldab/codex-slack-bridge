#!/bin/sh
set -eu
umask 077

if [ "$(id -u)" -ne 0 ]; then
  echo "Device authentication must be launched by root through the private IAP session" >&2
  exit 1
fi

if [ "$(cat /etc/nova/codex-auth-mode 2>/dev/null || true)" != device ]; then
  echo "This runtime was not provisioned in device-auth mode" >&2
  exit 1
fi

identity=${1:-}
case "$identity" in
  rory) user=nova-rory ;;
  thor|claude) user=nova-claude; identity=thor ;;
  taylor) user=nova-taylor ;;
  alex) user=nova-alex ;;
  jamie) user=nova-jamie ;;
  *) echo "Usage: $0 {rory|thor|taylor|alex|jamie}" >&2; exit 2 ;;
esac

home=$(getent passwd "$user" | cut -d: -f6)
auth_file="$home/.codex/auth.json"
test -s "$home/.codex/config.toml"

if runuser -u "$user" -- env HOME="$home" /usr/local/bin/codex login status 2>&1 \
  | grep -Fq "Logged in using ChatGPT"; then
  printf '{"ok":true,"status":"already_authenticated","identity":"%s"}\n' "$identity"
  exit 0
fi

printf 'Starting ChatGPT device authentication for %s. Complete only the URL and one-time code printed by Codex.\n' "$identity"
runuser -u "$user" -- env HOME="$home" /usr/local/bin/codex login --device-auth

if [ ! -s "$auth_file" ]; then
  echo "Codex completed without creating the expected file-backed credential" >&2
  exit 1
fi
chown "$user:$user" "$auth_file"
chmod 0600 "$auth_file"

if ! runuser -u "$user" -- env HOME="$home" /usr/local/bin/codex login status 2>&1 \
  | grep -Fq "Logged in using ChatGPT"; then
  echo "Codex device authentication readback failed" >&2
  exit 1
fi

printf '{"ok":true,"status":"authenticated","identity":"%s"}\n' "$identity"
