#!/bin/bash
# AgentChat/direct_codex 2026-08-04T15:00:00Z: add shift-aware support reminders.
set -euo pipefail
umask 077

exec > >(tee -a /var/log/nova-agent-bootstrap.log) 2>&1

metadata() {
  curl --fail --silent --show-error -H 'Metadata-Flavor: Google' \
    "http://metadata.google.internal/computeMetadata/v1/$1"
}

metadata_optional() {
  curl --silent --show-error -H 'Metadata-Flavor: Google' \
    "http://metadata.google.internal/computeMetadata/v1/$1" 2>/dev/null || true
}

PROJECT_ID="$(metadata project/project-id)"
SOURCE_BUCKET="$(metadata instance/attributes/nova-source-bucket)"
SOURCE_OBJECT="$(metadata instance/attributes/nova-source-object)"
SOURCE_COMMIT="$(metadata instance/attributes/nova-source-commit)"
CODEX_VERSION="$(metadata instance/attributes/nova-codex-version)"
CODEX_AUTH_MODE="$(metadata instance/attributes/nova-codex-auth-mode)"
STATE_DISK="$(metadata instance/attributes/nova-state-disk)"
SINGAPORE_SOURCE_OBJECT="$(metadata_optional instance/attributes/nova-singapore-source-object)"
SINGAPORE_SOURCE_COMMIT="$(metadata_optional instance/attributes/nova-singapore-source-commit)"

case "$CODEX_AUTH_MODE" in
  access-token|device) ;;
  *) echo "Unsupported Codex authentication mode" >&2; exit 1 ;;
esac

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  acl ca-certificates curl e2fsprogs git gnupg iptables jq npm python3 python3-pip python3-venv sudo unixodbc-dev

curl --fail --silent --show-error \
  https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb \
  -o /tmp/packages-microsoft-prod.deb
dpkg -i /tmp/packages-microsoft-prod.deb
rm -f /tmp/packages-microsoft-prod.deb
apt-get update
ACCEPT_EULA=Y DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends msodbcsql18

(
  umask 022
  npm install --global "@openai/codex@$CODEX_VERSION"
)
chmod a+rx /usr/local/lib/node_modules /usr/local/lib/node_modules/@openai
chmod -R a+rX /usr/local/lib/node_modules/@openai/codex
/usr/local/bin/codex --version

for user in nova-runtime nova-rory nova-raw nova-claude nova-taylor nova-alex nova-jamie nova-salesforce-broker nova-maxio-broker nova-rescue-broker nova-zoom-broker nova-singapore-broker nova-cloud-broker; do
  if ! getent group "$user" >/dev/null 2>&1; then
    groupadd --system "$user"
  fi
  if ! id "$user" >/dev/null 2>&1; then
    useradd --system --gid "$user" --create-home --home-dir "/home/$user" --shell /bin/bash "$user"
  fi
done

if ! getent group nova-zoom-credentials >/dev/null 2>&1; then
  groupadd --system nova-zoom-credentials
fi
usermod -a -G nova-zoom-credentials nova-zoom-broker
usermod -a -G nova-zoom-credentials nova-singapore-broker
usermod -a -G nova-zoom-credentials nova-cloud-broker

if ! getent group nova-singapore-shared >/dev/null 2>&1; then
  groupadd --system nova-singapore-shared
fi
usermod -a -G nova-singapore-shared nova-runtime
usermod -a -G nova-singapore-shared nova-singapore-broker

if ! getent group nova-maxio-reports >/dev/null 2>&1; then
  groupadd --system nova-maxio-reports
fi
for user in nova-runtime nova-taylor nova-jamie nova-maxio-broker; do
  usermod -a -G nova-maxio-reports "$user"
done

if ! getent group nova-internal-comms >/dev/null 2>&1; then
  groupadd --system nova-internal-comms
fi
usermod -a -G nova-internal-comms nova-salesforce-broker
usermod -a -G nova-internal-comms nova-zoom-broker
usermod -a -G nova-internal-comms nova-singapore-broker

STATE_DEVICE="/dev/disk/by-id/google-$STATE_DISK"
for _ in $(seq 1 30); do
  [ -b "$STATE_DEVICE" ] && break
  sleep 1
done
if [ ! -b "$STATE_DEVICE" ]; then
  echo "Persistent state disk is unavailable" >&2
  exit 1
fi
if ! blkid "$STATE_DEVICE" >/dev/null 2>&1; then
  mkfs.ext4 -F -m 0 -L nova-agent-state "$STATE_DEVICE"
fi
STATE_UUID="$(blkid -s UUID -o value "$STATE_DEVICE")"
install -d -m 0755 /var/lib/nova
if ! grep -Fq "UUID=$STATE_UUID /var/lib/nova " /etc/fstab; then
  printf 'UUID=%s /var/lib/nova ext4 defaults,nofail,nodev,nosuid 0 2\n' "$STATE_UUID" >> /etc/fstab
