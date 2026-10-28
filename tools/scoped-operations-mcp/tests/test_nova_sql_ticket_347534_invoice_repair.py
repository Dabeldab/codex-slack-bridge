from __future__ import annotations

import inspect

from scoped_operations_mcp.nova_sql_ticket_347534_invoice_repair import (
    PROTECTED_INVOICE_ID,
    Ticket347534InvoiceRepairOperation,
    _validate_readback,
)


def test_fixed_repair_preserves_august_invoice_and_accepts_exact_readback() -> None:
    manifest = {
        "TargetInvoices": 1179,
        "BadInvoices": 480,
        "ProtectedInvoice": 1,
        "ProtectedInvoiceEmployees": 1,
        "ProtectedInvoicePayments": 2,
        "ProtectedInvoiceProducts": 1,
        "ProtectedInvoiceNotes": 0,
        "ProtectedInvoiceProductCommissions": 1,
    }
    readback = {
        "TargetInvoices": 699,
        "WrongSourceInvoicesRemaining": 0,
        "ProtectedInvoice": 1,
        "ProtectedInvoiceEmployees": 1,
        "ProtectedInvoicePayments": 2,
        "ProtectedInvoiceProducts": 1,
        "ProtectedInvoiceNotes": 0,
        "ProtectedInvoiceProductCommissions": 1,
        "MissingSourceLocationInvoices": 1,
        "OrphanInvoiceEmployees": 0,
        "OrphanInvoicePayments": 0,
        "OrphanInvoiceProducts": 0,
        "OrphanInvoiceNotes": 0,
        "OrphanInvoiceProductCommissions": 0,
    }

    _validate_readback(readback, manifest)
    assert PROTECTED_INVOICE_ID == 73242


def test_fixed_repair_does_not_open_a_nested_sql_transaction() -> None:
    source = inspect.getsource(Ticket347534InvoiceRepairOperation.execute)

    assert "BEGIN TRANSACTION" not in source
    assert "self._connect(False)" in source
