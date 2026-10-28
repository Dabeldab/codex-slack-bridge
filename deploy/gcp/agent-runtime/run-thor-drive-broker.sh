#!/bin/sh
set -eu

lane="${1:-}"
[ "$lane" = claude_agent ] || { echo "invalid Thor Drive lane" >&2; exit 64; }
cd /

workspace_adc=/run/nova-secrets/google-workspace-adc
test -s "$workspace_adc" || { echo "required Thor Drive broker credential is unavailable" >&2; exit 78; }

export SCOPED_AGENT_LANE=claude_agent
export RORY_GOOGLE_WORKSPACE_ADC_PATH="$workspace_adc"

exec /opt/nova/venv/bin/python -m scoped_operations_mcp.operator_services_server
