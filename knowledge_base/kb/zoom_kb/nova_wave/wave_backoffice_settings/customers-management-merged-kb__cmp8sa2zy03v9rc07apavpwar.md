# Customers Management Merged KB

Source: Zoom Knowledge Library browser export
KB ID: n669kbqjs5h1h01ev55em8ki
Article ID: cmp8sa2zy03v9rc07apavpwar
Product lane: Nova Wave
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/n669kbqjs5h1h01ev55em8ki/articles/cmp8sa2zy03v9rc07apavpwar
Updated: 05/16/2026, 04:34 PM

Extract table (Keep table structure)
Customer Management Overview

Customers > Management is Nova's CRM/customer list screen.

Reference	Value
UI label	Customers > Management
Environment	Back Office (Manager Area)
Navigation path	Back Office → Customers → Management
Direct URL	https://backoffice.novapointofsale.com/customers/management

The screen is used to search, review, create, edit, view, and export customer records for the account. It helps businesses manage customer relationships by storing customer contact information, purchase association history, customer notes, marketing preferences, shipping information, profile images, and custom customer fields.

Support posture: Customer Management is still under development. Provide guided self-service for documented behavior only. If a user asks about behavior not documented in this article, do not guess or infer — state that the behavior is not documented and escalate to human support.

In Nova support language:

"customer profile" = "customer record"
"customer database" = Customers → Management
"customer list" = the table on Customers → Management
"store", "shop", and "location" may be used interchangeably, but use the exact UI label Location when giving navigation paths
Access and Permissions

Users who can access Customer Management:

Full Owner / Owner
Partial Owner
Marketing Manager
Custom roles with the CRM management privilege

Internal privilege label: crm_management

If a user lacks the required access, Nova shows: Access denied: User lacks the necessary authorization to this page.

Owners have full access everywhere in Nova. Only Owners can assign roles to users. If a user needs Customer Management access, they should request the required role or custom role from the Owner of the account.

Region and role model: A user can belong to multiple Regions. The user's role set applies across all Regions that user can access. Nova does not support different role sets per Region for the same user.

Do not claim that Regional Manager automatically has Customer Management access. Regional Manager does not inherit lateral-role access unless the relevant role or custom permission is assigned.

Scope: Customer Records are Account-wide
Customer records in Customers > Management are global/account-wide.
Customers are not scoped to a Region or Location on this screen.
There is currently no Region filter on this screen.
There is currently no Location filter on this screen.
Date filters and search filters help narrow what is visible on the screen, but they do not change the account-wide nature of the CRM data.
Download in Excel exports the entire CRM and does not respect filters or search.

Important support rule: Do not tell the user to change Region or Location to filter Customer Management results. Region/Location context may matter when finding customers indirectly through invoices, user reports, or layaways, because those source records may be tied to sales/reporting context.

How to Open Customer Management
Go to Back Office.
Open Customers in the left sidebar.
Click Management.
Direct URL: https://backoffice.novapointofsale.com/customers/management
Customer Management Screen Layout
Top-bar context
Element	Description
Region	Top-bar Region selector. Customer records are not Region-scoped on this screen, but Region context may apply to invoices, layaways, and user reports.
Location	Top-bar Location selector. Customer records are not Location-scoped on this screen.
Sidebar

The Customers sidebar entry exposes:

Management — customer records, customer lookup, customer purchase summaries, customer exports (this article)
Layaways — layaway invoice lookup and management (separate article)
Header summary
Number of Total Customers — total count of customer records currently visible based on active search/filter state.
Date and filter controls
Field	Behavior
From Date	Start of date range filter
To Date	End of date range filter
Filter by Purchase Date	Filters list to customers who purchased within the date range
Filter by Date Added	Filters list to customers whose records were added within the date range
Default	Removes date filtering and shows the normal customer list
Actions panel
Action	Behavior
Add New Customer	Opens the Create Customer workflow
Download in Excel	Exports the entire CRM customer list to Excel. Does not respect search, date filters, Region, or Location.
Search

The Search customer bar supports searching by:

