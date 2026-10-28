<!-- AgentChat/coding_agent 2026-07-23T20:26:28Z -->

# Fixed Instyle Demo Rebuild

This broker operation exists only for tickets 347072 and 347073.

## MCP surface

- Preview: `nova_sql_instyle_demo_rebuild_preview(idempotency_key)`
- Execute:
  `nova_sql_instyle_demo_rebuild_execute(idempotency_key, preview_hash)`
- Recover an abandoned post-reset execute:
  `nova_sql_instyle_demo_rebuild_recover(idempotency_key, preview_hash)`

There is no account, database, table, mapping, row, statement, or SQL input.
The fixed accounts are:

- source A: `LE_BOUTIQUE_INSTYLE` / `POS_LE_BOUTIQUE_INSTYLE`
- source B: `Instyle_Fragrance` / `POS_Instyle_Fragrance`
- target: `DEMO_NOVA_CAFE` / `POS_DEMO_NOVA_CAFE`

Every account is resolved through the scoped Salesforce client. The broker
opens one isolated connection for each source and the target. Tenant credentials
receive no cross-database rights and no credential or connection string is
returned by either tool.

## Preview contract

Preview uses SNAPSHOT transactions when the exact database has snapshot
isolation enabled. When it does not, the broker uses a short SERIALIZABLE
capture transaction, materializes the rows, and releases its read locks
immediately after that database is captured. The fallback never changes a
database option and does not hold source locks during the demo reset or load.
Both paths discover all non-system source tables and capture deterministic
schema, row-count, and row-content hashes. The required table set is the union
of both source schemas. The demo target must contain a compatible table and
column definition for every required source field.

`dbo.InventoryHistoryItem` is the fixed high-volume exception. Preview records
its count and a 4,096-bucket database fingerprint without materializing tens of
millions of rows in broker memory. Execute verifies the same fingerprint under
a short SERIALIZABLE source capture, streams transformed rows into
plan-specific internal target staging tables, releases the source transaction,
and only then enters the protected demo backup/reset/load phase. Partial
staging resumes by the declared primary-key prefix. `dbo.Log4Net` is the only
excluded source table because it is unkeyed application diagnostic output, not
a Nova business dependency; the exclusion is fixed in code and is returned by
preview and execute.

The immutable hash includes the exact source and target snapshots, required
tables, fixed accounts, product rules, reconciliation counts, the stable
idempotency key, and the protected-restore contract version. Reusing an
idempotency key returns the original preview. It does not silently replace that
preview with a newer source state.

There is one fixed source-to-target column exception:
`Instyle_Fragrance` has the nullable `decimal` field
`dbo.Employees_Hours.OriginalHours`, while `POS_DEMO_NOVA_CAFE` and
`POS_LE_BOUTIQUE_INSTYLE` do not. The field is not a primary key, foreign key,
identity, computed, or generated column. The broker copies every
`Employees_Hours` row and every matching target column, but it cannot copy the
`OriginalHours` values because the demo schema has no field for them. Preview
and execute return the source row count and populated `OriginalHours` count in
`fixedTargetSchemaOmissions`, and that evidence is part of the immutable plan
hash. Any other missing source table or column still fails closed. A change to
this field's type, nullability, or key role also fails closed; the operation
never adds or alters a target column.

## Mapping contract

- Source B non-product integer primary and foreign IDs are offset by
  1,000,000,000.
- Product matching never uses numeric ProductID across accounts.
- Products deduplicate only on normalized ProductName, BarcodeNumber,
  BarcodeNumber2, and SKU.
- The highest ProductID wins within one four-field group. Equal IDs are resolved
  deterministically by fixed source rank and canonical row hash.
- Every source ProductID maps through a source-qualified crosswalk.
- Invoice product references to missing/deleted products receive inactive,
  source-qualified placeholder products. In Nova's actual Products schema,
  inactive means `ProductIsAvailable = 0`; preview fails closed if that exact
  bit field or another recognized availability field is unavailable.
- The approved invoice-history scope creates placeholders only for the fixed
  missing Invoice_Products references. Missing product references in the other
  named Nova product-child tables remain explicit source-baseline exceptions:
  the broker maps them into separate negative source ranges, counts them, and
  rejects every unexpected positive product orphan.
