<!-- AgentChat/coding_agent 2026-08-03T19:37:00Z -->

# Fixed Oklahoma HAWAII Catalog Replacement

This reviewed operation is a one-purpose exception to the generic Nova SQL
DELETE prohibition. It cannot accept a caller-selected account, database,
category, table, mapping, row, statement, or SQL string.

Fixed contract:

- read-only source: `POS_unique_lifestyle_llc`
- writable target: `POS_oklahoma`
- selected source category: the unique `HAWAII` row, ID 87
- stable execution key: `rory-8702-oklahoma-hawaii-full-replace-v1`
- reviewed source result: 26 products, one category, zero required wholesaler
  rows
- reviewed target baseline: 723 products, six categories, one wholesaler,
  zero external catalog dependencies, and zero incoming product-ID collisions

`nova_sql_oklahoma_hawaii_catalog_replace_preview` recomputes the full source,
target, schema, fingerprint, trigger, foreign-key, and dependency contract. Any
drift blocks execution. `nova_sql_oklahoma_hawaii_catalog_replace_execute`
requires the exact preview hash, creates immutable full backups of all three
target catalog tables, and performs the target delete-and-copy in one
serializable transaction. `nova_sql_oklahoma_hawaii_catalog_replace_status`
is the read-only reconciliation route after an uncertain execute.

Completion requires authoritative readback of exactly 26 HAWAII products, one
HAWAII category, zero wholesalers, zero non-HAWAII rows, and zero unsupported
or orphaned references. The operation never changes the source and does not
alter the generic guarded executor or expose reusable DELETE capability.