fi
mountpoint -q /var/lib/nova || mount /var/lib/nova
chmod 0755 /var/lib/nova
install -d -m 0700 -o root -g root /var/lib/nova/activation
PRODUCTION_CUTOVER_MARKER=/var/lib/nova/activation/production-cutover.enabled
RUNTIME_PREFLIGHT_MARKER=/run/nova-runtime/production-preflight-passed
ZOOM_PREFLIGHT_MARKER=/run/nova-preflight/zoom-passed
rm -f "$RUNTIME_PREFLIGHT_MARKER"
rm -f "$ZOOM_PREFLIGHT_MARKER"
if [ -f "$PRODUCTION_CUTOVER_MARKER" ]; then
  # An activated runtime must remain quiesced until this exact release passes
  # provider and broker preflight. The provisioner disables these units before
  # reboot; this is the defense-in-depth path for a manual startup-script rerun.
  systemctl stop nova-runtime-recovery.timer nova-command-center-healthcheck.timer nova-command-center.service nova-slack-bridge.service nova-zoom-monitor.timer nova-support-shift-reminders.timer >/dev/null 2>&1 || true
fi

install -d -m 0755 /opt/nova/releases /opt/nova/bin /etc/nova
install -d -m 0750 -o root -g nova-runtime /etc/nova/codex-mcp-policy
install -d -m 0711 -o nova-runtime -g nova-runtime /srv/nova/attachments
install -d -m 0700 -o nova-runtime -g nova-runtime \
  /var/lib/nova/state /var/lib/nova/gmail /var/lib/nova/slack \
  /run/nova-runtime /var/log/nova /var/log/nova/cleanup
install -d -m 0700 -o root -g root /run/nova-preflight
install -d -m 0711 -o root -g root /var/lib/nova/broker
install -d -m 0700 -o nova-salesforce-broker -g nova-salesforce-broker \
  /var/lib/nova/broker/sql-write /var/lib/nova/broker/salesforce
install -d -m 0700 -o nova-maxio-broker -g nova-maxio-broker /var/lib/nova/broker/maxio
install -d -m 2770 -o nova-maxio-broker -g nova-maxio-reports /var/lib/nova/broker/maxio-reports
install -d -m 0700 -o nova-cloud-broker -g nova-cloud-broker /var/lib/nova/broker/cloud
install -d -m 2770 -o nova-cloud-broker -g nova-runtime /var/lib/nova/broker/support-shared
install -d -m 2770 -o nova-zoom-broker -g nova-zoom-credentials /var/lib/nova/broker/zoom
for zoom_state_file in /var/lib/nova/broker/zoom/oauth.env /var/lib/nova/broker/zoom/oauth.env.lock; do
  if [ -e "$zoom_state_file" ]; then
    chgrp nova-zoom-credentials "$zoom_state_file"
    chmod 0660 "$zoom_state_file"
  fi
done
install -d -m 2770 -o nova-zoom-broker -g nova-runtime /var/lib/nova/broker/zoom-shared
install -d -m 2770 -o root -g nova-internal-comms /var/lib/nova/broker/internal-comms
for internal_comms_file in \
  /var/lib/nova/broker/internal-comms/verified-requests.jsonl \
  /var/lib/nova/broker/internal-comms/verified-requests.jsonl.lock; do
  if [ -e "$internal_comms_file" ]; then
    chgrp nova-internal-comms "$internal_comms_file"
    chmod 0660 "$internal_comms_file"
  fi
done
install -d -m 0700 -o nova-singapore-broker -g nova-singapore-broker /var/lib/nova/broker/singapore
install -d -m 2770 -o nova-singapore-broker -g nova-singapore-shared /var/lib/nova/broker/singapore-shared
if [ -e /var/lib/nova/broker/singapore-shared/ops_singapore_ftp.json ]; then
  chown nova-singapore-broker:nova-singapore-shared \
    /var/lib/nova/broker/singapore-shared/ops_singapore_ftp.json
  chmod 0660 /var/lib/nova/broker/singapore-shared/ops_singapore_ftp.json
fi

