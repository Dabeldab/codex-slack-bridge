from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_gcp_runtime_exposes_broker_report_directory_to_agents_and_slack() -> None:
    bootstrap = (ROOT / "deploy/gcp/agent-runtime/bootstrap-private-runtime.sh").read_text(encoding="utf-8")
    launcher = (ROOT / "deploy/gcp/agent-runtime/run-maxio-broker.sh").read_text(encoding="utf-8")
    preflight = (ROOT / "deploy/gcp/agent-runtime/preflight.py").read_text(encoding="utf-8")
    config = yaml.safe_load((ROOT / "config/agents.gcp-runtime.yaml").read_text(encoding="utf-8"))

    assert "nova-maxio-reports" in bootstrap
    assert "/var/lib/nova/broker/maxio-reports" in bootstrap
    assert 'MAXIO_REPORT_OUTPUT_DIR="/var/lib/nova/broker/maxio-reports"' in launcher
    assert '"maxio_tax_report"' in preflight
    assert "/var/lib/nova/broker/maxio-reports" in config["defaults"]["slack_file_upload_allowed_roots"]


def test_tax_report_is_registered_in_agent_routing_contracts() -> None:
    capabilities = (ROOT / "config/agent-capabilities.yaml").read_text(encoding="utf-8")
    fast_paths = (ROOT / "config/tool-fast-paths.json").read_text(encoding="utf-8")
    pipelines = (ROOT / "config/pipeline-registry.json").read_text(encoding="utf-8")
    runbook = (ROOT / "docs/agent-tools/chargify-maxio.md").read_text(encoding="utf-8")

    assert capabilities.count("maxio.tax_report") == 2
    assert "maxio_tax_report" in fast_paths
    assert '"monthly_tax_report"' in pipelines
    assert "maxio_tax_report" in runbook
