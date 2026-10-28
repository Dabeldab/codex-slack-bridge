# Users Change Logs AI Knowledge V 3

Source: Zoom Knowledge Library browser export
KB ID: n669kbqjs5h1h01ev55em8ki
Article ID: cmp4lp97r03qjr2078tqyersp
Product lane: Nova Wave
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/n669kbqjs5h1h01ev55em8ki/articles/cmp4lp97r03qjr2078tqyersp
Updated: 05/13/2026, 05:58 PM

Extract table (Keep table structure)
Users Change Logs - AI Knowledge V3
Document Metadata
Title: Users Change Logs - AI Knowledge Source
Version: 3.0
Audience: AI chatbot / automated support
Environment: Back Office
Parent Menu Category: Users
Phase: Phase 1 - Canonical Knowledge Capture
Primary Scope: Account-global invoice change audit trail
Framework: 1.canonical_framework_v1_7.md
Direct URL: https://backoffice.novapointofsale.com/users/change-logs
Source notes:
Browser-reviewed page: https://backoffice.novapointofsale.com/users/change-logs
Reviewed in the user's test account on May 13, 2026.
User-provided clarification: Change Logs is global to the entire account and is not scoped to any specific Region.
User-provided clarification: the default date view is rolling Past 7 days from the day the report is opened.
User-provided clarification: Owner is the correct system role label; customers may refer to it as Full Owner.
User-provided clarification: Change Logs records from the beginning of account creation.
User-provided clarification: Change Logs entries are permanent and cannot be edited, deleted, restored, or reversed from the Change Logs page.
1. Component Description
Title

Users -> Change Logs

Target Audience
Owner users
Users with a role/custom access setup that includes the change_log privilege
AI chatbot / automated support
Environment
Back Office
Primary Navigation Path

Back Office -> Users -> Change Logs

Direct URL

https://backoffice.novapointofsale.com/users/change-logs

Direct URL rule:

Direct links do not bypass access restrictions.
The user must have the Owner role or the change_log privilege to access the page.
Scope Level
Account-global.
Change Logs is not scoped to a specific Region.
Do not describe Users -> Change Logs as Region-filtered.
The Back Office top bar may still show Region and Location selectors, but this Change Logs page is an account-level audit view for invoice changes.
Access

Users can access Back Office -> Users -> Change Logs if they have:

the Owner role, or
the specific privilege change_log

Terminology note:

Owner is the correct system role label.
Customers may refer to Owner as Full Owner.
Treat Full Owner as a customer synonym for Owner in support answers.

Other role labels do not grant Change Logs access by themselves.

Users with the following role labels can access Change Logs only if they are also granted the change_log privilege through a custom role or custom access setup:

Partial Owner
Regional Manager
Secretary
Inventory Manager
Product Manager
Sales Representative
Technician
Marketing Manager
2. The Why

Users -> Change Logs provides an audit trail for invoice changes in Nova.

This page should be used when a user needs to understand what happened to an invoice, especially when:

an invoice disappeared
an invoice was deleted
something changed on an invoice
the user wants to know who edited an invoice
the user wants to know who changed invoice commission
the user wants to review invoice-related changes by action type and date

The bot should route users to Back Office -> Users -> Change Logs for invoice audit questions such as:

"My invoice disappeared."
"Who deleted this invoice?"
"Who edited this invoice?"
"Who changed the commission?"
"Something is wrong with my invoice."
"Why does this invoice look different?"
"Where can I audit invoice changes?"

Important distinction:

Users -> Change Logs is for invoice-change audit trail review.
Users -> Payroll Changes is for payroll/timesheet change logs.

Permanent log behavior:

Change Logs records invoice-change audit activity from the beginning of account creation.
Change Logs entries are permanent for security purposes.
Users cannot edit or delete Change Logs entries.
Users cannot restore or reverse a change from the Change Logs page.
There is no log of the full original invoice state.
If a user needs to change a current invoice again, they can edit the invoice again where invoice editing is available; that new edit creates a new change-log entry.
If an invoice was deleted, there is no way to restore it from Change Logs. Invoice deletion is permanent and irreversible.
3. The How
3.1 Open Change Logs
Go to Back Office.
Open Users.
Click Change Logs.

Direct URL: https://backoffice.novapointofsale.com/users/change-logs

