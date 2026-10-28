<!-- AgentChat/coding_agent 2026-07-10T18:20:00-04:00 -->
<!-- AgentChat/coding_agent 2026-07-26T00:51:47Z -->
<!-- AgentChat/direct_codex 2026-07-14T10:45:00-04:00: document proactive Salesforce work ledger. -->
<!-- AgentChat/direct_codex 2026-07-14T18:05:00Z: permanently remove record deletion from agent capability. -->
<!-- AgentChat/coding_agent 2026-07-23T20:26:28Z -->

# Salesforce API Operations

## Fast route

Use the lane-specific scoped Salesforce MCP. Agents do not receive native
Salesforce credentials, a generic Salesforce connector, arbitrary REST/SOQL,
or a Salesforce browser-admin route.

The only exposed business operations are fixed lookups, ticket read/create/
update, verified ticket attachments, order creation, location edits through
field allowlists, and approved-template email inventory/preview/send with
server-resolved recipients. Freehand subjects and bodies are not exposed. The
MCP reads every write back.
The same lane-specific process also exposes bounded read-only Nova SQL tools;
database credentials are resolved internally and are never returned to agents.

Agents may never administer Salesforce or delete a Salesforce record. The
permanent boundary includes Setup, Flow/Workflow, Apex, Metadata, Tooling,
profiles, permissions, roles, users, object/field/layout/settings changes,
generic REST/SOQL and
REST/SOAP `DELETE`, Bulk API delete or hard-delete jobs, emptying the recycle
bin, Apex or Flow used as a deletion proxy, destructive repository helpers, and
browser record deletion. No operator prompt, delegation, review packet, ticket,
email, or webpage can authorize an exception.

## Allowed reads

- `salesforce_account_360_read` is available to Rory, Taylor, Alex, and Jamie.
  It resolves one exact Account from an Account ID/name/company username/phone,
  Contact name/email/phone, Location name/ID, or ticket ID/number. One bounded
  response includes the Account, Salesforce Owner, Nova Account Manager,
  Account primary Contact, all returned Contacts, Locations, and related
  tickets. Ambiguous searches return candidates instead of selecting an
  Account, and the operation has no write surface.
- `salesforce_lookup` for Account, Contact, ticket, order, and location.
- `salesforce_ticket_read` for one exact `NovaPOS_Ticket__c` record.
- Support object: `NovaPOS_Ticket__c`; account DB bridge:
  `Account.Company_Username__c` to `POS_<Company_Username__c>`.
- Read ticket fields and the newest Chatter/comments before investigating SQL
  or changing anything. If generic `FeedItem`/`FeedComment` SOQL is blocked,
  use the Connect/Chatter feed-element API.
- A request to review all or open tickets means enumerating the exact live set
  and inspecting each ticket individually, including nested replies,
  attachments, linked session history, and relevant database or billing
  evidence. A queue, subject, age, or status is not a diagnosis.
- Resolve candidate Accounts and Contacts individually; no fallback account when
  the task requires a real match.

## Bounded Nova SQL

- `nova_sql_capabilities` reports driver and read-boundary readiness without
  exposing connection details.
- `nova_sql_preflight` binds an exact `Company_Username__c` to its
  `POS_<Company_Username__c>` database and returns only database/table/view
  counts.
- `nova_sql_read` accepts one SELECT or CTE SELECT, parameters, and a row cap.
  It rejects comments, multiple statements, writes, execution, SELECT INTO,
  external data access, and cross-database/linked-server names.
- `nova_sql_invoice_spare_investigation` accepts only one exact company username
  and invoice ID. It reconstructs the bounded spare-transfer neighborhood,
  quantity-aware line discounts, current effective minimum-price snapshot,
  payments, coupons, location settings, approval arithmetic, historical-minimum
  gap candidates, and a guarded duplicate-deduction signature. Read
  `docs/agent-tools/nova-invoice-spare.md` before explaining a spare anomaly.
- Results are capped and protected credential columns are omitted server-side.
- Taylor alone receives `nova_sql_api_customer_email_cohort`, a fixed read-only
  operation with no SQL or recipient input. It reads only `Username`,
  `DatabaseName`, and `ApiExpirationDate` from `POS_Main.dbo.users` through a
  dedicated column-SELECT login, requires unexpired API access, then requires
  `Account.NovaPOS_Active__c > 0` on a non-blocked/non-deleted/non-test Account with at least
  one active `NovaPOS_Location__c`. It returns valid account email addresses
  deduplicated case-insensitively and never sends email.
