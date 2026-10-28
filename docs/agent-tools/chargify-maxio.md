<!-- AgentChat/coding_agent 2026-07-10T18:20:00-04:00 -->
<!-- AgentChat/direct_codex 2026-07-14T18:05:00Z: permanently remove record deletion from agent capability. -->
<!-- AgentChat/direct_codex 2026-07-14T14:45:00-04:00: define official Nova BillingAutomation as the location authority. -->
<!-- AgentChat/direct_codex 2026-07-31T00:00:00-04:00: add typed promotion and complete rate-change handling. -->
<!-- AgentChat/coding_agent 2026-08-03T23:58:00Z: require paid-result activation gating. -->

# Chargify / Maxio API Operations

## Fast route and auth

Use a Maxio MCP/app connector first, then Advanced Billing API, then Rainfall's
established client. Browser is only for a confirmed API limitation. Native API
uses HTTP Basic auth with the API key as username and `x` as password. Prefer
`CHARGIFY_BASE_URL` and `CHARGIFY_API_KEY`; some registry paths also recognize
`CHARGIFY_SUBDOMAIN` or `MAXIO_API_KEY`, so verify the selected client supports
the alias before calling it. Never print credentials.

Agents may never delete a Maxio/Chargify record. This is a permanent capability
boundary, not an approval step. Hard-delete, purge, destroy, and equivalent
record-removal operations are unavailable through every surface. The generic
`maxio_api_request` exposes only `GET`, `POST`, `PUT`, and `PATCH`, requires a
stable idempotency key for writes, records intent before execution, and rejects
deletion semantics without returning the API key. Maxio's documented immediate
subscription cancellation happens to use HTTP `DELETE`, but it sets the retained
subscription state to `canceled` rather than deleting the record or transaction
history. Jamie may call that endpoint only through the fixed typed cancellation
preview/apply pair below; generic `DELETE` remains unavailable.

## Location reconciliation source hierarchy

- Call `nova_billing_locations_read` with the exact Salesforce
  `Company_Username__c` first. It exposes the fixed current-location projection
  used by Nova BillingAutomation, including active non-storage IDs/names and the
  complete bounded location/status list; it accepts no SQL.
- Use Maxio as the authority for subscription, component quantity, rate,
  balance, invoice, and other financial state.
- Compare Salesforce active non-storage locations and billing links as
  administrative state. Treat Salesforce orders as lifecycle evidence only.
- Rainfall subscription-location rows and Maxio location-map metafields are
  optional internal diagnostics. Missing maps are normal and must not trigger a
  repair, blocker, or Needs Review item.
- Do not assign mixed Maxio rates to individual locations unless official Nova
  billing data records that assignment. Do not use Rainfall's mapping reconcile
  apply path for proactive sweeps because it creates optional mappings.

## Resolve before writing

1. Resolve the Salesforce account/ticket and Nova ID.
2. Try exact reference lookup with
   `GET /customers/lookup.json?reference={nova_id}`. If the reference is not
   known, use `GET /customers.json?q={email_or_name_or_reference}` and verify the
   returned identity before continuing.
3. Paginate `GET /subscriptions.json?customer_id={customer_id}` and
   `GET /payment_profiles.json?customer_id={customer_id}`.
4. Read the exact subscription, invoice, balances, components, allocations,
   credits, or profile needed. Confirm every ID belongs to the customer.
5. Preview monetary/allocation impact where supported; perform only the requested
   mutation; independently read back the object and related collection.

## Established operations

- Corporate tax report: `maxio_tax_report`. With no dates it generates the prior
  calendar month; use `month=YYYY-MM` for a specific month or inclusive
  `start_date` and `end_date` for a custom range. The broker reads paginated
  Maxio invoices, uses invoice billing addresses only, validates each taxable
  invoice, and creates one plain `.xlsx` worksheet in the GCP shared report
  directory. Return its `artifactPath` through `UPLOAD_FILE:` so Slack attaches
  the workbook. The report contains only its title, dates, headers, and rows.
