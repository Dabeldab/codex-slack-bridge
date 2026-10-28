# Deep Operational Investigation

Use this workflow when the operator asks why something happened, whether a
transaction is internally consistent, or for more than a surface-level lookup.

## Start with the bounded workflow

1. Resolve the exact customer, account, database, ticket, and record IDs from
   authoritative links. Do not guess from a display name.
2. Check the matching entry in `config/pipeline-registry.json` and
   `config/tool-fast-paths.json`. Call the narrow typed read operation first.
3. Inspect the complete bounded transaction neighborhood: parent and child
   records, line items, quantities, discounts, totals, payments, configuration,
   attachments, related events, and applicable application behavior.
4. Reconcile the arithmetic and chronology. Separate stored facts, calculations
   reconstructed from those facts, and inferences that depend on current
   settings, historical settings that were not preserved, or source code.
5. Continue through a narrow follow-up read or an acknowledged specialist
   handoff when the first result identifies a real gap. A row lookup or status
   alone is not a diagnosis.

For invoice spare, below-minimum approval, `SpareInvoiceID`, or negative-spare
questions, follow `docs/agent-tools/nova-invoice-spare.md` and call
`nova_sql_invoice_spare_investigation` before generic SQL. Review every returned
invoice, line, payment, coupon, location setting, and spare link. Never alter
invoice financial history during diagnosis.

## Report the result

Internally, give the short causal sequence, exact numbers, evidence boundary,
and next safe action. In a customer message or ticket update, include only the
verified reason and useful next step in plain language. Do not expose SQL,
tools, agents, handoffs, retries, internal paths, or troubleshooting narration,
and do not repeat the problem already stated by the customer.