# Codex file-backed credentials are isolated by Linux identity and live on the
# non-auto-delete state disk. Bind mounts preserve the normal ~/.codex path
# while keeping authentication across a safe VM replacement.
install -d -m 0711 -o root -g root /var/lib/nova/codex
for mapping in rory:nova-rory raw:nova-raw claude:nova-claude taylor:nova-taylor alex:nova-alex jamie:nova-jamie; do
  identity=${mapping%%:*}
  owner=${mapping##*:}
  home=$(getent passwd "$owner" | cut -d: -f6)
  auth_root="/var/lib/nova/codex/$identity"
  auth_home="$home/.codex"
  install -d -m 0700 -o "$owner" -g "$owner" "$auth_root" "$auth_home"
  fstab_entry="$auth_root $auth_home none bind,nofail,x-system.requires-mounts-for=/var/lib/nova 0 0"
  # Remove any stale mapping for this home before installing the exclusive
  # identity mapping. Older releases mapped Claude onto Rory's home, so merely
  # appending a second fstab entry would leave the unsafe bind mount active.
  fstab_tmp=$(mktemp)
  awk -v target="$auth_home" '$2 != target { print }' /etc/fstab > "$fstab_tmp"
  printf '%s\n' "$fstab_entry" >> "$fstab_tmp"
  install -m 0644 -o root -g root "$fstab_tmp" /etc/fstab
  rm -f "$fstab_tmp"
  if mountpoint -q "$auth_home"; then
    umount "$auth_home"
  fi
  mount --bind "$auth_root" "$auth_home"
  chown -R "$owner:$owner" "$auth_root"
  chown "$owner:$owner" "$auth_home"
  chmod 0700 "$auth_root" "$auth_home"
done

install -d -m 0711 -o root -g root /srv/nova/workspaces /srv/nova/sandboxes

for mapping in rory:nova-rory raw:nova-raw claude:nova-claude taylor:nova-taylor alex:nova-alex jamie:nova-jamie; do
  workspace=${mapping%%:*}
  owner=${mapping##*:}
  usermod -a -G "$owner" nova-runtime
  install -d -m 2770 -o "$owner" -g "$owner" "/srv/nova/workspaces/$workspace"
done
# Alex writes the verified weekly metrics cache and Command Center atomically
# adds the Gmail delivery receipt. Keep their exact shared directory setgid and
# group-writable so the receipt cannot fail after a successful external send.
install -d -m 2770 -o nova-alex -g nova-alex \
  /srv/nova/workspaces/alex/command-center-output/weekly-report

# The supervisor creates each lane's prompt and indexes its artifacts, while
# Codex runs under a separate Linux identity.  Keep the parent non-writable and
# grant only the matching agent group access to its own sandbox.
for mapping in \
  direct_codex:nova-rory \
  raw_codex:nova-raw \
  coding_agent:nova-taylor \
  tickets_agent:nova-alex \
  billing_agent:nova-jamie \
  claude_agent:nova-claude; do
  sandbox=${mapping%%:*}
  owner=${mapping##*:}
  install -d -m 2770 -o "$owner" -g "$owner" "/srv/nova/sandboxes/$sandbox"
done

ACCESS_TOKEN="$(metadata instance/service-accounts/default/token | jq -r .access_token)"
ENCODED_OBJECT="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$SOURCE_OBJECT")"
ARCHIVE=/tmp/nova-agent-source.tar.gz
curl --fail --silent --show-error \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  "https://storage.googleapis.com/storage/v1/b/$SOURCE_BUCKET/o/$ENCODED_OBJECT?alt=media" \
  -o "$ARCHIVE"

if [ -z "$SINGAPORE_SOURCE_OBJECT" ] || [ -z "$SINGAPORE_SOURCE_COMMIT" ]; then
  echo "Pinned Singapore component metadata is unavailable" >&2
  exit 1
fi
SINGAPORE_ENCODED_OBJECT="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$SINGAPORE_SOURCE_OBJECT")"
SINGAPORE_ARCHIVE=/tmp/nova-singapore-source.tar.gz
curl --fail --silent --show-error \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  "https://storage.googleapis.com/storage/v1/b/$SOURCE_BUCKET/o/$SINGAPORE_ENCODED_OBJECT?alt=media" \
  -o "$SINGAPORE_ARCHIVE"
unset ACCESS_TOKEN

RELEASE_DIR="/opt/nova/releases/$SOURCE_COMMIT"
rm -rf "$RELEASE_DIR"
install -d -m 0755 "$RELEASE_DIR"
tar -xzf "$ARCHIVE" -C "$RELEASE_DIR"
rm -f "$ARCHIVE"
ln -sfn "$RELEASE_DIR" /opt/nova/current

SINGAPORE_RELEASE_DIR="/opt/nova/components/singapore/$SINGAPORE_SOURCE_COMMIT"
rm -rf "$SINGAPORE_RELEASE_DIR"
install -d -m 0755 "$SINGAPORE_RELEASE_DIR"
tar -xzf "$SINGAPORE_ARCHIVE" -C "$SINGAPORE_RELEASE_DIR"
rm -f "$SINGAPORE_ARCHIVE"
chown -R root:root "$SINGAPORE_RELEASE_DIR"
chmod -R a+rX "$SINGAPORE_RELEASE_DIR"
ln -sfn "$SINGAPORE_RELEASE_DIR" /opt/nova/components/singapore/current

# The supervisor must validate MCP allowlists before changing to an agent UID,
# but it must not traverse that agent's owner-only Codex authentication home.
# Keep a non-secret, root-managed copy of each MCP launcher configuration.
for template in rory raw claude taylor alex jamie; do
  install -m 0640 -o root -g nova-runtime \
    "/opt/nova/current/deploy/gcp/agent-runtime/codex-home/$template.toml" \
    "/etc/nova/codex-mcp-policy/$template.toml"
done

python3 -m venv /opt/nova/venv
/opt/nova/venv/bin/python -m pip install --upgrade pip setuptools wheel
/opt/nova/venv/bin/python -m pip install '/opt/nova/current[google-secret-manager]'
/opt/nova/venv/bin/python -m pip install /opt/nova/current/tools/scoped-operations-mcp
/opt/nova/venv/bin/python -m pip install /opt/nova/current/tools/rescue-console-mcp
# Bootstrap runs with umask 077, but the Command Center and Slack services run
# as nova-runtime. The virtualenv contains code only: keep it root-owned and
# non-writable while granting the service identities read/traverse permission.
chmod -R a+rX /opt/nova/venv

# AgentChat/direct_codex 2026-07-27T21:24:14Z: persist and index the shared
# Nova database enum reference once per source revision. The stable state path
# keeps the global-memory fingerprint idempotent across immutable releases.
NOVA_ENUMS_RELEASE_SOURCE=/opt/nova/current/knowledge_sources/general/nova_database/nova_enums.md
NOVA_ENUMS_STATE_DIR=/var/lib/nova/state/knowledge_sources/general/nova_database
NOVA_ENUMS_STATE_SOURCE="$NOVA_ENUMS_STATE_DIR/nova_enums.md"
install -d -m 0750 -o nova-runtime -g nova-runtime "$NOVA_ENUMS_STATE_DIR"
if [ ! -f "$NOVA_ENUMS_STATE_SOURCE" ] || ! cmp -s "$NOVA_ENUMS_RELEASE_SOURCE" "$NOVA_ENUMS_STATE_SOURCE"; then
  install -m 0640 -o nova-runtime -g nova-runtime \
    "$NOVA_ENUMS_RELEASE_SOURCE" "$NOVA_ENUMS_STATE_SOURCE"
  sudo -u nova-runtime /opt/nova/venv/bin/python -m codex_slack_bridge.knowledge_ingest \
    --config /opt/nova/current/config/agents.gcp-runtime.yaml \
    --source "$NOVA_ENUMS_STATE_SOURCE" \
    --agent global \
    --tags nova,database,enums \
    --importance 3.0 \
    --manifest /var/lib/nova/state/knowledge_ingest_manifest.jsonl
fi

for script in run-salesforce-broker.sh run-salesforce-ticket-close.sh run-nova-location-region.sh run-salesforce-support-email-readback.sh run-salesforce-support-quality-projection.sh run-maxio-broker.sh run-rescue-broker.sh run-zoom-broker.sh run-zoom-monitor.sh run-support-shift-reminders.sh run-cloud-ops-broker.sh run-operator-broker.sh run-thor-drive-broker.sh run-singapore-background.sh bootstrap-codex-auth.sh begin-codex-device-auth.sh run-slack-bridge.sh run-command-center.sh; do
  install -m 0755 "/opt/nova/current/deploy/gcp/agent-runtime/$script" "/opt/nova/bin/${script%.sh}"
done

cat >/etc/sudoers.d/nova-agent-runtime <<'SUDOERS'
Defaults:nova-runtime secure_path=/usr/local/bin:/usr/bin:/bin
Defaults:nova-rory secure_path=/usr/local/bin:/usr/bin:/bin
Defaults:nova-raw secure_path=/usr/local/bin:/usr/bin:/bin
Defaults:nova-claude secure_path=/usr/local/bin:/usr/bin:/bin
Defaults:nova-taylor secure_path=/usr/local/bin:/usr/bin:/bin
Defaults:nova-alex secure_path=/usr/local/bin:/usr/bin:/bin
Defaults:nova-jamie secure_path=/usr/local/bin:/usr/bin:/bin
Defaults:nova-cloud-broker secure_path=/usr/local/bin:/usr/bin:/bin
Defaults:nova-zoom-broker secure_path=/usr/local/bin:/usr/bin:/bin
Defaults:nova-rescue-broker secure_path=/usr/local/bin:/usr/bin:/bin
Defaults:nova-singapore-broker secure_path=/usr/local/bin:/usr/bin:/bin

nova-runtime ALL=(nova-rory) NOPASSWD: /usr/local/bin/codex *
nova-runtime ALL=(nova-raw) NOPASSWD: /usr/local/bin/codex *
nova-runtime ALL=(nova-claude) NOPASSWD: /usr/local/bin/codex *
nova-runtime ALL=(nova-taylor) NOPASSWD: /usr/local/bin/codex *
nova-runtime ALL=(nova-alex) NOPASSWD: /usr/local/bin/codex *
nova-runtime ALL=(nova-jamie) NOPASSWD: /usr/local/bin/codex *

nova-taylor ALL=(nova-salesforce-broker) NOPASSWD: /opt/nova/bin/run-salesforce-broker coding_agent
nova-alex ALL=(nova-salesforce-broker) NOPASSWD: /opt/nova/bin/run-salesforce-broker tickets_agent
nova-jamie ALL=(nova-salesforce-broker) NOPASSWD: /opt/nova/bin/run-salesforce-broker billing_agent
nova-rory ALL=(nova-salesforce-broker) NOPASSWD: /opt/nova/bin/run-salesforce-broker direct_codex
nova-rory ALL=(nova-zoom-broker) NOPASSWD: /opt/nova/bin/run-zoom-broker direct_codex
nova-taylor ALL=(nova-maxio-broker) NOPASSWD: /opt/nova/bin/run-maxio-broker coding_agent
nova-jamie ALL=(nova-maxio-broker) NOPASSWD: /opt/nova/bin/run-maxio-broker billing_agent
nova-rory ALL=(nova-cloud-broker) NOPASSWD: /opt/nova/bin/run-cloud-ops-broker direct_codex
nova-rory ALL=(nova-cloud-broker) NOPASSWD: /opt/nova/bin/run-operator-broker direct_codex
nova-taylor ALL=(nova-cloud-broker) NOPASSWD: /opt/nova/bin/run-cloud-ops-broker coding_agent
nova-taylor ALL=(nova-zoom-broker) NOPASSWD: /opt/nova/bin/run-zoom-broker coding_agent
nova-alex ALL=(nova-rescue-broker) NOPASSWD: /opt/nova/bin/run-rescue-broker tickets_agent
nova-alex ALL=(nova-zoom-broker) NOPASSWD: /opt/nova/bin/run-zoom-broker tickets_agent
nova-jamie ALL=(nova-zoom-broker) NOPASSWD: /opt/nova/bin/run-zoom-broker billing_agent
nova-claude ALL=(nova-rescue-broker) NOPASSWD: /opt/nova/bin/run-rescue-broker claude_agent
nova-claude ALL=(nova-zoom-broker) NOPASSWD: /opt/nova/bin/run-zoom-broker claude_agent
nova-claude ALL=(nova-salesforce-broker) NOPASSWD: /opt/nova/bin/run-salesforce-broker claude_agent
nova-claude ALL=(nova-cloud-broker) NOPASSWD: /opt/nova/bin/run-thor-drive-broker claude_agent
nova-runtime ALL=(nova-salesforce-broker) NOPASSWD: /opt/nova/bin/run-salesforce-ticket-close
nova-runtime ALL=(nova-salesforce-broker) NOPASSWD: /opt/nova/bin/run-nova-location-region
nova-runtime ALL=(nova-salesforce-broker) NOPASSWD: /opt/nova/bin/run-salesforce-support-email-readback
nova-runtime ALL=(nova-salesforce-broker) NOPASSWD: /opt/nova/bin/run-salesforce-support-quality-projection
nova-runtime ALL=(nova-singapore-broker) NOPASSWD: /opt/nova/bin/run-singapore-background *
SUDOERS
chmod 0440 /etc/sudoers.d/nova-agent-runtime
visudo -cf /etc/sudoers.d/nova-agent-runtime

# The VM service account can read only the named Secret Manager resources.
# Block model and business-system broker processes from metadata. The dedicated
# cloud identity is minted by a root-only timer. Every model and broker process,
# including Rory's cloud broker, is blocked from the VM's attached identity.
cat >/opt/nova/bin/apply-metadata-firewall <<'FIREWALL'
#!/bin/sh
set -eu
iptables -N NOVA_METADATA 2>/dev/null || true
iptables -F NOVA_METADATA
iptables -A NOVA_METADATA -m owner --uid-owner 0 -j RETURN
# GCE also exposes its DNS resolver on the metadata address. Permit DNS only;
# all HTTP access, including service-account token minting, remains blocked.
iptables -A NOVA_METADATA -p udp --dport 53 -j RETURN
iptables -A NOVA_METADATA -p tcp --dport 53 -j RETURN
iptables -A NOVA_METADATA -j REJECT
iptables -C OUTPUT -d 169.254.169.254/32 -j NOVA_METADATA 2>/dev/null || \
  iptables -I OUTPUT 1 -d 169.254.169.254/32 -j NOVA_METADATA
if command -v ip6tables >/dev/null 2>&1; then
  ip6tables -N NOVA_METADATA_V6 2>/dev/null || true
  ip6tables -F NOVA_METADATA_V6
  ip6tables -A NOVA_METADATA_V6 -m owner --uid-owner 0 -j RETURN
  ip6tables -A NOVA_METADATA_V6 -p udp --dport 53 -j RETURN
  ip6tables -A NOVA_METADATA_V6 -p tcp --dport 53 -j RETURN
  ip6tables -A NOVA_METADATA_V6 -j REJECT
  ip6tables -C OUTPUT -d fd20:ce::254/128 -j NOVA_METADATA_V6 2>/dev/null || \
    ip6tables -I OUTPUT 1 -d fd20:ce::254/128 -j NOVA_METADATA_V6
fi
FIREWALL
chmod 0755 /opt/nova/bin/apply-metadata-firewall

cat >/etc/systemd/system/nova-metadata-firewall.service <<'UNIT'
[Unit]
Description=Block GCE metadata access from Nova non-root identities
Before=nova-secrets.service nova-command-center.service nova-slack-bridge.service

[Service]
Type=oneshot
ExecStart=/opt/nova/bin/apply-metadata-firewall
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
UNIT

cat >/etc/systemd/system/nova-cloud-token.service <<'UNIT'
[Unit]
Description=Mint Rory's short-lived project-owner Google Cloud token
After=network-online.target nova-metadata-firewall.service
Wants=network-online.target nova-metadata-firewall.service

[Service]
Type=oneshot
User=root
Group=root
RuntimeDirectory=nova-cloud-identity
RuntimeDirectoryMode=0710
RuntimeDirectoryPreserve=yes
ExecStart=/opt/nova/venv/bin/python /opt/nova/current/deploy/gcp/agent-runtime/mint_cloud_identity_token.py --target-principal nova-rory-cloud-ops@gen-lang-client-0051653266.iam.gserviceaccount.com --output /run/nova-cloud-identity/access-token
UMask=0077
UNIT

cat >/etc/systemd/system/nova-cloud-token.timer <<'UNIT'
[Unit]
Description=Refresh Rory's short-lived project-owner Google Cloud token

[Timer]
OnBootSec=30s
OnUnitActiveSec=20min
Persistent=true
RandomizedDelaySec=30s

[Install]
WantedBy=timers.target
UNIT

metadata instance/attributes/nova-secret-manifest > /etc/nova/secret-manifest.json
chmod 0600 /etc/nova/secret-manifest.json
printf '%s\n' "$CODEX_AUTH_MODE" > /etc/nova/codex-auth-mode
chmod 0600 /etc/nova/codex-auth-mode

cat >/opt/nova/bin/apply-rory-operator-secret-acls <<'ACL'
#!/bin/sh
set -eu
for path in \
  /run/nova-secrets/gmail-oauth-token \
  /run/nova-secrets/salesforce-client-id \
  /run/nova-secrets/salesforce-client-secret \
  /run/nova-secrets/salesforce-login-url \
  /run/nova-secrets/salesforce-instance-url \
  /run/nova-secrets/chargify-api-key \
  /run/nova-secrets/chargify-base-url \
  /run/nova-secrets/rescue-user \
  /run/nova-secrets/rescue-password \
  /run/nova-secrets/rescue-base \
  /run/nova-secrets/rescue-node-id \
  /run/nova-secrets/zoom-oauth-client-id \
  /run/nova-secrets/zoom-oauth-client-secret \
  /run/nova-secrets/zoom-oauth-refresh-token \
  /run/nova-secrets/command-center-proxy-token; do
  test -s "$path" || { echo "required Rory operator credential is unavailable" >&2; exit 78; }
  setfacl -m u:nova-cloud-broker:r "$path"
done
ACL
chmod 0755 /opt/nova/bin/apply-rory-operator-secret-acls

cat >/etc/systemd/system/nova-secrets.service <<'UNIT'
[Unit]
Description=Materialize pinned Nova Secret Manager versions
After=network-online.target nova-metadata-firewall.service
Wants=network-online.target nova-metadata-firewall.service

[Service]
Type=oneshot
RuntimeDirectory=nova-secrets
RuntimeDirectoryMode=0711
ExecStart=/opt/nova/venv/bin/python /opt/nova/current/deploy/gcp/agent-runtime/materialize_secrets.py /etc/nova/secret-manifest.json
ExecStartPost=/opt/nova/bin/apply-rory-operator-secret-acls
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
UNIT

cat >/etc/systemd/system/nova-codex-auth.service <<'UNIT'
[Unit]
Description=Initialize isolated Codex CLI ChatGPT credentials
After=nova-secrets.service
Requires=nova-secrets.service

[Service]
Type=oneshot
Environment=DO_NOT_TRACK=1
Environment=OTEL_SDK_DISABLED=true
ExecStart=/opt/nova/bin/bootstrap-codex-auth
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
UNIT

cat >/usr/local/sbin/nova-command-center-healthcheck <<'SCRIPT'
#!/bin/sh
set -eu

health_url=http://127.0.0.1:17866/healthz
if curl --fail --silent --show-error --max-time 5 "$health_url" >/dev/null; then
  exit 0
fi

logger -t nova-command-center-healthcheck 'Local Command Center health failed; restarting nova-command-center.service.'
systemctl --no-block restart nova-command-center.service
sleep 5
curl --fail --silent --show-error --max-time 5 "$health_url" >/dev/null
SCRIPT
chmod 0755 /usr/local/sbin/nova-command-center-healthcheck

cat >/usr/local/sbin/nova-runtime-recovery <<'SCRIPT'
#!/bin/sh
set -eu

cutover_marker=/var/lib/nova/activation/production-cutover.enabled
runtime_marker=/run/nova-runtime/production-preflight-passed
zoom_marker=/run/nova-preflight/zoom-passed

# A staged runtime and a healthy activated runtime are both strict no-ops.
[ -f "$cutover_marker" ] || exit 0
[ -f "$runtime_marker" ] && exit 0
systemctl is-active --quiet nova-agent-preflight.service && exit 0

logger -t nova-runtime-recovery 'Core runtime marker is absent; rerunning the read-only production preflight.'
if ! systemctl start nova-agent-preflight.service; then
  logger -t nova-runtime-recovery 'Production preflight is still blocked; core services remain stopped.'
  exit 0
fi

install -m 0600 -o root -g root /dev/null "$runtime_marker"
systemctl enable nova-command-center.service nova-slack-bridge.service
systemctl enable nova-command-center-healthcheck.timer
systemctl restart nova-command-center.service
systemctl restart nova-command-center-healthcheck.timer
systemctl restart nova-slack-bridge.service
if [ -f "$zoom_marker" ]; then
  systemctl enable nova-zoom-monitor.timer nova-support-shift-reminders.timer
  systemctl restart nova-zoom-monitor.timer
  systemctl restart nova-support-shift-reminders.timer
else
  systemctl disable --now nova-zoom-monitor.timer nova-support-shift-reminders.timer >/dev/null 2>&1 || true
fi
logger -t nova-runtime-recovery 'Production preflight recovered; core services were restored once.'
SCRIPT
chmod 0755 /usr/local/sbin/nova-runtime-recovery

cat >/etc/systemd/system/nova-command-center.service <<'UNIT'
[Unit]
Description=Nova private Command Center runtime
After=network-online.target nova-secrets.service nova-codex-auth.service
Requires=nova-secrets.service
ConditionPathExists=/run/nova-runtime/production-preflight-passed
StartLimitIntervalSec=300
StartLimitBurst=10

[Service]
Type=simple
User=nova-runtime
Group=nova-runtime
WorkingDirectory=/opt/nova/current
RuntimeDirectory=nova-runtime
RuntimeDirectoryMode=0700
RuntimeDirectoryPreserve=yes
Environment=HOME=/home/nova-runtime
Environment=COMMAND_CENTER_DISABLE_WATCHERS=0
Environment=AGENT_RUN_TRACE_DIR=/var/log/nova/agent_runs
Environment=DO_NOT_TRACK=1
Environment=OTEL_SDK_DISABLED=true
LoadCredential=gmail-oauth-token:/run/nova-secrets/gmail-oauth-token
LoadCredential=slack-bot-token:/run/nova-secrets/slack-bot-token
LoadCredential=operator-message-key:/run/nova-secrets/operator-message-key
LoadCredential=command-center-proxy-token:/run/nova-secrets/command-center-proxy-token
ExecStartPre=/bin/sh -c 'install -m 0600 "$CREDENTIALS_DIRECTORY/operator-message-key" /run/nova-runtime/operator_message.key && install -m 0600 "$CREDENTIALS_DIRECTORY/command-center-proxy-token" /run/nova-runtime/command-center-proxy.token'
ExecStart=/opt/nova/bin/run-command-center
Restart=always
RestartSec=5
UMask=0007

[Install]
WantedBy=multi-user.target
UNIT

cat >/etc/systemd/system/nova-command-center-healthcheck.service <<'UNIT'
[Unit]
Description=Verify and repair the local Nova Command Center runtime
After=network-online.target nova-command-center.service
ConditionPathExists=/run/nova-runtime/production-preflight-passed

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/nova-command-center-healthcheck
UNIT

cat >/etc/systemd/system/nova-command-center-healthcheck.timer <<'UNIT'
[Unit]
Description=Run the Nova Command Center service health repair

[Timer]
OnBootSec=90s
OnUnitActiveSec=60s
AccuracySec=10s
RandomizedDelaySec=10s
Persistent=true
Unit=nova-command-center-healthcheck.service

[Install]
WantedBy=timers.target
UNIT

cat >/etc/systemd/system/nova-zoom-monitor.service <<'UNIT'
[Unit]
Description=Nova read-only Zoom support chat snapshot
After=network-online.target nova-secrets.service
Requires=nova-secrets.service

[Service]
Type=oneshot
User=nova-zoom-broker
Group=nova-zoom-broker
WorkingDirectory=/
ExecStart=/opt/nova/bin/run-zoom-monitor
UMask=0007
UNIT

cat >/etc/systemd/system/nova-zoom-monitor.timer <<'UNIT'
[Unit]
Description=Refresh Nova read-only Zoom support chat snapshot
ConditionPathExists=/run/nova-runtime/production-preflight-passed
ConditionPathExists=/run/nova-preflight/zoom-passed

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Persistent=true
RandomizedDelaySec=15s

[Install]
WantedBy=timers.target
UNIT

cat >/etc/systemd/system/nova-support-shift-reminders.service <<'UNIT'
[Unit]
Description=Nova shift-aware support review reminders
After=network-online.target nova-secrets.service
Requires=nova-secrets.service

[Service]
Type=oneshot
User=nova-cloud-broker
Group=nova-cloud-broker
WorkingDirectory=/
ExecStart=/opt/nova/bin/run-support-shift-reminders
UMask=0007
UNIT

cat >/etc/systemd/system/nova-support-shift-reminders.timer <<'UNIT'
[Unit]
Description=Check scheduled support review reminders
ConditionPathExists=/run/nova-runtime/production-preflight-passed
ConditionPathExists=/run/nova-preflight/zoom-passed

[Timer]
OnBootSec=3min
OnUnitActiveSec=15min
AccuracySec=30s
Persistent=true
RandomizedDelaySec=30s

[Install]
WantedBy=timers.target
UNIT

cat >/etc/systemd/system/nova-slack-bridge.service <<'UNIT'
[Unit]
Description=Nova Slack Socket Mode to Codex CLI bridge
After=network-online.target nova-command-center.service nova-secrets.service nova-codex-auth.service
Requires=nova-secrets.service
ConditionPathExists=/run/nova-runtime/production-preflight-passed

[Service]
Type=simple
User=nova-runtime
Group=nova-runtime
WorkingDirectory=/opt/nova/current
RuntimeDirectory=nova-runtime
RuntimeDirectoryMode=0700
RuntimeDirectoryPreserve=yes
Environment=HOME=/home/nova-runtime
Environment=AGENT_RUN_TRACE_DIR=/var/log/nova/agent_runs
Environment=DO_NOT_TRACK=1
Environment=OTEL_SDK_DISABLED=true
LoadCredential=slack-app-token:/run/nova-secrets/slack-app-token
LoadCredential=slack-bot-token:/run/nova-secrets/slack-bot-token
LoadCredential=operator-message-key:/run/nova-secrets/operator-message-key
ExecStartPre=/bin/sh -c 'install -m 0600 "$CREDENTIALS_DIRECTORY/operator-message-key" /run/nova-runtime/operator_message.key'
ExecStart=/opt/nova/bin/run-slack-bridge
Restart=on-failure
RestartSec=5
UMask=0007

[Install]
WantedBy=multi-user.target
UNIT

cat >/etc/systemd/system/nova-agent-preflight.service <<'UNIT'
[Unit]
Description=Read-only Nova cloud provider and CLI preflight
After=network-online.target nova-secrets.service nova-codex-auth.service
Requires=nova-secrets.service

[Service]
Type=oneshot
WorkingDirectory=/opt/nova/current
Environment=DO_NOT_TRACK=1
Environment=OTEL_SDK_DISABLED=true
ExecStart=/opt/nova/venv/bin/python /opt/nova/current/deploy/gcp/agent-runtime/preflight.py
UNIT

cat >/etc/systemd/system/nova-runtime-recovery.service <<'UNIT'
[Unit]
Description=Fail-closed recovery for the activated Nova core runtime
After=network-online.target nova-secrets.service nova-codex-auth.service
Requires=nova-secrets.service
ConditionPathExists=/var/lib/nova/activation/production-cutover.enabled

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/nova-runtime-recovery
UNIT

cat >/etc/systemd/system/nova-runtime-recovery.timer <<'UNIT'
[Unit]
Description=Retry blocked Nova production preflight without bypassing it

[Timer]
OnActiveSec=2m
OnUnitActiveSec=2m
AccuracySec=15s
RandomizedDelaySec=15s
Persistent=true
Unit=nova-runtime-recovery.service

[Install]
WantedBy=timers.target
UNIT

for mapping in rory:nova-rory raw:nova-raw claude:nova-claude taylor:nova-taylor alex:nova-alex jamie:nova-jamie; do
  workspace=${mapping%%:*}
  owner=${mapping##*:}
  target="/srv/nova/workspaces/$workspace/codex-slack-bridge"
  rm -rf "$target"
  install -d -m 0750 -o "$owner" -g "$owner" "$target"
  cp -aL /opt/nova/current/. "$target/"
  chown -R "$owner:$owner" "/srv/nova/workspaces/$workspace"
  chmod 2770 "/srv/nova/workspaces/$workspace"
done

systemctl daemon-reload
systemctl enable nova-metadata-firewall.service nova-cloud-token.timer nova-secrets.service nova-codex-auth.service
systemctl enable --now nova-runtime-recovery.timer
# A RemainAfterExit firewall unit can still be active from a previous release.
# Restart it so in-place upgrades apply the rule set installed above.
systemctl restart nova-metadata-firewall.service
systemctl start nova-cloud-token.service
# The unit can already be active from early boot with the previous release's
# manifest. Restart it after installing the new manifest so newly pinned
# credentials are materialized before any runtime service can start.
systemctl restart nova-secrets.service
systemctl start nova-codex-auth.service
if [ "$CODEX_AUTH_MODE" = access-token ] && [ ! -f "$PRODUCTION_CUTOVER_MARKER" ]; then
  systemctl start nova-agent-preflight.service || true
elif [ "$CODEX_AUTH_MODE" = device ] && [ ! -f "$PRODUCTION_CUTOVER_MARKER" ]; then
  echo 'Codex device authentication is pending; provider preflight remains deferred.'
fi

# A root-only marker on the persistent disk distinguishes a staged VM from an
# explicitly cut-over production runtime. Upgrades of an activated runtime
# must pass the exact provider/MCP preflight before the services are restarted
# on the new immutable release. A fresh or unapproved VM remains stopped.
if [ -f "$PRODUCTION_CUTOVER_MARKER" ]; then
  if ! systemctl start nova-agent-preflight.service; then
    rm -f "$RUNTIME_PREFLIGHT_MARKER" "$ZOOM_PREFLIGHT_MARKER"
    systemctl disable --now nova-command-center-healthcheck.timer >/dev/null 2>&1 || true
    systemctl disable --now nova-command-center.service nova-slack-bridge.service nova-zoom-monitor.timer nova-support-shift-reminders.timer >/dev/null 2>&1 || true
    echo 'Activated runtime preflight failed; production services were stopped.' >&2
    exit 1
  fi
  install -m 0600 -o root -g root /dev/null "$RUNTIME_PREFLIGHT_MARKER"
  systemctl enable nova-command-center.service nova-slack-bridge.service
  systemctl enable nova-command-center-healthcheck.timer
  systemctl restart nova-command-center.service
  systemctl restart nova-command-center-healthcheck.timer
  systemctl restart nova-slack-bridge.service
  if [ -f "$ZOOM_PREFLIGHT_MARKER" ]; then
    systemctl enable nova-zoom-monitor.timer nova-support-shift-reminders.timer
    systemctl restart nova-zoom-monitor.timer
    systemctl restart nova-support-shift-reminders.timer
  else
    systemctl disable --now nova-zoom-monitor.timer nova-support-shift-reminders.timer >/dev/null 2>&1 || true
    echo 'Zoom live preflight is degraded; the Zoom monitor remains disabled.' >&2
  fi
  echo 'Activated production runtime restarted after verified preflight.'
else
  rm -f "$RUNTIME_PREFLIGHT_MARKER" "$ZOOM_PREFLIGHT_MARKER"
  systemctl disable --now nova-command-center-healthcheck.timer >/dev/null 2>&1 || true
  systemctl disable --now nova-command-center.service nova-slack-bridge.service nova-zoom-monitor.timer nova-support-shift-reminders.timer >/dev/null 2>&1 || true
fi
echo "Nova private agent runtime bootstrap completed for $SOURCE_COMMIT"
