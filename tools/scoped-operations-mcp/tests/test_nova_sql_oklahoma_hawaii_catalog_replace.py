from __future__ import annotations

# AgentChat/coding_agent 2026-08-03T19:31:00Z

from copy import deepcopy

import pytest

from scoped_operations_mcp import nova_sql_oklahoma_hawaii_catalog_replace as operation
from scoped_operations_mcp.nova_sql_client import WRITE_FORBIDDEN_SQL


FINAL_READBACK = {
    "products": 26,
    "categories": 1,
    "wholesalers": 0,
    "nonHawaiiProducts": 0,
    "nonHawaiiCategories": 0,
    "orphanCategoryReferences": 0,
    "orphanWholesalerReferences": 0,
    "productFamilyReferences": 0,
    "createdByReferences": 0,
    "productsMissingFromSource": 0,
    "sourceProductsMissingFromTarget": 0,
}


def _manifest():
    schema = {
        "Products": list(operation.PRODUCT_COLUMNS),
        "Products_Categories": list(operation.CATEGORY_COLUMNS),
        "Products_Wholesalers": list(operation.WHOLESALER_COLUMNS),
    }
    fingerprint = "a" * 64
    return {
        "source": {
            "database": operation.SOURCE_DATABASE,
            "categoryRows": [[87, "HAWAII", -1, "00000000-0000-0000-0000-000000000001"]],
            "counts": dict(operation.EXPECTED_SOURCE_COUNTS),
            "missingWholesalerReferences": 0,
            "productFamilyReferences": 0,
            "createdByReferences": 0,
            "minProductId": 1434,
            "maxProductId": 1606,
            "schema": deepcopy(schema),
            "fingerprints": {
                "products": fingerprint,
                "categories": fingerprint,
                "wholesalers": fingerprint,
            },
        },
        "target": {
            "database": operation.TARGET_DATABASE,
            "counts": dict(operation.EXPECTED_TARGET_COUNTS),
            "productIdCollisions": 0,
            "schema": deepcopy(schema),
            "fingerprints": {
                "products": fingerprint,
                "categories": fingerprint,
                "wholesalers": fingerprint,
            },
            "dependencyColumns": [
                list(row) for row in sorted(operation.EXPECTED_DEPENDENCY_COLUMNS)
            ],
            "foreignKeys": [list(row) for row in sorted(operation.EXPECTED_FOREIGN_KEYS)],
            "externalDependencyCounts": {
                "Inventory.ProductID": 0,
                "Invoice_Products.ProductID": 0,
            },
            "triggers": [],
        },
    }


class FakeCursor:
    rowcount = -1

    def __init__(self):
        self.commands = []

    def execute(self, sql, parameters=None):
        self.commands.append((" ".join(str(sql).split()), list(parameters or [])))
        return self


class FakeConnection:
    def __init__(self):
        self._cursor = FakeCursor()
        self.timeout = 0
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_fixed_contract_has_no_caller_selected_destructive_scope():
    assert operation.DELETE_POLICY_EXCEPTION == (
        "fixed_oklahoma_hawaii_catalog_replace_only"
    )
    assert operation.CALLER_SELECTED_DELETE_ALLOWED is False
    assert operation.SOURCE_USERNAME == "unique_lifestyle_llc"
    assert operation.TARGET_USERNAME == "oklahoma"
    assert operation.CATEGORY_NAME == "HAWAII"
    assert operation.REQUIRED_IDEMPOTENCY_KEY == (
        "rory-8702-oklahoma-hawaii-full-replace-v1"
    )
    assert WRITE_FORBIDDEN_SQL.search("DELETE FROM dbo.Products")
    with pytest.raises(operation.OklahomaHawaiiCatalogReplaceScopeError):
        operation._idempotency_key("another-operation-key")


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value["source"]["counts"].update(products=27),
        lambda value: value["target"]["counts"].update(products=722),
        lambda value: value["target"].update(productIdCollisions=1),
        lambda value: value["target"]["externalDependencyCounts"].update(
            {"Inventory.ProductID": 1}
        ),
        lambda value: value["target"].update(triggers=[["dbo", "Products", "x", 0]]),
    ],
)
def test_manifest_rejects_any_reviewed_count_dependency_or_trigger_drift(change):
    manifest = _manifest()
    change(manifest)
    with pytest.raises(operation.OklahomaHawaiiCatalogReplaceScopeError):
        operation._validate_manifest(manifest)


