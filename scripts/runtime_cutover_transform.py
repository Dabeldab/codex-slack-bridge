from __future__ import annotations

import argparse
from pathlib import Path


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def transform_bootstrap(text: str) -> str:
    text = _replace_once(text, 'CODEX_VERSION="$(metadata instance/attributes/nova-codex-version)"\nCODEX_AUTH_MODE="$(metadata instance/attributes/nova-codex-auth-mode)"\n', '', 'codex metadata variables')
    text = _replace_once(text, 'case "$CODEX_AUTH_MODE" in\n  access-token|device) ;;\n  *) echo "Unsupported Codex authentication mode" >&2; exit 1 ;;\nesac\n\n', '', 'codex auth mode validation')
    text = _replace_once(text, '(\n  umask 022\n  npm install --global "@openai/codex@$CODEX_VERSION"\n)\nchmod a+rx /usr/local/lib/node_modules /usr/local/lib/node_modules/@openai\nchmod -R a+rX /usr/local/lib/node_modules/@openai/codex\n/usr/local/bin/codex --version\n\n', '', 'codex installation block')
    start = '# Codex file-backed credentials are isolated by Linux identity and live on the\n'
    end = 'install -d -m 0711 -o root -g root /srv/nova/workspaces /srv/nova/sandboxes\n'
    if text.count(start) != 1 or text.count(end) != 1:
        raise RuntimeError('codex credential-home block anchors drifted')
    prefix, remainder = text.split(start, 1)
    _, suffix = remainder.split(end, 1)
    text = prefix + end + suffix
    old_scripts = 'run-cloud-ops-broker.sh run-operator-broker.sh run-thor-drive-broker.sh run-singapore-background.sh bootstrap-codex-auth.sh begin-codex-device-auth.sh run-slack-bridge.sh run-command-center.sh'
    new_scripts = 'run-cloud-ops-broker.sh run-operator-broker.sh run-thor-drive-broker.sh run-singapore-background.sh run-reasoning-relay-broker.sh run-slack-bridge.sh run-command-center.sh'
    text = _replace_once(text, old_scripts, new_scripts, 'runtime script install list')
    codex_sudo = '''nova-runtime ALL=(nova-rory) NOPASSWD: /usr/local/bin/codex *\nnova-runtime ALL=(nova-raw) NOPASSWD: /usr/local/bin/codex *\nnova-runtime ALL=(nova-claude) NOPASSWD: /usr/local/bin/codex *\nnova-runtime ALL=(nova-taylor) NOPASSWD: /usr/local/bin/codex *\nnova-runtime ALL=(nova-alex) NOPASSWD: /usr/local/bin/codex *\nnova-runtime ALL=(nova-jamie) NOPASSWD: /usr/local/bin/codex *\n\n'''
    text = _replace_once(text, codex_sudo, 'nova-runtime ALL=(nova-cloud-broker) NOPASSWD: /opt/nova/bin/run-reasoning-relay-broker\n\n', 'codex sudo rules')
    text = _replace_once(text, 'printf \'%s\\n\' "$CODEX_AUTH_MODE" > /etc/nova/codex-auth-mode\nchmod 0600 /etc/nova/codex-auth-mode\n\n', '', 'codex auth mode file')
    unit_start = "cat >/etc/systemd/system/nova-codex-auth.service <<'UNIT'\n"
    unit_end = "UNIT\n\ncat >/usr/local/sbin/nova-command-center-healthcheck <<'SCRIPT'\n"
    if text.count(unit_start) != 1 or text.count(unit_end) != 1:
        raise RuntimeError('codex auth service block anchors drifted')
    prefix, remainder = text.split(unit_start, 1)
    _, suffix = remainder.split(unit_end, 1)
    text = prefix + "cat >/usr/local/sbin/nova-command-center-healthcheck <<'SCRIPT'\n" + suffix
    text = text.replace('After=network-online.target nova-secrets.service nova-codex-auth.service', 'After=network-online.target nova-secrets.service')
    text = text.replace('After=network-online.target nova-command-center.service nova-secrets.service nova-codex-auth.service', 'After=network-online.target nova-command-center.service nova-secrets.service')
    text = _replace_once(text, 'Description=Nova Slack Socket Mode to Codex CLI bridge', 'Description=Nova Slack Socket Mode to ChatGPT Work reasoning relay', 'slack service description')
    text = _replace_once(text, 'Description=Read-only Nova cloud provider and CLI preflight', 'Description=Read-only Nova provider, broker, and reasoning-relay preflight', 'preflight description')
    text = _replace_once(text, 'ExecStart=/opt/nova/venv/bin/python /opt/nova/current/deploy/gcp/agent-runtime/preflight.py', 'ExecStart=/opt/nova/venv/bin/python /opt/nova/current/deploy/gcp/agent-runtime/preflight_chatgpt.py', 'preflight executable')
    text = _replace_once(text, 'systemctl enable nova-metadata-firewall.service nova-cloud-token.timer nova-secrets.service nova-codex-auth.service', 'systemctl enable nova-metadata-firewall.service nova-cloud-token.timer nova-secrets.service', 'systemd enable list')
    staged_block = '''systemctl start nova-codex-auth.service\nif [ "$CODEX_AUTH_MODE" = access-token ] && [ ! -f "$PRODUCTION_CUTOVER_MARKER" ]; then\n  systemctl start nova-agent-preflight.service || true\nelif [ "$CODEX_AUTH_MODE" = device ] && [ ! -f "$PRODUCTION_CUTOVER_MARKER" ]; then\n  echo 'Codex device authentication is pending; provider preflight remains deferred.'\nfi\n'''
    text = _replace_once(text, staged_block, '''if [ ! -f "$PRODUCTION_CUTOVER_MARKER" ]; then\n  systemctl start nova-agent-preflight.service || true\nfi\n''', 'codex auth startup block')
    forbidden = ('@openai/codex','/usr/local/bin/codex','nova-codex-auth.service','bootstrap-codex-auth','begin-codex-device-auth','CODEX_AUTH_MODE','CODEX_VERSION')
    remaining = [item for item in forbidden if item in text]
    if remaining:
        raise RuntimeError(f"bootstrap still contains forbidden runtime dependencies: {remaining}")
    return text