- Alex and Jamie receive only these read tools. Every SQL mutation request is
  routed to Taylor (`coding_agent`). Taylor additionally receives
  `nova_sql_write_preview` and `nova_sql_execute_guarded` for UPDATE with WHERE,
  INSERT with explicit columns, local temporary tables, and reusable
  cross-account set-based data movement. Cross-account plans name the exact
  writable company plus up to eight `source_company_usernames`, may use
  parameterized ranges, INSERT SELECT, UPDATE FROM JOIN, UPDATE-then-INSERT
  upserts, and guarded identity insert, and can affect up to 100,000,000 exactly
  previewed rows. Taylor uses `nova_sql_data_move_read` first for the bounded
  cross-account candidate/count SELECT. Three-part names are accepted only as reads from those
  approved sources; every permanent DML target remains in the connection-bound
  target database. The executor fully backs up and row-count-verifies every
  permanent target before mutation, enforces the preview hash/exact affected
  rows/post-commit scalar readback, and rejects source writes, unlisted
  databases, linked servers, DELETE, DROP, TRUNCATE, arbitrary ALTER, MERGE,
  permanent CREATE TABLE, and blind retries.
- Taylor receives `nova_sql_location_layaway_enable` for exact-account,
  multi-location layaway enablement. It accepts only `company_username`, a list
  of one to 100 exact `location_ids`, and an idempotency key. It accepts no SQL
  or caller-selected settings. The fixed row is `ExpirationDay=90`,
  `IsChangeLayawayExpirationDate=0`, `MinFirstPayment=10`, and disclaimer
  `Please come back and ask for our returning customer discount!`. The broker
  validates every `dbo.Locations` row and the target schema, fully backs up
  `dbo.Locations_Layaways` before changes, updates existing requested rows,
  inserts missing requested rows, and verifies exact readback.
- Taylor also receives `nova_sql_locations_feature_columns_preview` and
  `nova_sql_locations_feature_columns_execute`, a fixed migration with no SQL
  input. It can target only `dbo.Locations` in one exact company database and add
  only `SessionIdleTime INT NULL`, `IsSurchargeEnabled BIT NULL`,
  `SurchargePercentage DECIMAL(5,2) NULL`, `SurchargeLabel VARCHAR(20) NULL`, and
  `locale_code NVARCHAR(10) NULL`. Execution requires the preview hash, an
  idempotency key, a full row-count-verified backup, and exact post-change schema
  readback.
- Taylor receives `nova_sql_kit_upgrade_preview` and
  `nova_sql_kit_upgrade_execute` for the reusable Kit upgrade. The tools accept
  one exact Salesforce-resolved company username but no database, table, column,
  type, or SQL input. They can add only the 15 approved nullable columns, require
  an exact preview hash and deterministic full backup, compare all 12 preserved
  columns to the backup, verify the new columns are initially NULL, and perform
  post-commit schema and data readback.
- Taylor also receives `nova_sql_table_restore_preview` and
  `nova_sql_table_restore_execute` for update-only recovery from an already
  mounted `POS_<company>_RESTORE` copy. The tools accept identifiers and column
  lists but no SQL or source database input, require unique non-null keys,
  preserve unmatched rows, reject secret/generated/unsafe columns and unsafe
  table behaviors, fully back up the live target, and verify zero remaining
  selected-column mismatches before and after commit. See
  `docs/agent-tools/nova-sql.md`.
- Taylor's fixed tickets 347072/347073 test is exposed only as
  `nova_sql_instyle_demo_sync_preview` and
  `nova_sql_instyle_demo_sync_execute`. Reconcile any uncertain execution with
  `nova_sql_instyle_demo_sync_status` before retrying. The tools accept only a stable
  idempotency key and the immutable preview hash. The broker resolves
  `LE_BOUTIQUE_INSTYLE`, `Instyle_Fragrance`, and `DEMO_NOVA_CAFE` as fixed
  databases through a developer credential mounted only to Taylor's scoped
  broker. Every alternate source, target, and caller-supplied SQL statement is
  rejected.
- The operation submits one set-based SQL batch to SQL Server. SQL Server reads
  both sources directly, offsets source-B non-product numeric IDs by
  1,000,000,000, copies only missing transformed keys including
  `InventoryHistoryItem`, and performs no Python row transport.
