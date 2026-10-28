"""Guard that GitHub relay WIF identity never exceeds Google's service-account ID limit."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT = (ROOT / "deploy/gcp/deploy-github-agent-relay.ps1").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github/workflows/github-agent-relay.yml").read_text(encoding="utf-8")


def test_github_relay_invoker_name_is_valid_and_consistent():
    account = re.search(r"RELAY_INVOKER_SERVICE_ACCOUNT: ([a-z0-9-]+)@", WORKFLOW)
    default = re.search(r'\$InvokerServiceAccountName = "([a-z0-9-]+)"', DEPLOYMENT)
    assert account and default
    assert account.group(1) == default.group(1) == "nova-github-relay-invoker"
    assert re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", account.group(1))
    assert len(account.group(1)) <= 30


def test_deployment_rejects_oversized_service_account_ids():
    assert 'Invalid Google service-account ID' in DEPLOYMENT
    assert '$RuntimeServiceAccountName, $InvokerServiceAccountName' in DEPLOYMENT
    assert "assertion.ref == 'refs/heads/main'" in DEPLOYMENT
    assert "roles/iam.workloadIdentityUser" in DEPLOYMENT
    assert "roles/run.invoker" in DEPLOYMENT