3.2 Review Invoice Changes
Open Back Office -> Users -> Change Logs.
Confirm the date range.
Confirm the selected Invoice Type options.
Review the table.
Use Open Invoice when available to open the invoice pop-up for review.
3.3 Review Last Month
Open Back Office -> Users -> Change Logs.
In the Date: quick-filter area, click Last Month.
Review the updated From: and To: fields.
Review the table results.

Reviewed behavior:

On May 13, 2026, clicking Last Month set:
From: 04/01/2026
To: 04/30/2026
3.4 Export the Current View
Set the desired date range.
Select the desired Invoice Type options.
Click Download in Excel.

Export rule:

Download in Excel exports only the table data currently in view based on the active filters.
3.5 Open the Invoice From a Log Row
Find the relevant row in the Change Logs table.
In Actions, click Open Invoice when it is available.

Documented behavior:

Clicking Open Invoice opens a pop-up/modal with the invoice.
Open Invoice is available for all documented action types except Invoice Deleted.
For Invoice Deleted, the invoice cannot be opened from the row.
Owner users can open any invoice artifact in the system.
In general, any user with role access can open and view an invoice, but access to Users -> Change Logs itself is limited to Owner or change_log privilege.
4. Option Details
4.1 Change Logs Menu Item
Exact UI Label: Change Logs
Navigation Path: Back Office -> Users -> Change Logs
Direct URL: https://backoffice.novapointofsale.com/users/change-logs
Scope Level: Account-global
Default State: Not applicable
What it does: Opens the invoice change audit trail page.

Where is this setting? Back Office -> Users -> Change Logs

How do I change it? This is a navigation item, not a configurable setting. Access is controlled by Owner role or the change_log privilege.

4.2 Date Quick Filters
Exact UI Label Group: Date:
Navigation Path: Back Office -> Users -> Change Logs -> Date:
Direct URL: https://backoffice.novapointofsale.com/users/change-logs
Scope Level: Current Change Logs view
Default State: Past 7 days rolling back from the day the report is opened
What it does: Sets the date range for the visible Change Logs table.

Visible options:

Today
Past 7 days
This Month
Last Month

Documented default:

The default view is Past 7 days.
Past 7 days is rolling seven days back from the day the user opens the report.
It is not a fixed calendar week.

Where is this setting? Back Office -> Users -> Change Logs -> Date:

How do I change it? Click Today, Past 7 days, This Month, or Last Month.

4.3 From Date
Exact UI Label: From:
Navigation Path: Back Office -> Users -> Change Logs -> From:
Direct URL: https://backoffice.novapointofsale.com/users/change-logs
Scope Level: Current Change Logs view
Default State: derived from the default Past 7 days range
What it does: Sets the beginning date for the visible Change Logs table.
Visible control: date field with calendar icon.

Where is this setting? Back Office -> Users -> Change Logs -> From:

How do I change it? Enter a date or use the calendar icon.

4.4 To Date
Exact UI Label: To:
Navigation Path: Back Office -> Users -> Change Logs -> To:
Direct URL: https://backoffice.novapointofsale.com/users/change-logs
Scope Level: Current Change Logs view
Default State: current day when the default Past 7 days range is used
What it does: Sets the ending date for the visible Change Logs table.
Visible control: date field with calendar icon.

Where is this setting? Back Office -> Users -> Change Logs -> To:

How do I change it? Enter a date or use the calendar icon.

4.5 Invoice Type
Exact UI Label: Invoice Type
Navigation Path: Back Office -> Users -> Change Logs -> Invoice Type
Direct URL: https://backoffice.novapointofsale.com/users/change-logs
Scope Level: Current Change Logs view
Default State: all action types selected
What it does: Filters the Change Logs table by selected invoice action/change type.
Input behavior: dropdown / multi-select

Visible options:

Select all
Invoice Deleted
Invoice Changed
Commission Changed
Layaway Deleted
Employee tip Changed
Employee Non-Commission Changed
Invoice Location Changed

Where is this setting? Back Office -> Users -> Change Logs -> Invoice Type

How do I change it? Open the Invoice Type dropdown and select or clear the needed action types. Use Select all to include all visible action types.