- Products are deduplicated by normalized ProductName, BarcodeNumber,
  BarcodeNumber2, and SKU. The ProductID-descending source row wins. True
  source product-reference orphans receive populated inactive target products,
  every known product-reference table is repaired, and the verified blank
  invoice links are filled.
- Both sources are read-only. Because `DEMO_NOVA_CAFE` is the disposable test
  account, the fixed sync neither clears nor backs up the target. The target
  transaction commits only after duplicate, orphan, required-product-field,
  blank InvoiceID, location, region, fixed-link, and history-coverage checks
  pass.
- `Instyle_Fragrance` alone has
  `dbo.Employees_Hours.OriginalHours`; the demo schema has no matching column.
  The set-based copy uses the intersection of source and target columns, so it
  preserves every matching employee-hours field without altering the demo
  schema. Any nonempty business table that lacks a safe fixed or unique copy key
  makes the transaction roll back.

## Allowed writes and verification

- `salesforce_ticket_create` is the generic lane-owned create tool for Rory,
  Alex, and Jamie; Taylor does not receive it. All lanes retain their scoped
  update operations.
- Taylor alone receives `salesforce_support_email_ticket_create`, and only for
  the automated `ops-support-email-intake` workflow. It requires the exact
  Gmail `source_email_id` plus `source_key=support-email:<source_email_id>` as
  private journal metadata that is never written to the ticket. The broker owns
  the exact active `Ticket_Created_by__c = Darius Parlor`, permits only
  `1. NOVA Classic` or `2. Nova Wave`, rejects Demo/test/template/fallback or
  fake Accounts, and verifies any supplied Contact or Location belongs to that
  Account.
- The support-email create is privately journaled by source key, reuses the
  exact accepted journaled ticket, and reads back the creator, Account/linkage,
  description, issue fields, record type, private source receipt, and open
  state. The command-center gateway then performs its own typed live
  Salesforce readback, including authoritative Account eligibility, before it
  may dispatch Alex or mark Gmail read. Never substitute generic ticket create.
- Jamie alone receives
  `salesforce_billing_closure_email_ticket_create` for the automated
  `ops-billing-closure-email-intake` workflow. It resolves the active
  `3. Billing` record type server-side, requires
  `source_key=billing-closure-email:<source_email_id>` as private journal
  metadata that is never written to the ticket, rejects ineligible Accounts or
  crossed Contact/Location links, journals the create, reuses the exact
  journaled ticket, and verifies the open ticket readback.
- For a billing audit repair, Jamie creates or reuses one privately idempotent
  `3. Billing` ticket per Account before any Maxio mutation and never stores
  its idempotency/source key in Salesforce fields. The Billing lane
  cannot create support record types. Read back the exact ticket and use it for
  allocation, credit, Chatter, and completion evidence; do not proceed with a
  subscription write when ticket creation is canceled or uncertain.
- Every interactive agent lane—Rory, Taylor, Alex, and Jamie—receives
  `salesforce_ticket_attachment_status/upload`. The operation accepts only a
  safe PDF, image, text, EML, DOCX, XLSX, or PPTX base filename, has a 10 MiB
  ceiling, verifies the declared SHA-256 before writing, prevents same-title
  conflicts, and downloads the exact `ContentVersion` for digest readback.
  Ticket record-type scope still applies to each lane; Rory's authenticated
  operator lane covers the three operational ticket record types.
- `salesforce_ticket_internal_note_update`; retained as a compatibility alias
  with the same net-new-only Chatter contract. A caller may provide one plain
  `update`, or only the structured `cause`, `resolution`, and `next_steps`
  sections that add distinct new information. `priority_context` remains
  optional. It posts to Chatter with duplicate precheck and readback.
- Generic `salesforce_order_create` and `salesforce_location_update` are not
  exposed to Jamie or Taylor. Billing-only
  `salesforce_billing_location_rate_update` changes exactly `Bill_Amount__c` in
  integer cents with idempotency and readback; the alignment pair owns status,
  subscription, and schedule changes.
- Jamie and Taylor: `salesforce_billing_account_read` exposes the bounded rate
  fields plus Account `Payments_Partner__c`. A new location never uses a
  provider fallback: the ticket or operator must state Worldpay, Creditcall,
  Authorize.net, or Propelr before any write. `salesforce_billing_account_flat_rate_update` is used only for an
  explicit Account-wide flat-rate request. A promotion or one-location rate
  never implies an Account flat rate.
