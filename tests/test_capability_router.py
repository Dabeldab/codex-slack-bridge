from __future__ import annotations

import json

from codex_slack_bridge.capabilities import CapabilityRouter


def _registry(tmp_path):
    path = tmp_path / "tools.json"
    path.write_text(
        json.dumps(
            {
                "tools": {
                    "chargify": {
                        "display_name": "Chargify / Maxio",
                        "aliases": ["maxio", "subscription"],
                        "primary_agents": ["billing_agent"],
                        "credentials": {
                            "required_any": [
                                ["CHARGIFY_API_KEY", "MAXIO_API_KEY"],
                                ["CHARGIFY_BASE_URL", "CHARGIFY_SUBDOMAIN"],
                            ]
                        },
                    },
                    "gmail": {"display_name": "Gmail", "aliases": ["email", "inbox"]},
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_router_returns_only_task_relevant_capabilities(tmp_path):
    router = CapabilityRouter(_registry(tmp_path), tmp_path / "state.json")
    routes = router.select("Check this Maxio subscription", agent_name="billing_agent")
    assert [route.key for route in routes] == ["chargify"]
    assert routes[0].auth_ready is False
    assert len(routes[0].missing_credential_groups) == 2


def test_router_reports_ready_when_each_required_group_has_one_name(tmp_path):
    router = CapabilityRouter(_registry(tmp_path), tmp_path / "state.json")
    routes = router.select(
        "Check this Chargify subscription",
        available_names={"MAXIO_API_KEY", "CHARGIFY_BASE_URL"},
    )
    assert routes[0].auth_ready is True


def test_router_circuit_breaker_opens_and_success_resets_it(tmp_path):
    router = CapabilityRouter(_registry(tmp_path), tmp_path / "state.json")
    for _ in range(3):
        router.record_failure("chargify", "temporary failure", threshold=3)
    assert router.select("Maxio subscription")[0].circuit_open is True
    router.record_success("chargify")
    route = router.select("Maxio subscription")[0]
    assert route.circuit_open is False
    assert route.last_success_utc