4.6 Download in Excel
Exact UI Label: Download in Excel
Navigation Path: Back Office -> Users -> Change Logs -> Download in Excel
Direct URL: https://backoffice.novapointofsale.com/users/change-logs
Scope Level: Current filtered table view
Default State: Not applicable
What it does: Exports the current visible Change Logs table view to Excel.

Export rule:

The export includes only what is currently in view below, based on the selected date range and selected Invoice Type options.

Where is this setting? Back Office -> Users -> Change Logs -> Download in Excel

How do I change it? Set the date range and Invoice Type filters, then click Download in Excel.

4.7 Change Logs Table
Navigation Path: Back Office -> Users -> Change Logs -> table
Direct URL: https://backoffice.novapointofsale.com/users/change-logs
Scope Level: Current filtered table view
Default State: filtered by rolling Past 7 days and all Invoice Type options

Visible columns:

Invoice Id
Log Type Name & Date
Performed By
Information
Actions

What it does:

Shows invoice-change audit records matching the selected date range and selected Invoice Type options.

Where is this setting? Back Office -> Users -> Change Logs -> table

How do I change it? Change the date range or Invoice Type selections. Where sorting is available, sorting changes the row order ascending/descending for that column.

4.8 Open Invoice
Exact UI Label: Open Invoice
Navigation Path: Back Office -> Users -> Change Logs -> row -> Actions -> Open Invoice
Direct URL: URL changes by record or account context
Scope Level: Specific Change Logs row
Default State: enabled for non-deleted invoice action rows; unavailable/disabled for Invoice Deleted rows
What it does: Opens a pop-up/modal with the invoice for review.

Documented rule:

Open Invoice is available for all documented action types except Invoice Deleted.
For Invoice Deleted rows, Open Invoice is not available because the invoice was deleted.

Where is this setting? Back Office -> Users -> Change Logs -> row -> Actions -> Open Invoice

How do I change it? This is a row action, not a setting. Click Open Invoice when it is available.

4.9 Owner Access
Exact UI Label: Owner
Customer synonym: Full Owner
Navigation Path: Back Office -> Users -> Settings -> Add New User / Edit User -> USER ACCESS LEVEL -> System Roles -> Owner
Direct URL: No direct URL documented for the role assignment screen
Scope Level: User role assignment
Default State: Not documented for existing users
What it does: Owner access allows access to Users -> Change Logs and allows the user to open any invoice artifact in the system.

Where is this setting? Back Office -> Users -> Settings -> Add New User / Edit User -> USER ACCESS LEVEL -> System Roles -> Owner

How do I change it? An authorized Owner can open the user, go to USER ACCESS LEVEL, adjust the Owner role assignment, and save.

4.10 change_log Privilege
Exact Privilege Label: change_log
Navigation Path: Back Office -> Users -> Settings -> Edit User -> USER ACCESS LEVEL -> Custom Roles -> CREATE ROLE -> Access Roles
Direct URL: No direct URL documented for the custom-role dialog
Scope Level: Account-level page access privilege
Default State: Not documented
What it does: Grants access to Back Office -> Users -> Change Logs.

Where is this setting? Back Office -> Users -> Settings -> Edit User -> USER ACCESS LEVEL -> Custom Roles -> CREATE ROLE -> Access Roles

How do I change it? Create or edit a role/custom access setup that includes change_log, then assign it to the user.

5. Visible Reviewed Data From Test Account

This section records what was visible in the user's test account after clicking Last Month on May 13, 2026. These rows are test-account examples and should not be treated as default customer data.

Filter state:

Date quick filter: Last Month
From: 04/01/2026
To: 04/30/2026
Invoice Type: all visible action types selected

Visible rows:

Invoice Id	Log Type Name & Date	Performed By	Information	Actions
2843	Invoice Deleted; 04/24/2026 01:05 PM	*Manager	Invoice #2843 has been deleted	Open Invoice unavailable/disabled
2857	Invoice Deleted; 04/24/2026 01:06 PM	*Manager	Invoice #2857 has been deleted	Open Invoice unavailable/disabled
2858	Invoice Deleted; 04/24/2026 01:42 PM	*Manager	Invoice #2858 has been deleted	Open Invoice unavailable/disabled
2856	Invoice Changed; 04/28/2026 11:22 PM	*Manager	New Payment method Added: $5.55	Open Invoice available
2856	Commission Changed; 04/28/2026 11:24 PM	*Manager	Old Commission: $4,000.00, New Commission: ($4,000.00)	Open Invoice available
6. Bot-Logic
IF the user asks where Change Logs is, THEN answer: Back Office -> Users -> Change Logs, direct URL https://backoffice.novapointofsale.com/users/change-logs.
IF the user asks what Users -> Change Logs is for, THEN answer that it provides an account-global audit trail for invoice changes.
IF the user says an invoice disappeared, THEN route to Users -> Change Logs and tell them to check the date range and Invoice Type filter for Invoice Deleted.
IF the user asks who deleted an invoice, THEN route to Users -> Change Logs and explain that the table can show Invoice Deleted rows with Performed By and date/time.
IF the user asks who edited an invoice, THEN route to Users -> Change Logs and explain that the table can show invoice-change rows with Performed By and date/time.
IF the user asks who changed invoice commission, THEN route to Users -> Change Logs and explain that Commission Changed is one of the documented Invoice Type options.
IF the user asks what filters are available, THEN list Date quick filters, From, To, and Invoice Type.
IF the user asks what Date quick filters are available, THEN list Today, Past 7 days, This Month, and Last Month.
IF the user asks what the default date range is, THEN answer that the default is rolling Past 7 days from the day the report is opened.
IF the user asks what Invoice Type options are available, THEN list Select all, Invoice Deleted, Invoice Changed, Commission Changed, Layaway Deleted, Employee tip Changed, Employee Non-Commission Changed, and Invoice Location Changed.
IF the user asks what columns are visible, THEN list Invoice Id, Log Type Name & Date, Performed By, Information, and Actions.
IF the user asks whether Change Logs can be exported, THEN answer that Download in Excel exports the current filtered table view.
IF the user asks whether Change Logs is Region-scoped, THEN answer No; it is global to the entire account and is not scoped to any specific Region.
IF the user asks why no logs are visible, THEN check date range, Invoice Type selections, and whether invoice changes occurred in the selected period. Do not tell the user to change Region as a normal Change Logs troubleshooting step.
IF the user asks who can access Change Logs, THEN answer Owner or a user with the change_log privilege.
IF the user says Full Owner, THEN treat that as the customer synonym for Owner.
IF the user asks whether Partial Owner, Regional Manager, Secretary, Inventory Manager, Product Manager, Sales Representative, Technician, or Marketing Manager can access Change Logs, THEN answer that those role labels do not grant Change Logs access by themselves; the user needs Owner access or the change_log privilege.
IF the user asks whether deleted invoices can be opened from Change Logs, THEN answer No; Open Invoice is not available for Invoice Deleted rows.
IF the user asks whether non-deleted invoice-change rows can be opened from Change Logs, THEN answer Yes; Open Invoice opens the invoice in a pop-up/modal.
IF the user asks how far back Change Logs goes, THEN answer that Change Logs documents invoice-change audit activity from the beginning of account creation.
IF the user asks whether Change Logs entries can be edited or deleted, THEN answer No; the log is permanent for security purposes.
IF the user asks whether a change can be restored or reversed from Change Logs, THEN answer No; there is no restore option in Change Logs.
IF the user asks whether a deleted invoice can be restored, THEN answer No; invoice deletion is permanent and irreversible.
IF the user asks whether Change Logs stores the full original invoice state, THEN answer No; there is no log of the full original invoice state.
IF the user asks how to correct a non-deleted changed invoice, THEN explain that the invoice can be edited again where invoice editing is available, and that new edit creates another change-log entry.
IF the user asks about payroll-change history specifically, THEN route to Back Office -> Users -> Payroll Changes, not Users -> Change Logs.
Support Boundary

Allowed answer depth:

Provide the documented path and direct URL.
Explain the invoice audit-trail purpose.
Explain account-global scope.
Explain documented access: Owner or change_log.
Explain visible filters, options, table columns, export, and Open Invoice behavior.
Explain permanent log behavior, no edit/delete of log entries, no restore from Change Logs, and beginning-of-account coverage.
Provide first-pass no-results troubleshooting based on date range, Invoice Type selections, and whether an invoice change occurred.

Escalation trigger:

User asks why a specific real invoice change is missing after checking date range, Invoice Type selections, and whether the invoice action occurred.
User asks whether a log entry proves, reverses, restores, or validates a business action beyond the visible audit trail.
User still cannot access the page after confirming Owner or change_log access.