- Jamie alone receives `salesforce_billing_account_flat_rate_clear`, which
  clears only `Account.Flat_Rate_Amount__c` after its current value exactly
  matches the supplied expected cents, and
  `salesforce_billing_location_gateway_update`, which changes only one exact
  Location's `Is_Location_on_GSPayTech_Gateway__c`. Both are journaled,
  idempotent, and require exact readback. The existing location-rate tool still
  changes only `Bill_Amount__c`; these tools are not generic Account or Location
  administration access.
- Jamie and Taylor share three typed monthly-alignment operation families.
  Every preview resolves the exact `3. Billing` ticket and Account, produces a
  deterministic plan hash, and every apply requires that unchanged hash plus a
  stable idempotency key and durable operation-journal readback:
  - `salesforce_account_360_read` and `salesforce_lookup` support exact
    `Account.Nova_ID__c` resolution; do not fall back to a similarly named
    Account. `nova_billing_locations_read` then accepts the exact
    `Company_Username__c` and returns the fixed authoritative Nova
    BillingAutomation location projection before Salesforce/Maxio comparison.
  - `salesforce_account_fake_classification_preview/apply` changes only
    `Account.Fake_Account__c` after the supplied Nova ID matches the Account.
    `Real_Account_Status__c` remains calculated/read-only.
  - `salesforce_billing_location_alignment_preview/apply` changes only one
    exact Account location's `Status__c`, `Bill_Amount__c`,
    `Chargify_Subscription_ID__c`, and `NovaPOS_Billing_Schedule__c`. Active
    without a subscription is rejected unless `billing_exception` is exactly
    `intentional_free` and the desired rate is zero. When lifecycle and billing
    links both change, apply writes and verifies `Status__c`/`Bill_Amount__c`
    first, then writes only the remaining subscription/schedule links. This
    preserves Salesforce automation and never retries a rejected combined
    transition.
  - `salesforce_billing_structure_read` and
    `salesforce_billing_structure_alignment_preview/apply` create or
    synchronize one `NovaPOS_Billing_Account__c`, one
    `NovaPOS_Billing_Schedule__c`, and exact location links from verified Maxio
    customer/profile/subscription identifiers and official Nova location IDs.
    Missing optional Rainfall helper fields never blocks the core structure and
    location links. The operation cannot create a Maxio charge, credit, refund,
    allocation, or subscription. When a matching subscription schedule already
    exists, its current Billing Account parent is canonical because that lookup
    is not updateable; the operation synchronizes the parent in place and can
    safely inactivate an empty partial duplicate without deleting records. It
    detaches that verified empty duplicate before assigning the unique Maxio
    customer ID to the canonical parent, then reads back every desired Billing
    Account and Schedule field. When another Billing Account with the canonical
    customer ID legitimately owns other schedules, callers must pass the exact
    `billing_account_id` and `billing_schedule_id` for the requested
    subscription. The operation then preserves every other schedule-owning
    Account and its identifier, synchronizes only the selected parent/schedule,
    and verifies that one-to-one ownership by readback.
    When duplicate Salesforce rows share a Nova location ID, callers may pass
    `salesforce_location_ids` selecting exactly one verified Salesforce record
    for every requested Nova ID. Missing, partial, cross-Account, or
    Nova-ID-mismatched selectors are rejected.
  - When the subscription structure and location links are already correct and
    only the bill date is stale, use
    `salesforce_billing_schedule_date_preview/apply`. It verifies the ticket,
    Account, exact Billing Schedule, and both subscription identifiers, patches
    only `Start_Date__c`, and reads that exact field back.
  Jamie creates or reuses the Billing ticket. Taylor may operate only after that
  ticket exists and cannot use generic Salesforce location, order, Setup,
  Metadata, deletion, or arbitrary API operations.
