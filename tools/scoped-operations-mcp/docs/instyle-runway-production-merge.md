# Fixed Instyle Runway Production Merge

<!-- AgentChat/coding_agent 2026-08-06T12:08:00Z -->
<!-- AgentChat/coding_agent 2026-08-06T13:12:00Z -->

This typed operation merges the two fixed Instyle source accounts into the
fixed `INSTYLE_RUNWAY` production destination. It is intentionally separate
from the disposable demo sync and accepts no caller-selected account,
database, table, mapping, statement, or SQL input.

Use `nova_sql_instyle_runway_merge_preview` with one stable idempotency key.
Review the exact Salesforce account identities, source fingerprints, schema
hashes, clean destination baseline, 24/20 location split, and the live
107-placeholder, 142-linked-line, and 11-row quarantine scope. Execute only
with the identical key and exact preview hash. After any uncertain result, call
`nova_sql_instyle_runway_merge_status` before considering a retry.

The broker creates two destination regions, maps source-A locations to target
IDs 1-24 and source-B locations to 25-44, and keeps source product identity in
an immutable source-qualified crosswalk. Product collisions use normalized
`ProductName`, `BarcodeNumber`, `BarcodeNumber2`, and `SKU`, with the highest
source `ProductID` as the winner. Historical invoice lines whose product parent
is missing use populated inactive placeholders; invoice-less rows are retained
in a private quarantine table.

If a fresh preview finds the exact completed 44-location production merge
with the reviewed thirteen-row inactive-location defect, the same tools switch
to a bounded repair mode. That mode requires the original merge's complete
relationship, history, product, placeholder, quarantine, backup, and receipt
readback. It accepts only destination LocationIDs 25, 26, 27, 28, 29, 31, 35,
36, 37, 39, 40, 42, and 44 with the source-inactive sentinel that was
previously offset. It fully backs up `dbo.Locations`, changes only those exact
status-bearing manager values, and verifies all 44 source-authoritative
location statuses plus the original merge invariants before reporting
completion. Future clean merges preserve that inactive sentinel during the
initial copy.

Before the first business write, the transaction makes and row-count-verifies
a full retained backup of every destination business table. The transaction
rolls back unless the final checks prove the exact 44 locations and two
regions, exact history coverage, zero nonblank product-key duplicates, zero
positive product-reference orphans, zero declared relationship orphans, no
blank invoice links, no skipped nonempty source tables, and the exact approved
placeholder and quarantine scope. Post-commit status repeats the authoritative
relationship, count, backup, crosswalk, receipt, and mapping readback.