- Subscription: `GET /subscriptions/{id}.json`.
- Missing subscription without an immediate recovery charge: use only
  `maxio_subscription_creation_preview/apply`. It requires the exact customer ID
  and reference, a current non-expired payment profile owned by that customer, a
  monthly product, exact component/quantity/unit-price cents, a future
  `next_billing_at`, and the Billing ticket. The broker derives a stable
  subscription reference, journals the write, and verifies identity, allocation,
  future bill date, and zero open/pending invoice balance. It refuses an
  immediate billing date and cannot create an initial charge, payment, credit,
  refund, or proration.
- Missing subscription with an authorized immediate payment recovery: first use
  `maxio_subscription_creation_preview/apply` exactly as above so Maxio creates
  and reads back the recurring subscription without capturing money. Then use
  `maxio_billing_cycle_recovery_preview/apply` on that exact new subscription.
  Supply the exact missed cycle count, the subscription's exact current monthly
  amount, independently authorized total cents, service-period dates, and the
  Billing ticket. The recovery tool fixes `delay_capture=false`,
  `accrue_on_failure=true`, automatic collection, no negative-balance use, no
  allocation change, and no retry after any provider attempt. A paid result
  requires the linked successful charge and payment plus zero balances and
  returns `downstreamActivationAllowed=true`. A decline must preserve exactly
  the authorized open invoice with every other balance zero and returns
  `downstreamActivationAllowed=false`. Do not activate the official Nova
  location, Salesforce location, Billing Schedule, or Account until that flag
  is true. Generic charge creation remains blocked.
- Customer invoices: `GET /invoices.json?customer_ids={id}`; invoice detail:
  `GET /invoices/{uid}.json` with line items, payments, taxes, credits/refunds.
- Components: `GET /subscriptions/{id}/components.json`.
- Account-close reconciliation:
  `maxio_location_allocation_reconciliation_read` reads the complete component
  inventory for every exact current or recently changed subscription,
  classifies location/storage/other quantities, identifies subscriptions that
  remain open, totals only open location components, and returns a stable
  snapshot hash. Use it before cancellation to compare Maxio with official
  Nova and Salesforce, and after cancellation to prove zero open subscriptions
  and zero open location-component quantity.
- Allocation preview/apply: `POST /subscriptions/{id}/allocations/preview.json`,
  then `POST /subscriptions/{id}/allocations.json`. Location reconciliation must
  set every charge/proration/credit switch to none and verify cross-system equality.
- Jamie's preferred typed path is `maxio_component_allocation_preview`, then
  `maxio_component_allocation_apply` with the exact preview hash and a stable
  idempotency key. Callers provide only component IDs and desired quantities;
  they cannot select financial switches. The broker derives current quantities,
  retrieves the complete paginated component inventory, classifies decreases as
  location, storage, or other, and returns the hashed
  `componentDeallocationSummary`. Preserve this evidence before apply when the
  decrease will produce a Salesforce cancellation order. Only
  `locationComponentDeallocationCount` is an order location count.
  Storage and other component quantities are excluded. The broker
  rejects stale previews, applies `upgrade_charge=none`,
  `downgrade_credit=none`, `proration_upgrade_scheme=no-prorate`, and
  `proration_downgrade_scheme=none`, then verifies component quantities. Invoice,
  balance, and service-credit readback remains required before the overall
  billing workflow is complete.
- `maxio_capabilities.subscriptionRepairModes` registers the four supported
  repair paths and their exact tool order:
  - upgrade without charge: allocation preview/apply, then balance readback;
  - downgrade without credit: allocation preview/apply, then balance readback;
  - upgrade with credit: verified no-charge allocation first, then separate
    manual-credit preview/apply and balance readback;
  - downgrade with credit: verified no-credit allocation first, then separate
    manual-credit preview/apply and balance readback.
  A mixed component migration uses the same no-financial-effect allocation pair
  and requires explicit review of every increased and decreased component.