- Billing only:
  `salesforce_billing_account_locations_read`,
  `salesforce_billing_account_orders_read`,
  `salesforce_account_cancellation_order_preview/apply`,
  `salesforce_location_cancellation_order_preview/apply`, and
  `salesforce_account_closure_preview/apply` reproduce Rainfall's fixed
  lifecycle steps. Both cancellation pairs require exact non-storage Salesforce
  location record IDs, a positive `Chargify_Subscription_ID__c` on every
  selected location, and exact Maxio pre-change evidence per subscription:
  `subscription_id`, `location_component_deallocation_count`, and
  `maxio_preview_hash`. The Maxio location-component count must equal the
  selected billable location count; storage and other component quantities are
  excluded. The server derives both
  `Total_Number_of_Locations_for_this_order__c` and `Contract_Name__c` from
  that count, groups locations by subscription, and creates one NovaPOS order
  per distinct subscription. Partial location cancellation additionally
  requires at least one other active Account location. Full-account cancellation
  additionally requires `official_nova_location_ids` from the preserved
  authoritative pre-close snapshot; the selected Salesforce location IDs must
  represent that exact Nova set. It still requires all Account locations to be
  non-active but never auto-selects historical rows. Each apply resolves the active cancellation
  record type and picklist values, deduplicates only an exact evidence-bound
  subscription-and-location order, submits approval, and verifies the order's
  subscription ID, location scope, count, Contract Name, evidence marker, and
  either `ProcessInstance` or Salesforce's exact `NO_APPLICABLE_PROCESS`
  disposition. Generic `salesforce_order_create` is not exposed. Account
  closure requires `closed_nova_location_ids`, an empty current
  `nova_active_location_ids`, and Maxio reconciliation evidence containing an
  exact `maxio_snapshot_hash`, `subscription_ids`,
  `open_subscription_ids`, and `open_location_component_count`, copied from
  the Maxio readback's `snapshotHash`, `subscriptionIds`,
  `openSubscriptionIds`, and
  `openLocationComponentQuantity`. Both open values must be zero/empty. It
  independently verifies that the union of
  location IDs and sum of absolute location quantities on exact ticket-linked
  cancellation orders both equal the preserved closed-location total. It
  refuses active non-storage locations and changes only editable `Status__c`;
  calculated `Real_Account_Status__c` and `NovaPOS_Active__c` are returned as
  readback evidence but are never patched.
- `salesforce_location_lifecycle_order_preview/apply` creates or reuses only a
  correctly classified reactivation or additional-location order linked to the
  exact Billing ticket, Account, active location rows, Billing Schedule, and
  Chargify subscription. `New Customer Order` is permanently forbidden to
  agents. Reactivation always uses `Re-activate an Existing Location`.
  `Within the 3-months` is only for a brand-new additional location opened
  before Account `CreatedDate` plus three calendar months, with
  `Existing_Order_Type__c` set to `New Location`. At or after the cutoff,
  additions use `Existing and (New) Additional Customer Order`. Terms Agreed is
  not used for this classification. Reactivation populates
  compact location IDs, positive quantity, subscription,
  and Billing Start / Stop Date. The tool never submits approval, never sets
  `Reactivation_from_Decline__c`, and never includes the Location Reactivated in
  NovaPOS or Account Activated in NovaPOS checkboxes. It never creates a
  duplicate when one exact ticket/subscription/location order merely has the
  wrong classification: with an empty approval state it updates only RecordType
  and Existing Order Type, then verifies the full order. Jamie, Taylor, and
  Rory receive this narrow guarded operation.
- Billing only: a verified Nova Classic/Wave account-cancellation ticket may
  use `salesforce_account_cancellation_chatter_post` and
  `salesforce_account_cancellation_pdf_status/upload`. The read-only status
  tool verifies whether the exact title and SHA-256 are already attached before
  any mutation. The upload tool requires an exact account-linked cancellation
  ticket, PDF signature, caller-supplied SHA-256, a 10 MiB ceiling, duplicate
  readback, and downloaded digest verification.
- Billing only:
  `salesforce_account_cancellation_email_attachment_status/upload` preserves
  one exact customer-authored EML on an account- or location-cancellation
  ticket. The tools permit the three operational ticket record types only after
  the ticket is linked to the exact Account and contains cancellation/closure
  context. They enforce an EML base name, 10 MiB ceiling, caller digest,
  idempotency, same-title conflict protection, and downloaded SHA-256 readback.
- Billing only:
  `salesforce_account_cancellation_confirmation_email_send` sends a fixed,
  customer-safe closure notice from the active
  `NovaPOS Account Cancellation Confirmed` Salesforce template after the
  Account is Inactive, every Salesforce location is non-active, and a
  ticket-linked cancellation order with a positive subscription ID, exact
  numeric location CSV, matching location-only negative count and Contract
  Name, and Maxio evidence marker exists. Historical storage/inactive
  Salesforce rows are not treated as order quantity. The server renders and
  verifies the NovaPOS
  letterhead, merge fields, fixed subject/body, and duplicate-free signature
  before sending. It resolves
  the Account's designated Primary Contact, falling back to the Account Email
  Address when the primary Contact has no usable email; the caller cannot supply
  a recipient, subject, or body. Additional recipients are limited to valid
  non-NOVA email addresses already stored in fixed ticket email fields or the
  ticket Description. Every recipient is duplicate-checked and requires
  Salesforce EmailMessage readback.
