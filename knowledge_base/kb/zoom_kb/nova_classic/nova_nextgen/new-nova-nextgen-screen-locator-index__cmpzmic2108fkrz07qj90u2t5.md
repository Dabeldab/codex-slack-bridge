# New Nova / NextGen > Screen Locator Index

Source: Zoom Knowledge Library browser export
KB ID: xgc1pmuooitf8r7897796fje
Article ID: cmpzmic2108fkrz07qj90u2t5
Product lane: Nova Classic
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/xgc1pmuooitf8r7897796fje/articles/cmpzmic2108fkrz07qj90u2t5
Updated: 06/04/2026, 11:03 AM

Extract table (Keep table structure)

Use this file when the customer asks where something is located, what screen to open, or what a visible button, checkbox, toggle, column, or field is called. Pair this with the section walkthrough articles when the customer asks how to complete the task.

Standard Entry Path

For New Nova, open screens by clicking through the app:

Open the main tenant URL.
Log in if Your Session Has Expired is shown.
Select a Region in the top-right.
If the web Region dropdown is blank, click the blue menu button, open a screen such as Inventory, then check the Region dropdown again after the screen loads.
Click the blue menu button in the top-right.
Click the screen name.

Do not send customers directly to internal paths such as /products/listing or /transfers/index. Direct loading can show Server Error 404 - File or directory not found.

Screen Map
Customer is looking for	Open this screen	Menu path	Main controls and columns	Related how-to article
Sales overview, invoice totals, layaway code lookup, payment method activity, users at work	Dashboard	Blue menu > Dashboard	Location, date range, revenue cards, Revenue, Cost of Goods Sold, Invoices, Estimated Profit, invoice table, layaway table, sales by locations, sales by products, sales by users, Who is at Work?	dashboard.md
Products, Product Settings, Inventory Management, product quantities, categories, price, SKU/barcode, tracked inventory, product row actions, product import/export, add product, direct price edit, product matrix, variants, custom options, inventory report/export, bulk remove/add/category/quantity/labels	Inventory	Blue menu > Inventory	Product settings and inventory control are combined here. Page-action dropdown: Print, Import/Export, Add Product. Grid controls: Location, All Locations, Simple, Detailed, Add a Filter, Image, Name, Category, Price or Price (Default Price List), Quantity, Action. Open a product by clicking Name or Action > Edit. Product form tabs: Product Details, Pricing, Inventory. Product matrix controls can include Does this product come in different variants (example: color, size)?, Option 1, Option 2, Custom, Values, Remove Option, and Generate Variants. With a specific location selected, blue price amounts can be clicked and edited directly. Batch actions can include Update Quantities, Assign Category, Add to this location, Remove from this location, and Print Labels.	inventory_products.md, inventory_import_export.md, inventory_report.md
Product labels, price tags, barcode label warnings, label quantity	Print Labels	Blue menu > Print Labels	Select Paper Size, label sizes, Print Product Price, Print Product Desc., Print Labels, Clear, Auto Fill, Quantity to Print	print_labels.md
Inventory audit trail, who changed product quantity/cost, loss or adjustment comments	Change Log	Blue menu > Change Log	Product, Date, Location, Performed by, Comments, Cost, Quantity, Log Type	inventory_change_log.md
Requesting items, sending items, receiving counted items, receive-from-air, purchase orders, automatic purchase orders, receiving purchase orders, transfer status, transfer/P.O. PDFs	Transfers	Blue menu > Transfers	Page-action dropdown: Request Items, Send Items, Receive Items, New P.O.. List columns: Transfer #, From, To, Notes, Status, Action. Row actions can include Send, Receive, Reviewed, Not Reviewed, Download PDF, and Delete. Receive/edit screens can show Download copy of PO or Download copy of Transfer. Purchase orders use From Vendor, To, Missing Quantities, Auto Fill, Estimated Cost, and Total Estimated Cost. CSV export was not found/confirmed for opened transfers or P.O.s; CSV belongs to product Import/Export and Inventory Report workflows.	transfers_purchase_orders.md
Coupon list, coupon codes, automatic coupons, prompt-before-applying coupons, loyalty-only coupons, coupon discount rules	Coupons	Blue menu > Coupons	Page-action dropdown: Add Coupon. Form sections: Coupon Details, Coupon Activation, Coupon Value, Apply Automatically?, Prompt user before applying?, Only available to Loyalty program members?	coupons_price_lists.md
Location-specific pricing, assigned price lists, negotiable price settings, bulk percentage/dollar price updates, price-list settings	Price Lists	Blue menu > Price Lists	Page-action dropdown: Add Price List. List columns: Price List, Assigned Locations, Active, Created Date, Action. Bulk pricing modal controls include Update pricing information?, Suggested Price, Minimum Price, adding, removing, %, $, and Price Settings Information.	coupons_price_lists.md
Physical counts, daily counts, expected vs counted quantity, reviewed count status	Inventory Counts	Blue menu > Inventory Counts	Page-action dropdown: Add Count. List columns: Count #, Location, Submitted By, Notes, Last Modified By, Status, Action	inventory_counts.md
Employees, user details, system access, user contact fields	Users	Blue menu > Users	Page-action dropdown: Add New User. List columns: Id, Photo, First Name, Last Name, Position, Email, Mobile, Notes, Action	users_invoices.md, users_access.md
Customer lookup, phone/email, invoice totals, loyalty program, customer required fields	Customers	Blue menu > Customers	Page-action dropdown: Add Customer, Settings. List columns: ID, First, Last, Loyalty Program, Phone, Email, # of Invoices, Invoice Totals, Action	customers_loyalty.md
Loyalty setup, points, earning/using points, benefits, loyalty card number	Loyalty Programs	Blue menu > Loyalty Programs	Page-action dropdown: New Loyalty Program. List columns: Name, Earning Points, Using Points, Number of Benefits, Number of Members, Minimum amount to join	customers_loyalty.md
Invoice products, payments, customer, users, refunds, coupons, notes, layaway code	Invoice	Open from Dashboard or Customers	invoice #, Summary, Layaway code:, Customer, Payments, Users, Refunds, Coupons, Notes, Reviewed?, Comments	invoices.md, users_invoices.md
Kits and Bundles	Nova Classic only	Use Classic > Products > Kits and Bundles	New Nova live menu did not include a Kits and Bundles screen. Do not send New Nova customers to a New Nova kits screen.	Classic management_screen/products.md
If the Customer Asks "Where Is This?"