- An allocation never creates its own credit. Calculate an authorized credit
  amount independently in exact cents, preview and issue it with
  `maxio_manual_service_credit_preview/apply`, verify the exact service-credit
  balance increase, and let Maxio apply it to the next generated invoice. The
  credit requires its own authorization even when the allocation was authorized.
  If it instead belongs on an already-open eligible invoice, apply it separately in
  the authenticated Maxio UI and verify both the invoice due reduction and the
  service-credit balance reduction. Generic allocation, credit-note,
  service-credit, service-credit-deduction, and invoice-payment writes are
  rejected so they cannot bypass this order.
- A ticket that requests a promotion uses only
  `maxio_subscription_coupon_preview/apply`. The preview binds one exact coupon
  and subscription to the Billing ticket, verifies the subscription is active
  or past due, validates the coupon code, product family, active dates, amount or
  percentage, term, current coupon set, account balances, and existing-coupon
  state, then returns an immutable preview hash. Apply accepts only that hash and
  a stable idempotency key, posts only `{"codes": ["<coupon>"]}` to Maxio's
  documented add-coupon endpoint, and requires exact subscription coupon
  readback. The generic Maxio request tool cannot apply coupons.
- Every additional location uses the Nova Integrated Promo workflow. Resolve
  the merchant provider before any write; the only accepted values are
  `Worldpay`, `Creditcall`, `Authorize.net`, and `Propelr`. If neither the
  ticket nor the operator names one, ask which provider applies. Do not infer a
  provider from Account metadata or use a fallback product. Text such as
  `GSPayTech Sub-46010103` is a subscription/merchant identifier, not provider
  evidence. `maxio_nova_integrated_products` returns only active zero-base-price
  Nova Integrated products matched to those four providers.
- Jamie changes the product only with
  `maxio_subscription_product_change_preview/apply`. The target must be an
  active, monthly, zero-base-price Nova Integrated product in the same product
  family. Apply sends only `subscription.product_id`, then proves the coupon
  set, all nonzero component allocations, account balances, current period,
  and next assessment date did not change. It creates no charge, credit,
  proration, invoice adjustment, coupon, or allocation. Generic subscription
  updates cannot set a product field.
- The additional location must be isolated on a one-location subscription.
  After its no-immediate-charge allocation and all four fixed location custom
  fields read back, use `maxio_nova_integrated_promo_credit_preview/apply` for
  exactly three months at the ticket's exact location rate, or 9999 cents per
  month when the ticket does not state a rate. The pair rejects a provider or
  product mismatch, an unrelated location, a quantity other than one, a
  component-rate mismatch, and an unrelated existing service-credit balance.
  Its invoice-facing memo is limited to `Nova Integrated Promo`, the Billing
  ticket number, and location ID. It never changes an Account flat rate or
  applies the credit to an already-open invoice.
- Coupon application does not itself adjust an already-issued invoice, create a
  refund, or issue/apply a service credit. The promo workflow therefore remains
  open until the current invoice has an explicit verified disposition: no
  adjustment due, retained under a separately identified business reason, exact
  service credit, or exact refund. Manual service-credit application to an
  eligible existing invoice remains a Maxio UI-only operation; do not fabricate
  an API payment. If that UI-only step is actually required, keep the ticket open
  until its invoice and balance readback is available.
- A brief rate or promotion ticket still invokes the complete Rainfall-style
  lifecycle, but it never broadens rate scope. An Account-wide flat rate, a
  location-specific recurring rate, and a promotion are separate instructions.
  Use Account flat rate only when explicitly requested. A location rate changes
  only the exact recurring component and Salesforce Location Bill Amount. A
  promotion does not authorize either rate change unless the ticket explicitly
  states the post-promotion rate. Verify official Nova locations, Maxio
  product/coupon/components, exact Salesforce location rate and integrated
  gateway flag, Billing Schedule/subscription link, balances/invoices, and one
  concise final Chatter result before closure.