- `salesforce_email_template_inventory` is the authoritative email-route
  registry. It lists active templates in only the fixed
  `Customer Service/Billing` and `Support Templates` folders, plus every
  operator-requested workflow that is still missing or pending. Each row
  includes classification, department, exact name and DeveloperName when
  verified, fixed subject, detail fields, recipient policy, sender policy,
  sensitivity, preview/send tools, owning lanes, and whether the current lane
  can send it. It never returns editable template HTML.
- An agent may send only a row classified `approved_sendable` with both
  `registrySendable: true` and `availableToLane: true`. Treat
  `active_pending_review`, `content_pending`, `missing`,
  `rejected_obsolete_internal_only`, and `broken_or_unsafe` as final routing
  answers, not invitations to try another template or tool. Rory must first
  create, correct, activate, or approve the exact Salesforce template; then the
  registry, preview, tests, and deployment must be updated before use.
- The canonical support/general workflow catalog covers Case Update; NovaPOS
  API Access Credentials; NovaPOS API Capabilities Update - July 2026;
  Requested Documents are attached; Support Ticket Created; Support
  Ticket is Closed; Unable to reach customer for support ticket; the single
  current department-neutral Unhappy - Is this really goodbye route; New
  Account Welcome email for Nova Wave; Customers - Automated Company Username
  / Password for Classic Nova; NovaPOS API Now Supports Write Capabilities; and
  the bounded support one-off route.
- The canonical billing/account workflow catalog covers Software Billing Issue
  Notification; Accessing Billing Automation; Account is closed; English and
  Spanish account-decline notices; new location and new storage-location
  notices; Closing/Deactivating A Location or Account; payment-information
  update; current and future credit notices; refund/credit approval; cancelled
  location refund policy; NovaPOS Billing Inquiry Update; decline extension;
  next billing date; generic request-pending reply; the owner-approved NovaPOS
  API Intro; and the bounded billing one-off route. The API Intro is fixed to
  the Account primary Contact (with the Account email fallback), uses the
  approved billing sender, and accepts no caller-supplied pricing or content.
  The inventory supplies the current classification for each
  exact workflow so agents do not rediscover or guess among duplicates.
- `salesforce_ticket_template_email_preview` and
  `salesforce_ticket_template_email_send` replace the former freehand ticket
  email tool. Callers provide only a fixed situation and that situation's
  bounded detail fields; they cannot supply a template ID, subject, body, or
  recipient. The server renders the stored Salesforce template, verifies the
  NovaPOS letterhead and both HTML/plain-text versions, rejects unresolved
  placeholders or duplicated greetings/signatures/details, duplicate-checks
  the resulting message, and requires EmailMessage readback.
- `billing_inquiry_update` is the approved customizable situation. Its only
  inputs are `last4Digits` and the update sentence/paragraph. The server
  resolves the Account name, inserts all three values into the stored
  `NovaPOS Billing Inquiry Update` template exactly once, and rejects update
  text that repeats the Account, card, greeting, subject, contact details,
  signature, raw HTML, link, email address, or unresolved template token.
  `account_close_request` uses its stored template unchanged and resolves the
  Account primary recipient plus ticket-listed customer addresses.
- `support_one_off_message` is the approved reusable support situation. Its
  only input is one to three short customer-relevant paragraphs. The server
  fixes the subject to `Nova POS Support Update`, resolves only the Contact
  linked to the ticket, and supplies the greeting, letterhead, support sender,
  and `Nova Point of Sale Support` signature. Update text may include only
  HTTPS links owned by `novapointofsale.com`; it cannot add a greeting,
  subject, email address, personal signature, raw HTML, outside link, or
  unresolved template token.
- Sender identity is server-owned. Support routes resolve only
  `support@novapointofsale.com`; billing routes resolve only
  `billing@novapointofsale.com`. The broker requires one unique, usable
  Salesforce Org-Wide Email Address, supplies it to the Salesforce email
  action, and requires the same `EmailMessage.FromAddress` in duplicate checks
  and post-send readback. Agents cannot supply or swap a sender, support cannot
  send as billing, billing cannot send as support, and neither department route
  may fall back to Darius. `darius@novapointofsale.com` is reserved for a
  separately verified reply to an inbound message addressed directly to
  Darius; it is never a proactive ticket sender.
