# Nova SQL

For invoice spare, below-minimum approval, or linked-invoice questions, use the
fixed `nova_sql_invoice_spare_investigation` operation and follow
`docs/agent-tools/nova-invoice-spare.md`. Do not substitute a surface-level
invoice header lookup or current-product-only calculation.

## Ownership

- Alex, Jamie, and Taylor may use the bounded read and preflight operations.
- Taylor (`coding_agent`) alone owns Nova SQL mutations.
- Agents never receive database passwords, connection strings, or arbitrary SQL
  through the table-recovery tools.

## Guarded Data Movement

For regular copies between current or future accounts, use Taylor's typed
account-copy tools before the lower-level statement executor:

1. Resolve the exact source and target `Company_Username__c` values.
2. Describe each eligible business table with selected columns, stable business
   match columns, a typed source filter, `insert_missing`, `update_existing`, or
   `upsert` mode, and any logical relationships not declared as database foreign
   keys.
3. Call `nova_sql_account_copy_preview`. It accepts no SQL. The broker reads the
   live schemas, rejects protected/internal tables and secret columns, builds
   source-to-target integer-key crosswalks, deduplicates stable business keys,
   orders dependencies, checks collisions and unresolved references, and stores
   an immutable server-owned plan.
4. Review the table counts, dedupe counts, dependency order, relationship count,
   expected affected rows, and exact `planId`.
5. When the exact copy is authorized, call
   `nova_sql_account_copy_execute(plan_id=<planId>)`. The executor rejects any
   source, target, schema, scope, count, or relationship drift, creates a full
   copy of every changed target table, commits in one transaction, and verifies
   target rows and copied relationships after commit.
6. If execution is uncertain, call `nova_sql_account_copy_status` before any
   retry. Never run a handed-off `.sql` file directly.

Filters are structured equality/range/list/null predicates and bounded nested
`exists` scopes. The tool works from discovered schema rather than an account or
table allowlist, but it intentionally excludes credential, authentication,
secret, internal broker, generated, rowversion, and incompatible columns. A
relationship-safe copy currently requires the same single integer primary key
in source and target; unsupported table shapes fail during preview without a
write.

## Fixed Location Layaway Enablement

Use `nova_sql_location_layaway_enable` when a verified request asks to enable
layaway for exact locations on one Nova account. Supply only:

- the exact Salesforce-resolved `company_username`;
- one to 100 unique positive `location_ids`; and
- a stable source-job or ticket-based `idempotency_key`.

The tool does not accept SQL or setting values. It always ensures one
`dbo.Locations_Layaways` row per requested location with:

- `ExpirationDay = 90`
- `IsChangeLayawayExpirationDate = 0`
- `MinFirstPayment = 10`
- `Disclaimer = Please come back and ask for our returning customer discount!`

Before writing, the broker validates the exact database binding, every
`dbo.Locations` row, the target table and required writable columns, permissions,
the disclaimer length, absence of target DML triggers, and any additional
required columns. If all requested rows already match, it returns a verified
no-op. Otherwise it creates and row-count-verifies a complete
`dbo.Locations_Layaways` backup, updates only mismatched requested rows, inserts
only missing requested rows, commits one application-locked transaction, and
reads every row back. An uncertain commit is non-retryable until its durable
receipt and live rows are reconciled.

Taylor's normal `nova_sql_write_preview` and `nova_sql_execute_guarded` pair
also handles reusable cross-account data movement. Supply the exact writable
`company_username` plus up to eight exact `source_company_usernames`.
Use Taylor-only `nova_sql_data_move_read` first for the bounded cross-account
candidate/count SELECT needed to establish the exact mapping and affected rows.

The immutable statement list may use:

- `INSERT INTO dbo.<target> (<explicit columns>) SELECT ...` from the approved
  `POS_<source>.dbo.<table>`;
- `UPDATE <target alias> SET ... FROM dbo.<target> ... JOIN
  POS_<source>.dbo.<table> ... WHERE ...`;