Customer name
Customer email
Customer phone number
Customer List Columns Reference

The customer list table on Customers > Management contains the following columns:

Column	Description
Id	Unique customer identifier. Click the Id to open Customer Details.
Region	Shows Region information for context. Customer records are not Region-scoped.
Customer Info	Customer name and primary contact reference.
Phone	Customer phone number.
Gender	Customer gender field.
# of Invoices	Number of invoices in the system attached to this customer (a count, not a list).
Invoice Total	Customer's total purchase / invoice value across all attached invoices.
Last Purchase Date	Most recent purchase date for this customer.
Notes	Customer notes from the customer record.
Added By	Employee who added or created the customer record. Does not mean the customer permanently belongs to that employee.
Date Added	Date the customer record was created in Nova. Not the same as last edited date.
Actions	Row-level Options menu — opens Edit or View for that customer.

Negative rules:

Do not treat Added By as customer ownership, salesperson assignment, last editor, or full audit history.
Do not tell users that customer records belong to one Region or one Location. Customer records are global/account-wide in Customer Management.
Do not treat # of Invoices as a list of invoice records. It is a count.
Do not treat Invoice Total as an invoice-detail screen. It is a total purchase/invoice value metric.
Do not treat Date Added as last edited date.
Field-to-Question Natural Language Mapping

Users often ask customer questions in natural language instead of naming the exact list field. Map natural-language questions to the documented Customer Management fields first.

User wording	Customer Management answer
Who added this customer? / Who created this customer? / Which employee created this customer?	Use the Added By column.
Which employee does this customer belong to?	Customer records do not permanently belong to one employee. Use Added By only to show who added the customer record.
When was this customer added? / When was this customer created?	Use the Date Added field.
When did this customer last purchase? / When did this customer last buy something?	Use the Last Purchase Date field.
How much has this customer spent? / What is the customer's purchase total?	Use Invoice Total. It represents the customer's total purchases for invoices where that customer is attached.
How many invoices does this customer have? / How many purchases does this customer have?	Use # of Invoices. It represents the count of invoices where that customer is attached.
Can I see customer notes?	Use the Notes column or open the customer card.
Can I see the customer's email or phone number?	Use the customer list contact fields and the search bar. The search bar supports name, email, and phone number.
Can I see the customer's address?	Open the customer card and review the Shipping Information tab. For list-level review or analysis, use Download in Excel.
Can I see which region a customer belongs to?	Customer records are account-wide/global and do not belong to one Region. The list may show Region information for context, but there is no Region filter and the customer record is not Region-scoped.
Can I see which location a customer belongs to?	Customer records are account-wide/global and do not belong to one Location in Customer Management. Use invoices, layaways, reports, or Excel export analysis when the question is about location-related activity.
Who last edited this customer? / When was this customer last edited? / Can I see all customer changes?	Not documented in Customer Management. Added By is documented; full customer edit history, last editor, and last edited date are not documented.
Searching for a Customer
Open Back Office → Customers → Management.
Verify the correct Region and Location in the top bar (for context only — search results are account-wide).
Leave the filter mode on Default unless a date-based search is specifically needed.
Use the Search customer bar.
Search by name, email, phone number, or customer ID when available.
Click the customer Id in the table to open Customer Details.

If the customer is missing:

Switch the page back to Default.
Clear the From Date and To Date fields.
Check the top-bar Region and Location (in case the user's access is restricted).
Search again with fewer characters or a phone number fragment.
Verify the user has access to Customers > Management and the relevant Region.
Try alternate lookup paths (employee, invoice, or layaway) if context is known.
Filtering by Date — Purchase Date vs Date Added

The screen offers two distinct date filter modes. They answer different questions.

Filter by Purchase Date

Use this when the user asks for:

Customers who purchased during a date range
Customers who bought something last week
Customer purchase activity by date

Steps: Enter From Date → Enter To Date → Select Filter by Purchase Date → Review filtered list.

Purchase-date filtering is about the customer's purchase activity, not when the customer record was created.

Filter by Date Added

Use this when the user asks for:

Customers added today
Customers created last month
New customers in a date range
Customer records added during a selected period

Steps: Enter From Date → Enter To Date → Select Filter by Date Added → Review filtered list.

Date-added filtering is about when the customer record was added, not when the customer purchased something.

Default Mode

Default removes date filtering and returns to the normal customer list. Use it when the user needs the unfiltered list, or when they were filtering by date and now cannot find a customer.

Adding a New Customer

The best practical path during daily operations is to create or attach the customer during a sale in the Storefront. A customer can also be created without completing a purchase, and customer creation is not restricted to manager roles — employees can create customers from the Storefront as well.

This article documents the Back Office path.

Back Office steps
Open Back Office → Customers → Management.
Click Add New Customer.
The Create Customer workflow opens.
Complete the required Customer Information fields (marked with an asterisk).
Optional details may be added on Shipping Information or Custom Fields after required fields are valid.
Click Save.
Tabs on Create Customer
Customer Information — name, contact, marketing preferences, photo, notes
Shipping Information — address fields
Custom Fields — business-specific custom customer data

Important: Required CRM fields must be valid on the Customer Information tab before the user can move to Shipping Information or Custom Fields or save the customer.

Storefront customer creation

Storefront customer creation is possible, including creating a customer who does not actually purchase anything. The detailed Storefront workflow is outside this article and is covered in the Storefront knowledge base.

Customer Information Fields and Validation

Visible Customer Information controls:

Reset Image — clears the customer profile image
Change Picture — uploads a customer profile image (supported formats: JPG, PNG, JPEG)
First Name *
Middle Initials *
Last Name
Email
Check to Opt-out of text campaigns
Receive special events Notifications
Check to Opt-out of email campaigns
Mobile No *
Gender
Date of Birth
Notes
Save

(Asterisks indicate fields that are mandatory in the documented example account. Required fields are configurable per location — see CRM Mandatory Fields below.)

Validation rules
Field	Rule
First Name	Letters only. Numbers and symbols are not allowed. Mandatory only if configured in CRM Mandatory Fields.
Middle Initials	Letters only. Numbers and symbols are not allowed.
Last Name	Letters only. Numbers and symbols are not allowed.
Email	Simple format validation. Must contain an at sign. Nova does not verify whether the email address is real.
Mobile No	No documented format restriction.
Notes	No documented character limit.
Change Picture	Customer-facing supported image formats: JPG, PNG, JPEG.
Common validation errors
"First name is required" — fill the First Name field on Customer Information.
"Middle initial is required" — fill the Middle Initials field on Customer Information.
"Mobile phone is required" — fill the Mobile No field on Customer Information.

Required fields can vary by location. If the user thinks a field should not be required, the business can change which fields are mandatory in Locations → Settings → Edit → CRM Mandatory Fields.

CRM Mandatory Fields (Location Settings)

CRM Mandatory Fields control which customer profile fields are required when creating or saving a customer at a given location.

Configuration path: Back Office → Locations → Settings → Edit → CRM Mandatory Fields
Live-verified URL pattern: /location/settings/crm-mandatory-fields/{locationId}/{regionId}

Steps to change required fields
Go to Back Office → Locations → Settings.
Find the location.
Click Edit in the location row.
Click CRM Mandatory Fields.
Check the customer fields that should be required for that location.
Uncheck the customer fields that should not be required.
Click SAVE.
Fields that can be made mandatory

The CRM Mandatory Fields page shows these options, grouped in three columns:

Left column: First Name, Middle Initial, Last Name, Home Phone, Birthday
Middle column: Mobile Phone, Email, Address 1, Address 2, Notes
Right column: City, State, Country, Zipcode

Default state: No CRM mandatory fields are selected by default. Each location is configured by the customer.

Important:

A checked box means the field is required at that location.
An unchecked box means the field is optional at that location.
Required customer fields can vary by location. Do not tell the user a field is always required across every account or location.
In one documented St-Hyacinthe example, only First Name was checked. Do not present this as the default for every account or location.
Shipping Information Tab

Fields:

Address 1
Address 2
City
State
Country
Zip Code

No documented validation rules for shipping fields. Do not invent rules.

To update a customer's shipping address: open the customer Id → Customer Details → Shipping Information → edit fields → Save.

Custom Fields Tab

Nova allows users to create customer custom fields beyond the default customer fields. Use cases include membership status or other business-specific CRM data.

Workflow
Open the customer card.
Open Custom Fields.
Click ADD NEW CUSTOM FIELD.
Select an existing custom field from the dropdown, or add a new one.
If adding a new custom field, enter the Field Name.
Select the Field type.
Confirm the custom field row.
Save the customer card.
Custom field types available
Text
Number
Email
Date
Editing and Viewing a Customer
Edit
Open Back Office → Customers → Management.
Find the customer in the list.
Open Options (Actions menu) for the customer row.
Select Edit.
Update available customer fields.
Click Save.

Edit uses the same customer-card layout as Add New Customer (Customer Information, Shipping Information, Custom Fields tabs).

View
Open Back Office → Customers → Management.
Find the customer in the list.
Open Options for the customer row.
Select View.
Nova opens the customer card in read-only mode.

View looks similar to Edit but fields cannot be changed.

Customer Details Dialog

Open Customer Details by clicking the customer Id in the table.

Customer Details tabs
Customer Information — profile fields (name, mobile, gender, date of birth, notes, marketing preferences)
Shipping Information — address fields
Custom Fields — business-specific custom fields
Invoices — invoices attached to this customer
Products — products purchased by this customer
Layaways — layaways attached to this customer
Customer Details — Invoices Tab

Shows invoices attached to this customer record. For full invoice actions (refunds, payment corrections, edits), route to Accounting → Invoices — not Customer Details.

If a Print Invoice action is visible on a row, it can be used to print directly from the customer profile.

Customer Details — Products Tab

Shows products purchased by this customer based on attached invoices.

Customer Details — Layaways Tab

Shows layaways attached to this customer. For the full layaway report, status, paid/due totals, layaway codes, or layaway export, route to Customers → Layaways.

Marketing Preferences

Marketing-related controls live on the Customer Information tab:

Check to Opt-out of text campaigns — opts the customer out of text/SMS marketing
Check to Opt-out of email campaigns — opts the customer out of email marketing
Receive special events Notifications — opts the customer in to event-specific notifications

These are customer-level preferences only. Customers → Management does not include marketing campaign setup tools. If the user asks how to set up or send marketing campaigns, state that Customer Management only shows customer-level opt-out/notification controls and route to the appropriate marketing tool when documented.

Downloading the Full CRM to Excel
Open Back Office → Customers → Management.
Use Actions on the right side of the screen.
Click Download in Excel.

Important: Download in Excel exports the entire CRM/customer list. It does not respect:

The current search text
Date filters
Filter by Purchase Date
Filter by Date Added
Region selection
Location selection

The export is not limited to the currently visible filtered list — it always downloads everything.

Do not tell the user that Download in Excel exports only the visible, filtered, searched, region-specific, or location-specific results.

Advanced Filtering Using Excel

When the user asks how to filter, sort, segment, analyze, or look up customers by criteria that are not fully handled by the visible Customer Management search and date filters, route the user to Download in Excel.

The Customer Management screen supports:

Basic search by customer name, email, or phone number
Date filtering by Purchase Date or Date Added

For anything beyond that — sorting, segmenting, complex filtering, multi-field analysis — use Excel.

Recommended answer pattern

For simple lookup, use Back Office → Customers → Management and search by name, email, or phone number, or use the available date filters. For stronger filtering, sorting, segmentation, or analysis, use Download in Excel. The export downloads the full CRM with no filtering, so the user can run filters and analysis in Excel.

Examples that should route to Excel

Filtering by region, location, store, employee, invoice total, highest spenders, lowest spenders, invoice count, last purchase activity, customers who have not purchased recently, customers with no purchase activity, missing email, missing phone, gender, address, notes, display name, customer ID, duplicate customers, and any advanced CRM segmentation request not supported directly by the Customer Management page filters.

Do not name or explain ambiguous exported Excel column headers in customer-facing answers — current export contains repeated or unclear headers. Describe the workflow generically: download the full CRM, open in Excel, identify the relevant data, filter/sort/analyze there.

Customer Lookup — Primary and Alternate Paths

Customers > Management is the primary lookup screen. A customer can also be found indirectly when the user remembers other context.

Primary path: Customers > Management

Use when the user knows: customer name, email, or phone number.
Path: Back Office → Customers → Management

Alternate path: Users > Report > My Customers

Use when the user knows which employee added the customer, or wants to review customers added by a specific employee during a date range.

Go to Back Office → Users → Report.
Select the relevant employee and date range.
Open the My Customers tab or section.
Use Open Customer where available.
Alternate path: Accounting > Invoices

Use when the user remembers approximate sale details (date, time, location, invoice context).

Go to Back Office → Accounting → Invoices.
Locate the invoice using known context.
Open the invoice detail.
Review the customer attached to the invoice, if any.

If no customer was attached to the invoice, do not claim that the invoice can identify the customer.

Alternate path: Customers > Layaways

Use when the user remembers approximate layaway details (date, time, location, layaway context).

Go to Back Office → Customers → Layaways.
Widen the Layaways date range to include when the layaway was created or paid.
Locate the layaway using known context.
Open the related layaway/invoice context.
Review the customer attached to that layaway, if available.
Customer Creation Paths (Storefront vs Back Office)

Customers can be created from more than one area of Nova.

Best practical path during daily operations: create or attach the customer during a sale in the Storefront.
Back Office path documented here: Back Office → Customers → Management → Add New Customer.
Storefront creation is also possible and is not limited to manager roles. Employees can create customers from the Storefront, including customers who do not complete a purchase.
Detailed Storefront customer creation steps are outside this article — see the Storefront knowledge base.
Customer Import (Support-Assisted)

Customer import into Nova is handled by support, not self-service.

Answer pattern: If a customer asks whether they can import or upload a customer list into Nova, answer that support can upload customer lists into the system and the customer should contact support for assistance.

Do not provide unsupported self-service import steps unless a documented self-service import workflow is added later.

Reading Nova Customers from a Third-Party CRM (API)

Nova offers an API that can be used for integrations, including reading customer data into a third-party CRM.

Answer pattern: If a customer asks whether they can connect Nova customer data to their own CRM, answer yes and direct them to contact support for more information about API access and integration details.

Do not provide API endpoints, authentication steps, data schemas, or integration implementation details unless they are documented in a dedicated API knowledge source.

Customer Deletion (Not Supported)

Customer deletion is not supported from Customer Management. A customer record cannot be deleted from this screen.

If a customer record should no longer be used, the user can:

Open Options → Edit on the customer row.
Change or clear the available customer details to nullify the record.
Click Save.

Do not tell users that Nova supports deleting, erasing, or removing a customer record from Customer Management. Do not tell the user that support, Back Office, or Storefront can delete a customer unless a future KB explicitly documents that behavior.

Duplicate Customers

Nova does not enforce duplicate-customer restrictions in this flow. A user may enter the same customer more than once.

Customer merge is not supported in Customer Management. If the user asks to merge duplicate customers, state that a clearly labeled Merge Customers action is not visible on the reviewed Customers screens.

Troubleshooting: User Cannot Access Customer Management

Check in this order:

Confirm the user is in Back Office, not Storefront.
Confirm the user is in the correct account.
Confirm the user has one of the required access paths: Full Owner / Owner, Partial Owner, Marketing Manager, or a custom role with the CRM management privilege.
If the user sees Access denied: User lacks the necessary authorization to this page., they should request access from the Owner of the account.

Do not troubleshoot Customer Management access by changing Region or Location. The screen is account-wide; the user's role/privilege must still authorize the page.

Troubleshooting: User Cannot Find a Customer
Search in Back Office → Customers → Management by customer name, email, or phone number.
Switch the filter mode to Default.
Clear From Date and To Date fields.
Check the top-bar Region and Location.
Try a shorter search or phone number fragment.
If the customer may have been added by a specific employee, check Users → Report → My Customers.
If attached to a known sale, locate the invoice from Accounting → Invoices using approximate date, time, location, then open the invoice and review the attached customer.
If attached to a layaway, locate the layaway from Customers → Layaways using approximate context, then open the related layaway/invoice context.
If still missing, verify the user has crm_management access and the relevant Region access.

Do not claim the customer does not exist unless the user has performed a complete search and has the required access.

Troubleshooting: Customer Count Changed or Looks Too Low

Use this scenario when the user asks:

"Why did my number of customers change?"
"It showed more customers a few minutes ago."
"Why are there fewer customers now?"
"Did my customers get deleted?"
"Why does Number of Total Customers show a smaller number?"
Check in this order
Check whether Search customer has text entered.
Check whether Filter by Purchase Date is selected.
Check whether Filter by Date Added is selected.
Check the From Date and To Date fields.
Switch back to Default.
Clear search and date filters.
Verify top-bar Region and Location.
If the count is still unexpectedly lower after filters are cleared, deletion or access changes may be possible — escalate or review with an authorized user.

Important support rule:

Do not immediately tell the user customers were deleted. The most common explanation is active search, filters, Region, or Location context.
Customer deletion is only a possible explanation after search/filter/access context are checked.
Customer Management does not support deletion, so unprompted deletion claims are almost never correct.
Troubleshooting: User Cannot Save a New Customer
Check required CRM fields first. Required fields are marked with an asterisk on the customer form.
Validation errors will name the field (e.g., "First name is required").
Required fields are configured in Back Office → Locations → Settings → Edit → CRM Mandatory Fields.
In some accounts only First Name is required by default; required field configuration varies per location.
Complete all required fields before saving.
If fields visibly contain data but the same required-field error remains, re-enter the value manually, click outside the field, then click Save again. If the error persists, collect the customer Id and escalate.

Do not tell the user the profile saved until the error messages clear or the application confirms the save.

Troubleshooting: User Cannot Move to Shipping Information or Custom Fields
Check required fields on Customer Information tab.
If First Name or another required field is missing, complete it first.
Then move to Shipping Information or Custom Fields.
Troubleshooting: Validation Errors
Validation message	Fix
"First name is required"	Fill First Name on Customer Information.
"Middle initial is required"	Fill Middle Initials on Customer Information.
"Mobile phone is required"	Fill Mobile No on Customer Information.
Name field rejected (numbers/symbols)	First Name, Middle Initials, Last Name allow letters only. Remove numbers and symbols.
Email field rejected	Use a valid-looking email format. Must contain an at sign. Nova does not verify whether the address is real.
Customer image will not upload	Use a supported image format: JPG, PNG, or JPEG.
Troubleshooting: Excel Export vs Filters

If a user expects Download in Excel to match their search or date filters, explain that Download in Excel exports the entire CRM/customer list. It does not apply:

The screen's search bar
Date filters
Filter by Purchase Date
Filter by Date Added
Region
Location

The full CRM is always exported. The user can then filter or sort in Excel.

Bot Logic: Core Routing Rules
IF user asks how to open Customer Management → answer with Back Office → Customers → Management and the direct URL https://backoffice.novapointofsale.com/customers/management.
IF user asks where to find a customer and gives name/email/phone context → route to Customer Management and the search bar.
IF user asks where to find a customer and gives employee-added context → route to Users → Report → My Customers.
IF user asks where to find a customer and gives sale/invoice context → route to Accounting → Invoices and explain that the customer can be reviewed from the invoice only if a customer was attached.
IF user asks where to find a customer and gives layaway context → route to Customers → Layaways.
IF user's question is ambiguous → answer with the primary CRM path first, then mention alternate lookup paths.
Bot Logic: Field Lookup and Natural Language Mapping
IF user asks who added/created/entered/made a customer → answer with Added By column.
IF user asks which employee a customer belongs to → explain customer records do not permanently belong to an employee; Added By shows who added the record.
IF user asks when a customer was added/created → use Date Added.
IF user asks when a customer last purchased → use Last Purchase Date.
IF user asks how much a customer spent / total purchases → use Invoice Total.
IF user asks how many invoices a customer has → use # of Invoices.
IF user asks whether a customer belongs to a Region or Location → state that Customer Management records are account-wide/global.
IF user asks who last edited a customer / when last edited / full history → state it is not documented; only Added By is documented.
Bot Logic: Access Rules
IF user asks who can access Customer Management → answer: Full Owner / Owner, Partial Owner, Marketing Manager, or custom roles with CRM management privilege.
IF user asks for the exact internal privilege label → provide crm_management.
IF user gets access denied → explain they likely lack the required CRM management access; route them to request the appropriate role from the Owner.
DO NOT claim that Regional Manager automatically has Customer Management access.
Bot Logic: Scope Rules
IF user asks whether Customer Management is filtered by Region or Location → answer no. Customer records are account-wide/global.
DO NOT instruct the user to switch Region or Location to filter Customers > Management.
IF the question involves invoices, layaways, or reports → Region/Location context may matter for those source records.
Bot Logic: Search and Filter Rules
IF user asks how to search CRM → answer that the search bar supports customer name, email, or phone number.
IF user asks about date filters → answer that the screen filters by Purchase Date or Date Added.
IF user asks what happens when there is no filter → answer the default is no filter (Default mode).
IF user asks for customers who purchased in a date range → use Filter by Purchase Date.
IF user asks for customers added/created/entered in a date range → use Filter by Date Added.
Bot Logic: Export Rules
IF user asks what Download in Excel exports → answer it exports the entire CRM/customer list.
IF user asks whether Excel respects filters/search → answer no — it downloads everything.
IF user needs stronger filtering or CRM analysis than the screen supports → recommend Download in Excel and explain Excel can be used to filter, sort, and analyze the full CRM.
DO NOT tell users Download in Excel exports only the visible/filtered/searched/region/location-specific results.
Bot Logic: Add/Edit/View Rules
IF user asks how to add a customer → answer the best way is during a sale, but customers can be created from Back Office and Storefront.
IF user asks for the Back Office path → route to Customers → Management → Add New Customer.
IF user asks whether only managers can create customers → answer no. Employees can create customers from the Storefront.
IF user asks whether a customer must purchase before being created → answer no.
IF user asks for exact Storefront customer creation steps → state the detailed Storefront workflow is outside this article.
IF user asks why Save is blocked / cannot move to another tab → check required CRM fields first.
IF user asks how to edit → route to Options → Edit.
IF user asks how to view without changing → route to Options → View (read-only).
IF user asks who added/owns/belongs to a customer → answer with Added By; clarify it means who added the record, not permanent ownership.
IF user asks whether there is a full audit trail → answer Customer Management shows Added By only; full audit trail is not documented.
IF user asks to delete/remove/erase a customer → answer no. Deletion is not supported. They can edit and clear details to nullify, then Save.
Bot Logic: Validation Rules
IF user asks why a name field is rejected → explain First Name/Middle Initials/Last Name allow letters only.
IF user asks why email is rejected → explain Nova performs simple email-format validation (requires an at sign) but does not verify whether the address is real.
IF user asks whether duplicates are blocked → answer no. Duplicate restriction is not enforced.
IF user asks why a customer image will not upload → advise using JPG, PNG, or JPEG.
Bot Logic: Custom Field Rules
IF user asks whether more fields can be created beyond defaults → answer yes, via Custom Fields on the customer card.
IF user asks about examples like membership status → explain custom fields can hold business-specific customer information.
IF user asks what types are available → list: Text, Number, Email, Date.
Bot Logic: Import and API Rules
IF user asks whether customers can be imported → answer support can upload customer lists; contact support.
IF user asks whether they can read Nova customers into their own CRM → answer yes, Nova offers an API; contact support for details.
DO NOT provide API endpoints, authentication, data schemas, or implementation guidance unless a dedicated API KB exists.
DO NOT provide self-service import steps unless a documented workflow is added later.
Bot Logic: Under-Development Boundary
Customer Management is under development. If a question concerns behavior not documented here → do not infer or invent behavior.
Allowed first-pass check: verify whether the question is covered by this article, related published KBs, or visible UI labels.
Escalation trigger: undocumented CRM behavior, system limits, automation beyond the documented API high-level answer, deletion, merge/deduplication, hidden validations, or unsupported image formats beyond the JPG/PNG/JPEG list.
Hard stop: do not provide guessed steps, backend assumptions, or undocumented workarounds.
Answer Safety: Do and Do Not
Do
Use exact Nova labels: Customers, Management, Add New Customer, Create Customer, Customer Details, Search customer, Filter by Purchase Date, Filter by Date Added, Default, Download in Excel, Added By, Date Added, Last Purchase Date, # of Invoices, Invoice Total.
Explain that required customer fields are controlled by Locations → Settings → Edit → CRM Mandatory Fields.
Tell users to complete fields marked with an asterisk on the customer form.
Tell users to click the customer Id to open Customer Details.
Remind users to verify Region and Location in the top bar when records seem missing.
Check Search, filters, Region, and Location before suggesting customer deletion when counts change.
Distinguish purchase date from date added.
Distinguish customer records from invoices and layaways.
Mention crm_management when the issue is access to Customer Management.
Clearly say when a requested action is not visible on the reviewed Customers screens.
Do Not
Invent fields in Shipping Information, Custom Fields, Invoices, Products, or Layaways tabs that are not documented or visible.
Invent steps for merge, delete, refund, invoice correction, or marketing-campaign setup from Customer Management.
State that a customer field is always required in every location — required fields are location-configurable.
Assume customers were deleted when the visible customer count changed.
Promise that a record exists if the user cannot find it.
Treat invoice actions, refunds, or payment corrections as customer-management actions.
Route layaway questions only to Customer Management when the actual feature is Customers → Layaways.
Tell users to switch Region or Location to filter Customer Management.
Claim Regional Manager has Customer Management access by default.
Treat Added By as customer ownership or salesperson assignment.
Expose or request unnecessary customer personal information in chat.
Synonyms and Search Phrases
Primary CRM terms
customer management
customer list
customer database
customer profile
customer record
CRM
CRM list
CRM screen
Customer lookup phrases
find a customer
look up a customer
search for a customer
find customer by phone
find customer by name
find customer by email
find customer by ID
customer added by employee
customer from invoice
customer from layaway
Custom field phrases
customer custom field
additional customer field
track membership
track loyalty status
custom CRM data
business-specific customer data
Customer creation phrases
add a customer
new customer
create a customer
enter a customer
add customer profile
add customer record
new client
Customer import and integration phrases
import customers
upload customer list
bulk customer add
read customers into our CRM
API customer access
connect Nova to my CRM
third-party CRM
customer data export to another system
Access phrases
cannot access Customer Management
access denied Customer Management
crm_management permission
give me CRM access
assign Customer Management role
request CRM access
Validation / required-field phrases
"first name is required"
"middle initial is required"
"mobile phone is required"
why is this field required
how do I change required fields
CRM Mandatory Fields
Date filter phrases
customers added today / this week / last month
new customers in a date range
customers who purchased in a date range
customers who bought last week
purchase date vs date added
Explicit Gaps and Do-Not-Infer Items

The following behaviors are not documented in this article and must not be inferred:

Customer deletion or erasing
Customer merge / deduplication
Full customer edit history (who/when last edited)
Last editor field
Marketing campaign setup or sending
API endpoints, authentication, schemas
Self-service customer import
Customer record location-scoping (records are account-wide)
Region-restricted customer records on Customer Management
Image format support beyond JPG, PNG, JPEG
Specific Storefront customer-creation steps (covered in Storefront KB)
Exact Excel export column meaning (export has ambiguous headers)
Whether Regional Manager has automatic Customer Management access (it does not)

If a user asks about any of these, state that the behavior is not documented and escalate or route to the appropriate KB/support.
