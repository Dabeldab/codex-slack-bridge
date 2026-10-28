# Instyle set-based demo copy

<!-- AgentChat/coding_agent 2026-08-05T10:00:00Z -->

Use this operation only for the fixed tickets 347072 and 347073 test:

- read-only source A: `LE_BOUTIQUE_INSTYLE`
- read-only source B: `Instyle_Fragrance`
- writable disposable target: `DEMO_NOVA_CAFE`

The operation packages Alex's SQL account-copy pattern as one database-side,
set-based batch. Python does not fetch, transform, or relay business rows. The
fixed broker credential can read the two source databases and write the demo
target, but the SQL contains no source DML and every DML target is the current
`POS_DEMO_NOVA_CAFE` database.

## Taylor runbook

1. Call `nova_sql_capabilities` and require
   `instyleDemoSyncConfigured=true` and
   `instyleDemoSyncExecutionMode=single_database_side_set_based_sql`.
2. Call `nova_sql_instyle_demo_sync_preview` with one stable idempotency key.
3. Confirm the result names the two fixed read-only sources, the fixed demo
   target, `single_database_side_set_based_sql`, and
   `coldHistoryAction=copy_missing_rows_set_based`.
4. Call `nova_sql_instyle_demo_sync_execute` with the same key and exact
   preview hash.
5. Read the completion receipt. Do not fall back to generic SQL.
6. If execute reports `execution_failed_reconciliation_required`, call
   `nova_sql_instyle_demo_sync_status` before any retry.

The expected run time is minutes. A long-running Python row-copy process is not
part of this operation.

## What the SQL does

- Builds a source-qualified product crosswalk from the two Nova catalogs.
- Deduplicates the normalized `ProductName + BarcodeNumber + BarcodeNumber2 +
  SKU` key and selects `ProductID DESC` with a deterministic source tie-breaker.
- Copies compatible business tables with server-side `INSERT ... SELECT` and
  transformed-key `NOT EXISTS` checks, so reruns insert only missing rows.
- Copies missing `InventoryHistoryItem` rows on SQL Server instead of relaying
  tens of millions of rows through Python.
- Creates exactly 107 populated, inactive Nova products for the 142 qualifying
  invoice lines whose historical Product rows are missing.
- Leaves the 11 source invoice-product rows without a valid invoice quarantined
  and excludes them from the copy.
- Repairs the 15 known Nova product-reference tables. Missing non-invoice
  product parents retain a negative, source-qualified reference instead of
  creating unapproved placeholder products.
- Repairs the verified blank `InvoiceID` values in `Invoice_Employees` and
  `Invoice_Payments`.

## Fixed safety boundary

- The tool accepts only an idempotency key and preview hash.
- It accepts no account, database, table, mapping, row, statement, or SQL input.
- Both source names and the only writable target are embedded in the reviewed
  SQL resource.
- The developer credential is mounted only into Taylor's isolated broker; its
  username and password are never exposed to Taylor, Command Center, logs, or
  tool output.
- `DEMO_NOVA_CAFE` is not cleared and no demo backup is created.
- Source schema and target schema/state are hash-locked between preview and
  execute. Ordinary new source rows do not invalidate the preview.
- The target transaction rolls back on the first failed validation.

## Required completion readback

The receipt must show:

- `sourceDatabasesReadOnly=true`
- `targetBackupRequired=false`
- `copyMode=single_database_side_set_based_sql`
- zero nonblank normalized product-key duplicates
- zero positive product-reference orphans
- zero blank `InvoiceID` values in `Invoice_Products`
- exactly 107 qualified placeholder products covering 142 copied invoice lines
- exactly 11 invoice-less source rows still quarantined from the copy
- zero missing `ProductName`, `SKU`, or `BarcodeNumber` values on inactive
  missing-product rows
- 44 locations and four regions
- target `InventoryHistoryItem` coverage at least equal to both source counts
  captured by the SQL run
- `postWriteReadbackVerified=true`

For a future customer target, publish a new typed operation only after its exact
target and collision-safe offsets are previewed. Reuse this SQL asset and
database-side execution pattern; do not restore Python row transport.