Hard-stop condition:

After the documented access/visibility/no-results checks, do not continue troubleshooting undocumented Change Logs behavior. Offer to connect the user with support.

Forbidden answer patterns:

Do not describe Change Logs as Region-scoped.
Do not tell users to change Region as the normal troubleshooting step for missing Change Logs data.
Do not claim Change Logs is a complete compliance guarantee.
Do not claim Change Logs entries can be edited or deleted.
Do not claim Change Logs can restore or reverse invoice changes.
Do not claim deleted invoices can be restored.
Do not claim Change Logs stores the full original invoice state.
Do not infer event categories beyond the documented Invoice Type options.
Do not use Change Logs as the answer for payroll timesheet-change audit questions; use Payroll Changes.
7. Troubleshooting
User Cannot See Users -> Change Logs
Confirm the user is in Back Office, not Storefront.
Confirm the user is opening Back Office -> Users -> Change Logs.
Confirm the user has the Owner role or the change_log privilege.

If access is missing:

The user should request access from the account Owner.

Do not use Region troubleshooting for Change Logs access:

Change Logs is account-global and is not scoped to a specific Region.
Access Denied

Documented standard message: Access denied: User lacks the necessary authorization to this page.

Resolution:

Request Owner access or a role/custom access setup with the change_log privilege.
Do not tell the user to self-assign access.
No Change Logs Are Visible

Check:

Date range: Today, Past 7 days, This Month, Last Month, From, or To.
Invoice Type selections: confirm the relevant action type is selected, or use Select all.
Whether the invoice action actually occurred during the selected period.

Do not tell the user to switch Regions as a normal no-results fix:

Change Logs is global to the account and not Region-scoped.
User Wants Payroll Change Logs

If the user asks about timesheet changes, employee hours changes, automatic checkout logs, or payroll-change review:

Use Back Office -> Users -> Payroll Changes.
Do not route payroll-change audit questions to Users -> Change Logs.
8. FAQs
Where is the Change Logs page in Nova Back Office?

Go to Back Office -> Users -> Change Logs or open https://backoffice.novapointofsale.com/users/change-logs.

What is Users -> Change Logs used for in Nova?

Users -> Change Logs provides an account-global audit trail for invoice changes, such as deleted invoices, edited invoices, changed commission, layaway deletion, employee tip changes, employee non-commission changes, and invoice location changes.

What should I use if an invoice disappeared in Nova?

Use Back Office -> Users -> Change Logs and check the date range and Invoice Type filter for Invoice Deleted.

Where can I see who deleted an invoice in Nova?

Use Back Office -> Users -> Change Logs. Invoice Deleted rows can show the invoice ID, date/time, performed-by user, and information about the deleted invoice.

Where can I see who edited an invoice in Nova?

Use Back Office -> Users -> Change Logs. The table can show invoice-change rows with the invoice ID, date/time, performed-by user, information, and the Open Invoice action when available.

Where can I see who changed invoice commission in Nova?

Use Back Office -> Users -> Change Logs and include Commission Changed in the Invoice Type filter.

Is Users -> Change Logs scoped by Region?

No. Users -> Change Logs is global to the entire account and is not scoped to a specific Region.

What is the default date range on Users -> Change Logs?

The default date range is Past 7 days, rolling seven days back from the day the report is opened.

What filters are available on Users -> Change Logs?

The visible filters are Invoice Type, Date: quick filters, From:, and To:. The visible Date quick filters are Today, Past 7 days, This Month, and Last Month.

What Invoice Type options are available on Users -> Change Logs?

The visible Invoice Type options are Select all, Invoice Deleted, Invoice Changed, Commission Changed, Layaway Deleted, Employee tip Changed, Employee Non-Commission Changed, and Invoice Location Changed.

What columns are visible on Users -> Change Logs?

The visible columns are Invoice Id, Log Type Name & Date, Performed By, Information, and Actions.

Can I export Users -> Change Logs?

Yes. Download in Excel exports the current filtered table view.

Can I open an invoice from Users -> Change Logs?

Yes, for non-deleted invoice action rows. Click Open Invoice in the Actions column to open a pop-up/modal with the invoice.