def transform_provisioner(text: str) -> str:
    text = _replace_once(text, '$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..\\..")).Path', 'if (-not $env:NOVA_RUNTIME_REPO_ROOT) { throw "NOVA_RUNTIME_REPO_ROOT is required by the ChatGPT runtime provisioner." }\n$RepoRoot = (Resolve-Path $env:NOVA_RUNTIME_REPO_ROOT).Path', 'repo root binding')
    text = _replace_once(text, '    [string]$CodexVersion = "0.144.4",\n', '', 'codex version parameter')
    text = _replace_once(text, '    [ValidateSet("access-token", "device")]\n    [string]$CodexAuthMode = "access-token",\n', '', 'codex auth parameter')
    text = _replace_once(text, '        @{ id = "nova-command-center-upstream-token"; path = "/run/nova-secrets/command-center-proxy-token"; owner = "root"; group = "root"; required = $true },\n        @{ id = "nova-agents-openai-api-key"; path = "/run/nova-secrets/openai-api-key"; owner = "nova-runtime"; group = "nova-runtime"; mode = "0440"; required = $false }\n', '        @{ id = "nova-command-center-upstream-token"; path = "/run/nova-secrets/command-center-proxy-token"; owner = "root"; group = "root"; required = $true }\n', 'openai api secret definition')
    codex_secret = '''    if ($CodexAuthMode -eq "access-token") {\n        $secretDefinitions += @{\n            id = "nova-agents-codex-access-token"\n            path = "/run/nova-secrets/codex-access-token"\n            owner = "root"\n            group = "root"\n            required = $true\n        }\n    }\n\n'''
    text = _replace_once(text, codex_secret, '', 'codex access-token secret')
    plan_block = '''        codexVersion = $CodexVersion\n        codexAuthMode = $CodexAuthMode\n        codexAuth = if ($CodexAuthMode -eq "device") {\n            "Interactive ChatGPT device-code login on the private VM; no Platform API key"\n        } else {\n            "ChatGPT workspace access token through Codex CLI; no Platform API key"\n        }\n        interactiveCodexAuthRequired = $CodexAuthMode -eq "device"\n'''
    text = _replace_once(text, plan_block, '        reasoningProvider = "chatgpt_work_relay"\n        openAiApiKeyRequired = $false\n', 'codex plan fields')
    text = _replace_once(text, ',nova-codex-version=$CodexVersion,nova-codex-auth-mode=$CodexAuthMode', '', 'codex metadata')
    text = _replace_once(text, '        codexAuthMode = $CodexAuthMode\n        interactiveCodexAuthRequired = $CodexAuthMode -eq "device"\n', '        reasoningProvider = "chatgpt_work_relay"\n        openAiApiKeyRequired = $false\n', 'codex result fields')
    forbidden = ('$Codex','nova-agents-codex-access-token','nova-codex-','openai-api-key','CodexAuthMode','CodexVersion')
    remaining = [item for item in forbidden if item in text]
    if remaining:
        raise RuntimeError(f"provisioner still contains forbidden runtime dependencies: {remaining}")
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=('bootstrap', 'provisioner'))
    parser.add_argument('source')
    parser.add_argument('destination')
    args = parser.parse_args()
    source = Path(args.source).read_text(encoding='utf-8')
    transformed = transform_bootstrap(source) if args.kind == 'bootstrap' else transform_provisioner(source)
    Path(args.destination).write_text(transformed, encoding='utf-8', newline='\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