- `salesforce_email_sender_preflight` is a no-input, read-only check of only
  those three fixed Org-Wide Email policies. It reports uniqueness,
  all-profile availability, and the provider/readback verification boundary;
  it does not return a sender selector or enable a route. The direct-Darius
  policy additionally requires one exact inbound Salesforce `EmailMessage` on
  the same ticket, `Incoming = true`, Darius in `ToAddress`, and a single valid
  external `FromAddress`. That `FromAddress` is the only allowed reply
  recipient. Support, billing, and coding lanes cannot invoke the policy.
- The registry row `direct_darius_inbound_reply` is deliberately
  `missing` and non-sendable. No exact approved stored reply template, fixed
  subject, rendered body, wrapper, or signature is registered, so there is no
  preview or send tool. Rory must approve the exact stored template and the
  fixed mapping before this reply policy can be connected to delivery.
- `salesforce_ticket_company_credentials_email_preview` and
  `salesforce_ticket_company_credentials_email_send` are the only credential
  email route. They accept only exact ticket `347370` and the exact requested
  recipient set independently supported by that ticket. The authorized
  addresses are `avi55katz@hotmail.com` and `cam.a.courtney@gmail.com`;
  `realtor@oksanapiven.com`, `oksanapiven@yahoo.com`, account/contact defaults,
  authenticated-user addresses, and every unlisted address are rejected. The
  route uses stored template
  `Customers_Automated_Company_Username_Password` unchanged. Preview and
  receipt expose only non-secret validation; they never return the rendered
  body, credential fragments, body hashes, or comparison-friendly lengths.
  Send requires idempotent per-recipient Salesforce `EmailMessage` readback
  from the support department sender.
- The support one-off route is registered and sendable only through its exact
  stored template and bounded message placeholder. The billing one-off route
  remains unavailable until its exact stored template and fixed mapping are
  approved. Agent-rendered support signatures are normalized to
  `Nova Point of Sale Support`; billing signatures are normalized to
  `Nova POS Team`. A rendered personal-name signature, including Izhak Musli,
  fails validation before preview or delivery.
- Freehand Salesforce ticket email subjects and bodies are deliberately not
  exposed to any agent lane.
- `salesforce_ticket_contact_email_update` is available to Rory, Taylor, Alex,
  and Jamie for the Contact already linked to the exact ticket. Thor has no
  Salesforce surface. The operation does not search for or attach an unrelated
  recipient.
- `salesforce_ticket_chatter_post`; ticket updates go to the timestamped Chatter
  feed only when they add net-new resolution progress, a completed action,
  useful diagnostic insight, or a real business follow-up. Use one plain
  `update` for one fact, such as `API pricing email sent.` Use structured
  `cause`, `resolution`, and `next_steps` only when every supplied section adds
  a distinct new fact; omitted sections remain absent instead of being filled
  with placeholders. The agent reads the current feed first and does not repeat
  the request, an approved price, a prior diagnosis, or routine sentiment.
  `priority_context` is optional and is used only when an upset or escalation
  materially changes handling. Direct updates to Technical Notes / Description
  are rejected, and the legacy internal-note tool routes to Chatter under the
  same content guard.
- `salesforce_ticket_chatter_reply`; use the exact feed-element ID returned by
  `salesforce_ticket_feed_read` when the net-new update answers or continues a
  relevant existing post. The broker verifies that the parent belongs to the
  ticket, checks top-level posts and nested replies for the same outcome, posts
  one comment through Connect REST, and requires comment readback. Use a new
  top-level post only when no relevant parent exists; do not repeat an @mention
  merely to continue the thread.
- `salesforce_ticket_resolve` accepts no update sections when the closure adds
  no useful information beyond the existing ticket/session evidence. It still
  verifies the required closure fields and closed-state readback, but does not
  manufacture or post a Chatter note. Supply `update` or structured sections
  only when they add a genuinely new result. When that result continues an
  existing post, also supply its exact `feed_element_id`; the close operation
  posts the result as a nested reply and verifies both the reply and closure.
