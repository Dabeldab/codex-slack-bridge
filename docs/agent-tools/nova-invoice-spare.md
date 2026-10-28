# Nova Invoice Spare Investigation

Use this read-only workflow when Darius asks why an invoice spare is positive or
negative, why a below-minimum sale was approved, or how one invoice consumed
another invoice's spare.

`skills/deep_operational_investigation.md` is the compact prompt-time trigger
for this runbook. The full rules below remain authoritative for invoice spare.

## Required first call

Call `nova_sql_invoice_spare_investigation` with the Salesforce-resolved
`Company_Username__c` and one exact invoice ID. The operation accepts no SQL and
returns a bounded neighborhood containing the requested invoice, its attached
source, direct consumers or siblings, product lines, payments, coupons, location
minimum-price settings, quantity-aware calculations, and a guarded spare-link
interpretation.

Use `nova_sql_read` only for a narrow follow-up the typed result identifies. Do
not begin with `SELECT *`, and do not mutate invoice history while diagnosing it.

## Spare model

For each line:

- gross: `ProductPrice * Quantity`
- total line discount: `ProductDiscount * Quantity`
- net: `(ProductPrice - ProductDiscount) * Quantity`
- current minimum contribution: current effective minimum times quantity
- current spare snapshot: net minus the current minimum contribution

The current minimum is a present-day diagnostic only. `Invoice_Products` stores
the sale price and discount but not the minimum price used when the invoice was
created. A later product or price-list change can therefore make a current
recalculation differ from the stored invoice spare.

For an attached invoice, the legacy approval rule is:

`sale own spare + full available source-invoice spare >= 0`

The gross retail value is not the approval threshold. The legacy flow transfers
the source's full available spare, even when the sale needs less, and stores the
remainder on the new invoice.

## Deep diagnosis sequence

1. Reconcile the source invoice's gross, quantity-aware discount, net, stored
   spare, and payment total.
2. Reconcile the consuming invoice the same way. A zero-dollar invoice with no
   payment can be internally consistent when every unit was fully discounted.
3. Read `SpareInvoiceID` in both directions. Check every direct consumer before
   assigning one source-spare change to one sale.
4. Reconstruct the approval equation from the typed result. State the exact own
   spare, attached spare, and resulting stored spare.
5. Compare the inferred at-sale minimum total with the current minimum snapshot.
   When an exact gap matches one or more product contributions, name the match
   as an inference and explain that the invoice did not preserve the old minimum.
6. If the source spare is below its expected post-transfer balance, inspect the
   relevant POS source path. In the reviewed legacy WinForms flow, source spare
   persistence existed in both the local-backup and server invoice paths. Treat
   that as root cause only when the database signature and the applicable client
   code or version agree.
7. Return a short causal explanation. Do not paste a table dump, repeat the
   customer's original description, or claim today's product settings were the
   historical settings.

## Duplicate-deduction signature

A strong one-consumer signature is:

- source line math reconstructs positive spare `S`;
- one child invoice attaches that source;
- the child received `S` in its approval equation;
- the source's stored spare is `-S` instead of `0`; and
- two applicable persistence paths each subtract the same full `S`.

The arithmetic is `S - S - S = -S`. If multiple consumers exist, historical
minimums changed, coupons affected spare, or the code version is uncertain,
report the bounded evidence and investigate further instead of forcing this
diagnosis.

## Output boundary

Keep raw SQL, database names, internal paths, tool names, and code details out of
customer-facing ticket updates. Internally, give Darius the stored facts, the
equations, the verified application behavior, remaining uncertainty, and any
safe next step. This workflow is read-only and performs no invoice correction.