- Invoice_Products rows with a NULL InvoiceID are excluded from active invoice
  data and written to the operation's deterministic quarantine table.
- Primary-key duplicates and foreign-key orphans are rejected before and after
  the load.

## Execute and recovery contract

Execution re-captures both source snapshots and rejects changed rows, schema, or
hashes before backup or reset. It takes a target application lock and requires
the protected demo restore gateway to prove all of these conditions:

1. A complete target backup was created.
2. Backup content was read back against the previewed target snapshot.
3. Rollback is available from the exact backup receipt.
4. The protected reset is bound to `POS_DEMO_NOVA_CAFE`.
5. The reset leaves the expected target schema ready for load.
6. The gateway gives tenant connections no cross-database rights and does not
   expose direct DELETE, DROP, ALTER, constraint-disable, or cross-database SQL
   operations.

The broker records atomic checkpoints for backup verification, reset completion,
load start, completion, and verified rollback. The data load and reconciliation
commit as one target transaction together with a target-local durable
idempotency receipt. That receipt lets a resumed process distinguish a committed
load from a transaction SQL Server rolled back after process loss. A pre-commit
failure rolls the transaction back. A failure after reset invokes the protected
rollback and refuses retry unless target restoration is read back.

If the broker process itself disappears after `reset_completed` or
`load_started`, the caller must not retry with generic SQL or create a new
preview over the reset target. Taylor calls
`nova_sql_instyle_demo_rebuild_recover` with the original key and preview hash.
The recovery tool opens only the fixed `DEMO_NOVA_CAFE` target, takes the same
application lock, rejects a changed target schema, checks for a durable commit,
re-verifies the complete private backup, restores the exact pre-run snapshot,
and writes a `rolled_back` checkpoint with readback. It never opens either
source database. Replaying recovery returns the existing verified rollback
receipt. After a verified rollback, a later rebuild must use a new preview and
new idempotency key so current source drift is captured explicitly.

The fixed operation uses a one-hour query timeout for its high-volume backup,
38-million-row target load, and post-load readback. It does not inherit the
generic Nova bounded-read timeout. This timeout is fixed in code and cannot be
selected by the caller; generic SQL executor limits remain unchanged.

After commit, every required target table and the quarantine table are counted,
primary-key duplicates and foreign-key orphans are checked, source/product/
quarantine reconciliation is compared to preview, and the same readback is
repeated post-commit.

The production broker defaults to its built-in target-scoped protected restore
gateway. It uses only the already resolved `POS_DEMO_NOVA_CAFE` tenant
connection. Ordinary tables are retained in the broker's `0600` private backup
receipt, while their rows are copied to deterministic, plan-specific internal
tables in the same demo database using the existing guarded full-table backup
pattern and row-count readback. The protected backup copy uses a fixed one-hour
query timeout so `dbo.InventoryHistoryItem` never inherits the generic
30-second bounded-read timeout. A retry reuses every existing backup table only
after its source and backup counts match the immutable target snapshot, then
continues at the first missing table. The error identifies that fixed target
table if a copy fails; target reset has not begun at that point. Rollback
restores those tables set-wise instead of materializing them in broker memory.
Backup aggregate readback uses the same exact-identifier table ordering as the
source snapshot, including Nova's mixed-case table names.
The backup tables are never deleted. The gateway clears only the immutable
required table set and can restore the exact previewed snapshot. It opens no
administrator or cross-database connection and accepts no caller-selected
target, table, or SQL.

`NOVA_SQL_INSTYLE_DEMO_RESTORE_HELPER` remains an optional operator override for
a separately installed root-owned implementation. When configured, the broker
retains the existing symlink, ownership, permission, environment, output-size,
and response-safety checks.

## Promotion checks

- All three tools are present only in `coding_agent`.
- All three tools are absent from support and billing lanes.
- Preview is read-only; execute is an idempotent guarded write.
- Tool schemas contain no SQL, account, database, table, or target override.
- Runtime preflight requires both tools in Taylor's broker and forbids them in
  the other Salesforce brokers.
- The built-in target-scoped restore gateway or an explicitly configured
  protected helper must pass the complete backup/reset/rollback capability
  contract before preview is considered ready.
- The generic SQL executor limits and validators remain unchanged.
