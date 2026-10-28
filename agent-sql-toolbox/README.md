# Agent SQL Toolbox

AgentChat/coding_agent 2026-07-08T20:31:00Z

Reusable Nova SQL scripts generalized from the local SSMS script folders:

- `C:\Users\redma\OneDrive\Documents\SQL Server Management Studio`
- `C:\Users\redma\OneDrive\Documents\SQL Server Management Studio 22`

The originals are intentionally left untouched. These copies remove hardcoded
account names where practical, use parameters for account/date/location scope,
and default write-capable scripts to dry-run mode.

## Agent Rules

- Connect to the intended `POS_<Company_Username__c>` database before running a
  report script.
- Treat every script under `migration/` and `maintenance/` as write-capable even
  when `@Execute = 0`. Live writes require explicit user authorization in the
  current conversation.
- Do not trust the templates blindly. Run `schema/pos_schema_preflight.sql`
  against the actual target POS database first and adapt any mismatch before
  using a report or migration template.
- Migration templates never commit by default. `@Execute = 1` runs a rollback
  preview unless `@CommitChanges = 1` and the exact commit phrase are also set.
- Maintenance templates never execute by default. Index maintenance requires
  `@Execute = 1` and the exact execution phrase.
- Prefer report scripts first. Use migration scripts only after a read-only
  preflight and a narrow change plan.
- Never paste customer credentials, SQL passwords, or connection strings into
  these files.
- Keep source SSMS folders read-only. Make future reusable copies here.

## Scripts

Relationship map:

- `SCHEMA_MAP.md` - human-readable Nova POS relationship map and support-agent
  workflow for invoice, customer, product, inventory, refund, layaway, employee,
  and appointment investigations.
- `schema/pos_relationship_discovery.sql` - read-only catalog discovery for
  actual table presence, expected relationships, declared foreign keys, child
  column index coverage, and inferred ID relationships in the current account
  database.

Reports:

- `schema/pos_schema_preflight.sql` - read-only actual-schema compatibility
  check for toolbox scripts.
- `reports/core_integrity_audit.sql` - read-only audit for common support data
  issues such as orphan invoice details, missing payment method/details,
  inventory/product mismatches, appointment customer mismatches, and refund
  payment gaps.
- `reports/customer_purchase_detail.sql` - generalized customer/product/payment
  purchase export.
- `reports/inventory_by_location.sql` - inventory, product, category, and
  barcode details by location.
- `reports/inventory_count_detail.sql` - submitted inventory count detail.
- `reports/appointment_duration.sql` - appointment duration export.
- `reports/duplicate_product_barcodes.sql` - duplicate or suspicious barcode
  scan.
- `reports/employee_commission_summary.sql` - sales commission, hours,
  reimbursements, and deductions summary.

Maintenance and migration:

- `maintenance/rebuild_fragmented_indexes.sql` - dynamic index maintenance
  generator with dry-run default.
- `migration/account_clone_preflight.sql` - read-only source/target account
  clone readiness checks.
- `migration/copy_location_settings_template.sql` - guarded copy of operational
  location settings.
- `migration/copy_products_template.sql` - guarded product/category/wholesaler
  copy using natural-key matching.

## Source Notes

The first useful set was generalized from scripts such as `Customers, how much
they paid.sql`, `Inventory By location.sql`, `Inventory Count.sql`,
`Appointment with Duration.sql`, `Duplicate products.sql`, `Calculate
Commissions for all employees by date and location.sql`, `Reindex Account.sql`,
`database-copy-script.sql`, `Copy location settings.sql`, and
`CopyProducts.sql`.
