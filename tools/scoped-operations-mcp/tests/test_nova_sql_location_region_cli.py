from __future__ import annotations

import pytest

from scoped_operations_mcp.nova_sql_client import NovaSqlScopeError
from scoped_operations_mcp.nova_sql_location_region_cli import (
    execute_location_region_update,
)


class FakeClient:
    def __init__(self):
        self.calls = []

    def update_location_region(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "ok": True,
            "status": "completed",
            "readback": {
                "locationId": kwargs["location_id"],
                "regionId": kwargs["region_id"],
            },
        }


def test_cli_dispatches_only_the_fixed_location_region_operation():
    client = FakeClient()

    result = execute_location_region_update(
        {
            "action": "update_location_region",
            "companyUsername": "shoe_mgk_brandon",
            "locationId": 41,
            "regionId": 6,
            "idempotencyKey": "bridge-job:6226",
        },
        client=client,
    )

    assert result["readback"] == {"locationId": 41, "regionId": 6}
    assert client.calls == [
        {
            "company_username": "shoe_mgk_brandon",
            "location_id": 41,
            "region_id": 6,
            "idempotency_key": "bridge-job:6226",
        }
    ]


def test_cli_rejects_arbitrary_action_and_invalid_target():
    client = FakeClient()

    with pytest.raises(NovaSqlScopeError, match="Unsupported"):
        execute_location_region_update(
            {"action": "execute_sql"},
            client=client,
        )
    with pytest.raises(NovaSqlScopeError, match="companyUsername"):
        execute_location_region_update(
            {
                "companyUsername": "bad-name",
                "locationId": 41,
                "regionId": 6,
                "idempotencyKey": "bridge-job:6226",
            },
            client=client,
        )
    assert client.calls == []
