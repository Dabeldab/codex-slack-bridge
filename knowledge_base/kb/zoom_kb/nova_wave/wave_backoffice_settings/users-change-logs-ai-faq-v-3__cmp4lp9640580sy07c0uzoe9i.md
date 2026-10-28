# Users Change Logs AI FAQ V 3

Source: Zoom Knowledge Library browser export
KB ID: n669kbqjs5h1h01ev55em8ki
Article ID: cmp4lp9640580sy07c0uzoe9i
Product lane: Nova Wave
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/n669kbqjs5h1h01ev55em8ki/articles/cmp4lp9640580sy07c0uzoe9i
Updated: 05/13/2026, 05:58 PM

Extract table (Keep table structure)
question	answer
Where is the Change Logs page in Nova Back Office?	Go to Back Office -> Users -> Change Logs or open https://backoffice.novapointofsale.com/users/change-logs.
What is Users -> Change Logs used for in Nova?	Users -> Change Logs provides an account-global audit trail for invoice changes, such as deleted invoices, edited invoices, changed commission, layaway deletion, employee tip changes, employee non-commission changes, and invoice location changes.
What should I use if an invoice disappeared in Nova?	Use Back Office -> Users -> Change Logs and check the date range and Invoice Type filter for Invoice Deleted.
Where can I see who deleted an invoice in Nova?	Use Back Office -> Users -> Change Logs. Invoice Deleted rows can show the invoice ID, date/time, performed-by user, and information about the deleted invoice.
Where can I see who edited an invoice in Nova?	Use Back Office -> Users -> Change Logs. The table can show invoice-change rows with the invoice ID, date/time, performed-by user, information, and the Open Invoice action when available.
Where can I see who changed invoice commission in Nova?	Use Back Office -> Users -> Change Logs and include Commission Changed in the Invoice Type filter.
Is Users -> Change Logs scoped by Region in Nova?	No. Users -> Change Logs is global to the entire account and is not scoped to a specific Region.
What is the default date range on Users -> Change Logs in Nova?	The default date range is Past 7 days, rolling seven days back from the day the report is opened.
What filters are available on Users -> Change Logs in Nova?	The visible filters are Invoice Type, Date quick filters, From, and To. The visible Date quick filters are Today, Past 7 days, This Month, and Last Month.
What Invoice Type options are available on Users -> Change Logs in Nova?	The visible Invoice Type options are Select all, Invoice Deleted, Invoice Changed, Commission Changed, Layaway Deleted, Employee tip Changed, Employee Non-Commission Changed, and Invoice Location Changed.
What columns are visible on Users -> Change Logs in Nova?	The visible columns are Invoice Id, Log Type Name & Date, Performed By, Information, and Actions.
Can I export Users -> Change Logs in Nova?	Yes. Download in Excel exports the current filtered table view.
Does Download in Excel export all Users -> Change Logs data in Nova?	No. Download in Excel exports only the current table view based on the selected date range and selected Invoice Type options.
Can I open an invoice from Users -> Change Logs in Nova?	Yes, for non-deleted invoice action rows. Click Open Invoice in the Actions column to open a pop-up/modal with the invoice.
Can I open a deleted invoice from Users -> Change Logs in Nova?	No. Open Invoice is not available for Invoice Deleted rows.
Why is Open Invoice disabled in Users -> Change Logs in Nova?	Open Invoice is not available for Invoice Deleted rows. For non-deleted invoice action rows, Open Invoice opens the invoice in a pop-up/modal.
Who can access Users -> Change Logs in Nova?	Users can access Users -> Change Logs if they have the Owner role or the change_log privilege.
Is Full Owner the same as Owner for Users -> Change Logs in Nova?	Owner is the correct system role label. Customers may say Full Owner, and support answers should treat Full Owner as a synonym for Owner.
Can a Partial Owner access Users -> Change Logs in Nova?	Partial Owner does not grant Users -> Change Logs access by itself. The user needs Owner access or a custom role with the change_log privilege.
Can a Regional Manager access Users -> Change Logs in Nova?	Regional Manager does not grant Users -> Change Logs access by itself. The user needs Owner access or a custom role with the change_log privilege.
Can a Secretary access Users -> Change Logs in Nova?	Secretary does not grant Users -> Change Logs access by itself. The user needs Owner access or a custom role with the change_log privilege.
How do I give someone access to Users -> Change Logs in Nova?	Give the user Owner access or a role/custom access setup with the change_log privilege. Role setup is managed from Back Office -> Users -> Settings -> USER ACCESS LEVEL.
Why do I get access denied when opening Users -> Change Logs in Nova?	Confirm the user has the Owner role or the change_log privilege. If access is missing, request access from the account Owner.
Why are there no rows in Users -> Change Logs in Nova?	Check the date range, selected Invoice Type options, and whether invoice changes occurred in the selected period. Do not switch Regions as a normal fix because Change Logs is account-global.
Should I change Region if Users -> Change Logs is empty in Nova?	No. Users -> Change Logs is global to the entire account and is not scoped to a specific Region. Check the date range, Invoice Type selections, and whether invoice changes occurred.
Can I delete or edit an entry in Users -> Change Logs in Nova?	No. Users -> Change Logs entries cannot be deleted or edited. The log is permanent for security purposes.
Can I restore or reverse a change from Users -> Change Logs in Nova?	No. Users -> Change Logs is an audit trail only. There is no restore or reverse action from this page.
Can I restore a deleted invoice from Users -> Change Logs in Nova?	No. If an invoice was deleted, there is no way to restore it from Users -> Change Logs. Invoice deletion is permanent and irreversible.
Can I see the full original invoice state in Users -> Change Logs in Nova?	No. Users -> Change Logs records the invoice-change event, but there is no log of the full original invoice state.
Can I correct a changed invoice after reviewing Users -> Change Logs in Nova?	Yes, if the invoice still exists and invoice editing is available, the invoice can be edited again. That new edit creates another change-log entry.
How far back does Users -> Change Logs keep records in Nova?	Users -> Change Logs documents invoice-change audit activity from the beginning of account creation.
Where do I see payroll change logs in Nova?	Use Back Office -> Users -> Payroll Changes for payroll-change logs. Payroll Changes is separate from Users -> Change Logs.