def test_execute_is_one_transaction_with_backups_and_post_commit_readback(
    monkeypatch,
    tmp_path,
):
    manifest = _manifest()
    connections = []

    def connect(_read_only):
        connection = FakeConnection()
        connections.append(connection)
        return connection

    monkeypatch.setattr(operation, "_build_manifest", lambda _cursor, lock_tables: manifest)
    monkeypatch.setattr(operation, "_verify_database_binding", lambda _cursor: None)
    monkeypatch.setattr(operation, "_acquire_lock", lambda _cursor, _key: None)
    monkeypatch.setattr(
        operation,
        "_create_backups",
        lambda _cursor, _hash, _manifest_value: [
            {"sourceTable": "dbo.Products", "backupTable": "fixed", "rowCount": 723}
        ],
    )
    monkeypatch.setattr(
        operation,
        "_replace_catalog",
        lambda _cursor: {
            "deletedProducts": 723,
            "deletedCategories": 6,
            "deletedWholesalers": 1,
            "insertedProducts": 26,
            "insertedCategories": 1,
            "insertedWholesalers": 0,
        },
    )
    monkeypatch.setattr(operation, "_readback", lambda _cursor: dict(FINAL_READBACK))

    gateway = operation.OklahomaHawaiiCatalogReplaceOperation(
        connect=connect,
        state_dir=tmp_path,
    )
    preview = gateway.preview(idempotency_key=operation.REQUIRED_IDEMPOTENCY_KEY)
    result = gateway.execute(
        idempotency_key=operation.REQUIRED_IDEMPOTENCY_KEY,
        preview_hash=preview["previewHash"],
    )

    write_connection = connections[1]
    statements = [sql for sql, _parameters in write_connection._cursor.commands]
    assert "SET XACT_ABORT ON" in statements
    assert "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE" in statements
    assert "BEGIN TRANSACTION" in statements
    assert write_connection.commits == 1
    assert write_connection.rollbacks == 0
    assert result["transactionCommitted"] is True
    assert result["postCommitReadbackVerified"] is True
    assert result["readback"] == FINAL_READBACK


def test_execute_rolls_back_before_mutation_when_manifest_drifts(monkeypatch, tmp_path):
    manifest = _manifest()
    connections = []
    calls = {"manifest": 0, "replace": 0}

    def connect(_read_only):
        connection = FakeConnection()
        connections.append(connection)
        return connection

    def build(_cursor, lock_tables):
        calls["manifest"] += 1
        current = deepcopy(manifest)
        if lock_tables:
            current["target"]["fingerprints"]["products"] = "b" * 64
        return current

    monkeypatch.setattr(operation, "_build_manifest", build)
    monkeypatch.setattr(operation, "_verify_database_binding", lambda _cursor: None)
    monkeypatch.setattr(operation, "_acquire_lock", lambda _cursor, _key: None)
    monkeypatch.setattr(operation, "_readback", lambda _cursor: dict(FINAL_READBACK))
    monkeypatch.setattr(
        operation,
        "_replace_catalog",
        lambda _cursor: calls.update(replace=calls["replace"] + 1),
    )

    gateway = operation.OklahomaHawaiiCatalogReplaceOperation(
        connect=connect,
        state_dir=tmp_path,
    )
    preview = gateway.preview(idempotency_key=operation.REQUIRED_IDEMPOTENCY_KEY)
    with pytest.raises(operation.OklahomaHawaiiCatalogReplaceScopeError):
        gateway.execute(
            idempotency_key=operation.REQUIRED_IDEMPOTENCY_KEY,
            preview_hash=preview["previewHash"],
        )

    assert connections[1].rollbacks == 1
    assert connections[1].commits == 0
    assert calls["replace"] == 0