Answer in this pattern:

Name the mode: New Nova / NextGen.
Give the clicked path: Select Region > blue menu > screen.
Name the control exactly as it appears.
Tell what it is used for.
Add the how-to steps only if the customer is trying to complete a task.

Example:

A: In New Nova, you can find Quantity to Print under Print Labels. Select the region, click the blue menu button, then click Print Labels. The Quantity to Print column is on the product list. Enter the number of labels for each product, review the paper size, then click Print Labels.

Mode-Specific Routing Rules
Product Import/Export is in New Nova under Inventory > page-action dropdown > Import/Export.
Product Settings and Inventory Management route to the same combined Inventory screen in New Nova / NextGen.
If the web Region dropdown is blank, click the blue menu and open a screen such as Inventory first; this can populate the region list after the app context loads.
Product prices can be edited directly from Inventory when a specific Location is selected by clicking the blue price in Price or Price (Default Price List).
Product matrix / variants are in Inventory > product Name or Action > Edit > Product Details. Turn Does this product come in different variants... to YES, add options and values, click Generate Variants, then save.
New Nova coupon options include Apply Automatically?, Prompt user before applying?, and Only available to Loyalty program members?. These should be documented from the New Nova coupon form, not from Classic NovaFAQ wording.
Category setup coupons cannot use percentage discounts. This applies to Nova Classic, New Nova / NextGen, and Nova Wave-style coupon answers.
Kits and Bundles is a Nova Classic Products feature. It is not in the live New Nova blue menu.
For the current NextGen inventory report/export answer, route customers to New Nova. The source-backed New Nova report screen is Inventory Report and includes Export To Excel.
Classic Automatic Purchase Orders questions route to New Nova Transfers > New P.O.. The process still depends on product capacities and vendor links, but the layout is different.
Evidence Notes

This index is based on live clicked menu snapshots and the downloaded NextGen UI route/template labels. If a customer reports a missing button, check user access, selected region/location, and whether they are in Nova Classic or New Nova.