Can I open a deleted invoice from Users -> Change Logs?

No. Open Invoice is not available for Invoice Deleted rows.

Who can access Users -> Change Logs?

Users can access the page if they have the Owner role or the change_log privilege.

Is Full Owner the same as Owner for Users -> Change Logs?

Owner is the correct system role label. Customers may say Full Owner, and support answers should treat Full Owner as a synonym for Owner.

Why are there no rows in Users -> Change Logs?

Check the date range, selected Invoice Type options, and whether invoice changes occurred in the selected period. Do not switch Regions as a normal fix because Change Logs is account-global.

Can I delete or edit an entry in Users -> Change Logs?

No. Change Logs entries cannot be deleted or edited. The log is permanent for security purposes.

Can I restore or reverse a change from Users -> Change Logs?

No. Users -> Change Logs is an audit trail only. There is no restore or reverse action from this page.

Can I restore a deleted invoice from Users -> Change Logs?

No. If an invoice was deleted, there is no way to restore it from Change Logs. Invoice deletion is permanent and irreversible.

Can I see the full original invoice state in Users -> Change Logs?

No. Change Logs records the invoice-change event, but there is no log of the full original invoice state.

Can I correct a changed invoice after reviewing Users -> Change Logs?

Yes, if the invoice still exists and invoice editing is available, the invoice can be edited again. That new edit creates another change-log entry.

How far back does Users -> Change Logs keep records?

Users -> Change Logs documents invoice-change audit activity from the beginning of account creation.

Where do I see payroll change logs in Nova?

Use Back Office -> Users -> Payroll Changes for payroll-change logs. Payroll Changes is separate from Users -> Change Logs.

9. Intent Map
Intent Group: Users Change Logs - Invoice Audit Trail

Intent Name: Route Invoice Audit Questions To Change Logs
Intent Goal: Route users to the Change Logs page when they need to audit invoice deletion or invoice edits.
Training Phrases:

My invoice disappeared
Who deleted this invoice?
Who edited this invoice?
Something changed on my invoice
Why does this invoice look different?
Who changed the commission?
Where can I see invoice changes?
I need an audit trail for an invoice
How do I audit invoice edits?
How do I see invoice change history?

Knowledge Sources to Use:

Users Change Logs - AI Knowledge V3.md
Users Change Logs - AI FAQ V3.csv

Expected Answer Shape:

State that Users -> Change Logs is the account-global invoice audit trail.
Provide Back Office -> Users -> Change Logs and direct URL.
Explain date range and Invoice Type filters.
Mention Open Invoice for non-deleted rows.
Intent Group: Users Change Logs - Filters And Options

Intent Name: Explain Change Logs Filters
Intent Goal: Explain date range and action-type filtering.
Training Phrases:

What filters are on Change Logs?
What are the Change Logs options?
What Invoice Type options can I choose?
How do I see last month's change logs?
What does Past 7 days mean?
What is the default date range?
How do I change the date on Change Logs?
Can I filter Change Logs by invoice type?
What are all the log type options?
How do I select all change log types?

Knowledge Sources to Use:

Users Change Logs - AI Knowledge V3.md
Users Change Logs - AI FAQ V3.csv

Expected Answer Shape:

List Date quick filters.
State default is rolling Past 7 days.
List From and To fields.
List all Invoice Type options.
State all action types are selected by default.
Intent Group: Users Change Logs - Export And Open Invoice

Intent Name: Explain Change Logs Actions
Intent Goal: Explain Download in Excel and Open Invoice.
Training Phrases:

Can I export Change Logs?
Does Download in Excel export everything?
What does Download in Excel export?
Can I open the invoice from Change Logs?
Why can't I open a deleted invoice?
What does Open Invoice do?
Does Open Invoice open a pop-up?
Can I review the invoice from the log?
Can I open commission changed invoice?
Can I open invoice changed row?

Knowledge Sources to Use:

Users Change Logs - AI Knowledge V3.md
Users Change Logs - AI FAQ V3.csv

Expected Answer Shape:

State Download in Excel exports the current filtered table view.
State Open Invoice opens an invoice pop-up/modal.
State Open Invoice is available for non-deleted invoice action rows.
State Invoice Deleted rows cannot be opened.
Intent Group: Users Change Logs - Permanent Log Behavior