- A ticket-authorized recovery of missing location payments uses
  `maxio_component_payment_recovery_preview/apply` when an isolated existing
  subscription already carries the recovery location allocation. Callers supply the exact recovery location IDs,
  component, recovery charge quantity, unit-rate cents, independently authorized
  total cents, and ticket number. The total must equal charge quantity times unit
  rate. The target subscription's complete location metadata must equal the
  recovery locations and map all of them to that component, so an allocation
  decline cannot put unrelated locations into dunning.
- Preview requires an active automatic-payment subscription, a current payment
  profile, correct recurring allocation, and zero starting invoice, discount,
  credit, and prepayment balances. It verifies a zero-effect downgrade and an
  exact full-charge allocation preview. Apply first reduces the recovery
  location-component allocation to zero with `downgrade_credit=none`, then
  reallocates the exact charge quantity with `upgrade_charge=full`, automatic
  collection, and `initiate_dunning=true`. It restores the normal recurring
  quantity with no charge or credit only after the exact linked payment succeeds.
  The charge quantity may exceed
  the location count only when the ticket's exact amount proves multiple missed
  component payments; for example, two missed $119.99 payments for one location
  use charge quantity 2 and restore recurring quantity 1.
- A successful result requires the exact linked charge/payment, zero balances,
  restored recurring quantity, and `downstreamActivationAllowed=true`. Pending
  or declined collection leaves the service allocation at zero and downstream
  activation blocked. A declined payment additionally requires the exact
  authorized open invoice, dunning enabled on only that subscription, and every
  other balance zero. Never retry after the full-charge allocation was attempted.
- Choose only one recovery path. Use component-payment recovery for an isolated
  existing subscription whose recurring allocation must be staged to zero and
  restored after payment. Use billing-cycle recovery after creating a verified
  future-billed replacement subscription for an account that had no usable
  subscription. Never run both charge paths for the same authorized amount.
- When any other already-paid location shares the original subscription, first
  create a future-billed Maxio subscription for only the recovery locations with
  the exact customer, payment profile, product, component/rate, and next billing
  date. Then create or synchronize the Salesforce Billing Account and Billing
  Schedule, link and verify every exact recovery location, and populate the exact
  Maxio location metadata. Only after those readbacks may the recovery pair run
  on the isolated subscription. The original paid locations remain on their
  existing subscription and cannot enter decline from this recovery.
- An explicitly authorized refund uses Jamie's billing-only
  `maxio_invoice_refund_preview/apply` pair. The caller supplies one exact paid
  invoice UID, one exact payment transaction ID on that invoice, exact refund
  cents, and the Billing ticket. Preview verifies the payment and its remaining
  refundable amount. Apply fixes `external`, `apply_credit`, and `void_invoice`
  false, uses a server-owned ticket memo, requires exact refund readback, and
  permanently blocks a second attempt after any provider attempt. Cancellation,
  Salesforce notes/closure, and the approved refund email remain separate
  operations that occur only after verified refund readback.
- Monthly location organization uses only the typed custom-field and metadata
  operations shared by Jamie and Taylor:
  - `maxio_location_custom_fields_read` and
    `maxio_location_custom_fields_preview/apply` read or create the fixed
    subscription metafields `Locations`, `LocationComponentMap`,
    `LocationNameMap`, and `LocationNamesDisplay`. Callers cannot choose a
    different field, scope, or display behavior.
  - `maxio_subscription_location_metadata_read` and
    `maxio_subscription_location_mapping_preview/apply` store exact official
    Nova location IDs/names with exact Maxio component IDs. The preview rejects
    duplicate location IDs, unknown components, and any component whose mapped
    location count does not equal its current subscription allocation.
  These fields are organizational diagnostics, not the authority for active
  location count or financial state. Missing metadata never blocks the billing
  repair; fix official Nova, Salesforce, and Maxio allocations first. The
  metadata apply has no charge, credit, refund, invoice, proration, allocation,
  or subscription-state effect and requires an unchanged preview hash, stable
  idempotency key, durable journal, and exact metadata readback.
- Default payment profile: canonical
  `POST /subscriptions/{subscription_id}/payment_profiles/{profile_id}/change_payment_profile.json`.
