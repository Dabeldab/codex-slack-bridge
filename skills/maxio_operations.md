# Maxio / Chargify Operations

Use for Maxio customers, subscriptions, invoices, components, allocations,
payment profiles, refunds, credits, cancellations, and reactivation.

- Route through the registered Maxio MCP when healthy; otherwise use the native
  Advanced Billing API and established Rainfall client. Browser is UI-only fallback.
- Resolve the exact customer, subscription, invoice, and related Salesforce/Nova
  identifiers before a mutation.
- Keep reads, previews, refunds, credits, voids, allocation changes, and
  cancellation as distinct operations.
- Preview monetary/allocation effects when supported, use a stable idempotency
  key, perform only the authorized change, and read back the object plus related
  collection afterward.
- Recover missing location payments only through
  `maxio_component_payment_recovery_preview/apply`. Bind the exact recovery
  location IDs, component, charge quantity, unit rate cents, authorized total,
  and Billing ticket. The target subscription may contain only those recovery
  locations. The typed pair downgrades with no credit, reallocates at full charge
  with `initiate_dunning=true`, then restores the recurring quantity with no
  credit. When other already-paid locations share the subscription, first create
  a separate future-billed Maxio subscription, create/sync its Salesforce Billing
  Account and Billing Schedule, link and verify every recovery location, and set
  exact Maxio location metadata. Do not use a generic or one-time charge, expose
  unrelated locations to dunning, or retry after a charge attempt.
- Follow the billing-location or billing-refund workflow skill when those task
  families apply; this skill supplies routing, not a replacement for their rules.