- local `#temporary` staging tables for mappings and crosswalks;
- explicit ranges and filters through parameters;
- a two-statement UPDATE-then-INSERT upsert pattern; and
- `identity_insert=true` on a permanent INSERT when preserving an identity is
  required and the target metadata and permissions support it.

Preview must include the complete statement list, exact affected-row count,
scalar postcondition query and value, stable idempotency key, exact target, and
exact source accounts. Execute repeats the identical fields and adds the exact
preview hash.

The broker binds the developer credential to the target, permits three-part
names only for the previewed sources, and syntactically prevents every source
write. It rejects DELETE, DROP, TRUNCATE, MERGE, arbitrary ALTER, dynamic SQL,
linked servers, unbounded UPDATE, and implicit-column INSERT. Before the first
target UPDATE or INSERT it creates and row-count-verifies a full backup of every
permanent target table. One application-locked transaction then performs the
set-based work and verifies the scalar both before and after commit.

Cross-account plans support up to 100 statements and 100,000,000 affected rows
so large table/range copies do not require Python row transport. The affected
count is still exact, not an estimate. Source database row totals are recorded
before and after execution as readback evidence; ordinary external source
growth is reported rather than treated as a target-write failure.

The generic executor still accepts no ALTER. Two separate no-SQL-input schema
migrations are broker-reviewed: the five-column `dbo.Locations` feature update,
and the fixed `POS_Natural_Balance_Insoles.dbo.Kit` parity update. The Kit tool
accepts only an idempotency key and preview hash, adds only the 15 approved
nullable Demo Nova Cafe-matching columns, backs up the table, and verifies the
12 pre-existing columns are unchanged.

## Guarded Table Recovery

Use this workflow when a point-in-time database copy has already been mounted as
`POS_<Company_Username__c>_RESTORE` and selected columns must be copied back to
the same table in the live `POS_<Company_Username__c>` database.

1. Resolve the exact Salesforce Account and `Company_Username__c`.
2. Determine the exact schema/table, the smallest unique non-null key column
   set, and only the columns that must be recovered.
3. Call `nova_sql_table_restore_preview` with:
   - `company_username`
   - `schema_name`
   - `table_name`
   - `key_columns`
   - `restore_columns`
   - a stable `idempotency_key`
4. Review:
   - source/live table and projection counts
   - shared, source-only, target-only, already matching, and candidate rows
   - fixed source/live database names
   - deterministic full-table safety-copy name
   - immutable `planHash`
5. Execute only when the operator has authorized the exact recovery. Call
   `nova_sql_table_restore_execute` with identical inputs and the exact
   `preview_hash`.
6. Require the completed receipt, exact affected-row count, unchanged target
   row count, zero remaining restore mismatches, and post-commit readback.

The broker resolves the `_RESTORE` source internally and opens isolated
read-only source and guarded live connections. It stages only the requested key
and restore columns in a connection-local temporary table. The live write is one
application-locked transaction that creates and verifies a complete target-table
copy before updating only uniquely matched existing rows.

## Safety Boundary

The operation:

- accepts identifiers and column lists, never SQL or a source database name;
- changes only caller-selected non-secret restore columns;
- never inserts, deletes, merges, alters schema, cleans backups, or changes
  source-only/target-only rows;
- requires unique non-null keys in both projections;
- rejects identity, computed, generated, rowversion, user-defined, and
  credential/secret restore columns;
- rejects temporal targets, enabled target DML triggers, enabled database DDL
  triggers, and cascading updates;
- caps snapshots at 250,000 rows per table and changes at 10,000 rows;
- rechecks source and live hashes after locking and before mutation;
- retains the deterministic safety copy and durable idempotency receipt;
- treats an uncertain commit as non-retryable until the receipt and live state
  are reconciled.

This is an update-only recovery tool. If the requested outcome requires adding
or removing rows, restoring schema, or recovering a table above the ceilings,
Taylor must build a separately typed operation with its own invariants.