- Subscription invoice-email preference: `PUT /subscriptions/{id}.json` with
  the exact requested `receives_invoice_emails` value, followed by subscription
  readback.
- Invoice delivery: `POST /invoices/{uid}/deliveries.json`. A `204` response
  confirms that Maxio queued the delivery; it does not prove recipient delivery,
  so retain the provider result and use the available delivery/email readback.
- Payment-profile or customer record deletion: unavailable to agents. Leave the
  record unchanged and report the permanent policy denial in the originating
  internal chat.
- Immediate subscription cancellation: Jamie uses
  `maxio_subscription_cancellation_preview`, then
  `maxio_subscription_cancellation_apply` with the same subscription ID, ticket
  number, reason, exact preview hash, and stable idempotency key. The server
  requires a verified zero balance, omits scheduling parameters, sends only the
  internal cancellation message, retrieves and hashes the complete pre-change
  component inventory, reports separate location, storage, and other
  deallocation counts, journals the provider call, and verifies
  `state = canceled`. Pass the unchanged preview hash and
  `locationComponentDeallocationCount` to the typed Salesforce cancellation
  order pair; never substitute the sum of all components. It does not refund or
  credit money, void invoices, schedule the cancellation, or send customer
  email. Taylor and generic API callers do not receive this operation.

## No-charge reactivation

When a Billing ticket explicitly authorizes reactivation with no customer
charge and one future bill date, Jamie uses
`maxio_subscription_no_charge_reactivation_preview/apply`. The pair requires an
exactly canceled subscription, zero starting balances, and a waiver equal to
the current reactivation charge. It creates exactly one ticket-bound service
credit, consumes it during resume, sets the exact future bill date, and returns
`downstreamActivationAllowed=true` only after active state, exact customer
identity, zero balances, and the date all read back. This is separate from the
paid reactivation route and does not require a payment profile or successful
payment.

## Location lifecycle order

Use the following order for add/open, close, and reactivation work. A tracked
handoff is an active continuation, not completion; the originating job remains
open until the child returns verified readback.

1. Resolve the exact Billing ticket, Account, official Nova locations, Maxio
   customer/subscription/profile, Salesforce locations, and existing orders.
2. Preview the financial or allocation change and preserve the immutable
   preview hash and stable idempotency key.
3. Perform at most one authorized financial attempt. Reconcile transactions,
   invoices, balances, subscription state, and the durable operation journal
   before any retry.
4. Gate activation on `downstreamActivationAllowed=true` or equivalent linked
   successful payment evidence. Pending or declined results keep Nova and
   Salesforce inactive and keep the ticket open for payment follow-up.
5. After the financial gate succeeds, synchronize the Salesforce Billing
   Account/Schedule and exact location links, create or reuse the required
   lifecycle order, and verify the order fields and approval disposition with
   `salesforce_billing_account_orders_read`.
6. If the official Nova status needs SQL, send one tracked continuation to
   Taylor with the exact company/location IDs and payment receipt. Taylor must
   read current state before the guarded status update. The parent remains
   active until the receipt returns.
7. Re-read official Nova, Salesforce, Maxio, and the order. Post only one concise
   net-new ticket update, send an approved customer notice only when required,
   resolve the ticket, and verify Salesforce closure. A verified closed ticket
   must be removed from every Command Center ticket lane immediately.

Do not use `prepare_subscription_for_cancellation` for a plain deactivate/cancel:
it can zero allocations, create credits, apply credits in the UI, and void invoices.
Refund, credit, void, allocation, and cancellation are separate mutations unless
the request explicitly combines them. Generic refund execution is not yet a
verified local wrapper; use the billing refund workflow and a recorded request
shape.

Canonical sources: Rainfall `src/api/routes.py`, `src/api/chargify_client.py`,
`src/api/idme.py`, `src/api/chargify_components.py`, and
`docs/BILLING_MANAGER_SALESFORCE.md`. Verify files exist in the working tree
before importing; some may exist only in Git HEAD.