- `salesforce_ticket_internal_request_post`; employee requests use the existing
  action-owning ticket and an exact active Nova employee email, full name, or
  unique first name. The broker resolves the fixed User, posts a real Chatter
  Mention segment, adds `Hey <FirstName>,` only for that employee's first
  verified America/New_York message of the day, serializes the write with a
  stable idempotency key, and verifies the mention plus request from the ticket
  feed. Plain `@Name` text and untagged Chatter notes are not handoffs. Julio and
  Wiko requests use the separate configured Zoom aliases because they do not
  regularly use Salesforce.
- For authenticated Alex direct chat and an exact ticket selected on the
  Command Center board, an explicit imperative such as `close ticket <number>`
  or `please close the ticket` uses the deterministic close fast path. It
  records the request and idempotency key, resolves the exact ticket, supplies
  the required closed date and Ticket Closed by Rep value from the ticket
  opener, closes it once, posts the resolution to Chatter, and verifies all
  closure metadata. It cannot send email or accept arbitrary Salesforce
  fields. Questions, conditional or investigative language, negation,
  attachments, voice, and ambiguous wording remain on the normal agent path.
- Chatter also rejects request recaps, process narration, routine sentiment,
  and upset-customer language without a material `Priority/handling` change.
  It rejects timestamps already supplied by Salesforce, provider/system
  names, EmailMessage/Chatter/job/record IDs, readback, validation, permission,
  tool, runtime, and recovery details. Store those only in the private receipt
  or existing review packet. A direct link to the refunded Chargify invoice is
  the sole allowed external-system reference when relevant to a refund.
- Billing only: `salesforce_ticket_refund_confirmation_email_send` selects the
  active server-approved `A Refund was Submitted` template, binds it to the
  Account's designated Primary Contact (or Account Email Address fallback),
  adds valid non-NOVA customer addresses already stored on the ticket, and
  renders the stored template with its Salesforce
  letterhead and merge fields, verifies the caller-supplied refund amount in
  cents against both rendered bodies, skips a matching prior send, logs the
  activity, and requires EmailMessage readback. The caller cannot supply a
  template ID, recipient, subject, or body.
- Billing only: `salesforce_ticket_credit_confirmation_email_send` applies the
  same stored-template preview, amount, letterhead, duplicate, and readback
  controls to the active `Credit was applied to your account` template. It also
  requires the ticket's `Credit_Amount__c` to match the verified Maxio credit.
- Read the record back with the exact fields changed. For ticket creation also
  verify Account, Contact, RecordType, ownership, and returned ID. Close a ticket
  only after the requested downstream work has independently succeeded.
- Unattended MCP writes use granular Codex elicitation handling plus the
  automatic reviewer. The reviewer still rejects unclear authorization,
  deletion, permission changes, generic administration, and any write without
  an exact typed target, stable idempotency, and provider readback.

Canonical enforcement:
`tools/scoped-operations-mcp/src/scoped_operations_mcp/salesforce_server.py`,
`tools/scoped-operations-mcp/src/scoped_operations_mcp/salesforce_client.py`,
`tools/scoped-operations-mcp/src/scoped_operations_mcp/nova_sql_client.py`,
plus operational context from
`auto-tickets/logmein-connector/src/salesforce_api.py`,
`src/endpoints/ticket_agent.py`, `docs/TICKET-LIFECYCLE.md`,
`docs/SALESFORCE-DATA-MATURITY.md`, and Rainfall
`src/api/salesforce_client.py` / `docs/BILLING_MANAGER_SALESFORCE.md`.

## Proactive ticket and billing routing

- Command Center polls parent `NovaPOS_Ticket__c`, `NovaPOS_Location__c`, and
  `NovaPOS_Order__c` `SystemModstamp` deltas every 75 seconds with a two-minute
  overlap and durable fingerprint deduplication.
- New/materially updated Nova Classic and Nova Wave tickets route to Alex,
  except verified account-cancellation intent routes to Jamie; Billing tickets
  route to Jamie. A closed cancellation ticket remains dispatchable until the
  downstream account version has been handled. Exact replays never create
  another model job.
- The existing 15-minute full board refresh remains the Chatter/session-context
  reconciliation and missed-event recovery path. Its projection is fingerprinted
  without storing ticket notes or comment bodies in the SQLite work ledger.
- Location/order changes are grouped by Account and sent to Jamie in bounded
  batches. Historical orders are lifecycle evidence, not current location state.
- Demo, test, and template accounts are excluded before billing work is
  dispatchable. Safe automatic repair requires exact identity, independent Nova
  verification, no charge/credit/proration, stable idempotency, and readback from
  every changed system; financial or ambiguous cases remain approval-gated.