Intent Name: Explain Permanent Change Log Limits
Intent Goal: Explain that Change Logs is a permanent audit trail, not a restore or editing tool.
Training Phrases:

Can I delete a change log entry?
Can I edit a change log entry?
Can I restore an invoice from Change Logs?
Can I reverse a change from Change Logs?
Can I undo a deleted invoice?
Is invoice deletion permanent?
Does Change Logs keep the original invoice?
Can I see the original invoice state?
How far back do Change Logs go?
Are Change Logs permanent?

Knowledge Sources to Use:

Users Change Logs - AI Knowledge V3.md
Users Change Logs - AI FAQ V3.csv

Expected Answer Shape:

State Change Logs records from the beginning of account creation.
State entries are permanent for security purposes and cannot be edited or deleted.
State there is no restore or reverse option in Change Logs.
State deleted invoices cannot be restored.
State there is no log of the full original invoice state.
For non-deleted invoices, explain the invoice can be edited again where invoice editing is available and the new edit creates another log entry.
Intent Group: Users Change Logs - Access

Intent Name: Change Logs Access
Intent Goal: Explain who can access Change Logs.
Training Phrases:

Who can access Change Logs?
Why can't I open Change Logs?
Why do I get access denied on Change Logs?
Do I need Owner access for Change Logs?
Is Full Owner enough for Change Logs?
What privilege gives Change Logs access?
What is change_log access?
Can Partial Owner see Change Logs?
Can Regional Manager see Change Logs?
How do I give someone Change Logs access?

Knowledge Sources to Use:

Users Change Logs - AI Knowledge V3.md
Users Settings - AI Knowledge Source V15.md for broader role setup

Expected Answer Shape:

State access requires Owner or change_log.
Treat Full Owner as a customer synonym for Owner.
State other role labels do not grant Change Logs access by themselves.
Route role assignment questions to Users Settings.
Intent Group: Users Change Logs - Scope And No Results

Intent Name: Change Logs Scope And Empty Results
Intent Goal: Explain account-global scope and no-results checks.
Training Phrases:

Is Change Logs by region?
Is Change Logs account wide?
Why don't I see change logs?
Why is Change Logs empty?
I changed region and still don't see logs
Do I need to select another region?
Why are there no invoice changes?
Why is today's Change Logs empty?
Why is this month's Change Logs empty?
How do I find old invoice changes?

Knowledge Sources to Use:

Users Change Logs - AI Knowledge V3.md
Users Change Logs - AI FAQ V3.csv

Expected Answer Shape:

State Change Logs is account-global and not Region-scoped.
Check date range.
Check Invoice Type selections.
Check whether the invoice action occurred in that period.
Do not recommend switching Regions as the normal fix.
10. Synonyms and Search Phrases
Change Logs
change log
invoice audit trail
invoice change log
invoice deleted log
deleted invoice
invoice changed
edited invoice
commission changed
invoice commission changed
invoice location changed
layaway deleted
employee tip changed
employee non-commission changed
invoice history
audit log
activity log
change history
change records
logs under Users
Back Office logs
Full Owner
Owner

Retrieval note:

Synonyms are retrieval boosters only.
They do not expand documented behavior beyond the Invoice Type options and rules documented in this article.
11. Quality Gate
Environment separation is explicit: Change Logs is a Back Office page.
Exact navigation path is documented.
Direct URL is documented.
Account-global scope is documented.
Region-scoped behavior is explicitly prohibited.
Required access is documented as Owner or change_log.
Full Owner is documented as a customer synonym for Owner.
The Why is documented as invoice audit trail.
Bot routing for missing/deleted/edited/commission-changed invoices is documented.
Default Past 7 days behavior is documented as rolling seven days back from the day the report is opened.
Invoice Type options are documented.
Download in Excel current-view export behavior is documented.
Open Invoice pop-up/modal behavior is documented.
Deleted invoice Open Invoice limitation is documented.
Permanent log behavior is documented.
Beginning-of-account coverage is documented.
No restore/reverse behavior is documented.
Deleted invoice irreversibility is documented.
No full-original-state log is documented.
Troubleshooting focuses on date range, action type, occurrence of invoice change, and access.
Standalone FAQs are included.
Embedded intent map is included.
Expected customer questions have affirmative documented answers or documented escalation boundaries.
