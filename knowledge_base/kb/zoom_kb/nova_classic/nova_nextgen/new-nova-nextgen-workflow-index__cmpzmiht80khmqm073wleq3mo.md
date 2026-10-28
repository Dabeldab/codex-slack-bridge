# New Nova / NextGen > Workflow Index

Source: Zoom Knowledge Library browser export
KB ID: xgc1pmuooitf8r7897796fje
Article ID: cmpzmiht80khmqm073wleq3mo
Product lane: Nova Classic
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/xgc1pmuooitf8r7897796fje/articles/cmpzmiht80khmqm073wleq3mo
Updated: 06/04/2026, 11:03 AM

Extract table (Keep table structure)

Use this file to route New Nova / NextGen customer questions into the correct step-by-step article. New Nova is web-based and uses the blue top-right menu plus screen-specific page-action dropdowns.

Entry Workflow
Open the tenant URL.
Log in if Your Session Has Expired is shown.
Select a Region.
If the web Region dropdown is blank, click the blue menu button, open a screen such as Inventory, and let that screen populate the app context.
Click the blue menu button in the top-right.
Open the screen.
Use the page-action dropdown when the action is not visible in the list body.

If the user has not selected a region, menu behavior can look incomplete.

Workflow Map
Customer intent	Use this article	New Nova path	Key workflow notes
Open New Nova, handle session expired, select region, open menu	getting_started_navigation.md	tenant URL > login > Region > blue menu	Your Session Has Expired is normal on first access. If it happens during work, log back in. If the web Region list is blank, open a screen from the blue menu first to populate it.
Dashboard totals, sales, invoices, layaway code lookup	dashboard.md, users_invoices.md, invoices.md	Blue menu > Dashboard	Use Dashboard invoice/layaway tables when the customer needs a quick lookup.
Product settings or inventory management	inventory_products.md	Blue menu > Inventory	New Nova combines product settings and inventory control into one Inventory screen. Classic-style Product Settings and Inventory Management questions route here.
Open or edit an existing product	inventory_products.md	Inventory > click product Name or row Action > Edit	Product form has Product Details, Pricing, and Inventory tabs.
Add product	inventory_products.md	Blue menu > Inventory > page-action dropdown > Add Product	New Product has Product Details, Pricing, and Inventory tabs.
Import products	inventory_import_export.md, inventory_products.md	Inventory > page-action dropdown > Import/Export > Import new products	Product Import/Export is a New Nova capability. Validate template/columns before importing.
Export products	inventory_import_export.md, inventory_products.md	Inventory > page-action dropdown > Import/Export > Export products from Nova	Export options can include all company items, current location only, and quantities.
Inventory Report or Export To Excel	inventory_report.md, inventory_products.md	Inventory > inventory report/export flow	Current support answers should route inventory report/export to New Nova. Source route has Inventory Report and Export To Excel.
Inventory change history, who changed quantity, loss/audit comments	inventory_change_log.md	Blue menu > Change Log	Use Product, Date, Location, Performed by, Comments, Cost, Quantity, and Log Type to review what changed.
Print inventory/product report	inventory_products.md	Inventory > page-action dropdown > Print	This can open the browser print dialog. If print opens by mistake, cancel to return.
Filter products, simple/detailed view, quantity lookup	inventory_products.md	Blue menu > Inventory	Use Location, All Locations, Simple, Detailed, and Add a Filter.
Bulk update inventory quantity	inventory_products.md	Blue menu > Inventory > select products > bulk action	Confirm selected rows, location, and quantity behavior before applying.
Remove multiple products from a location	inventory_products.md	Inventory > specific Location > select products > Remove from this location	Do not use All Locations. Confirm the warning because products not active in another location may be deleted permanently.
Add multiple products to a location	inventory_products.md	Inventory > specific Location > select products > Add to this location	Adds selected products to the location at quantity 0, then use Update Quantities if stock exists.
Assign category to multiple products	inventory_products.md	Inventory > select products > Assign Category	Use only when every selected product needs the same category.
Print labels for multiple inventory products	inventory_products.md, print_labels.md	Inventory > specific Location > select products > Print Labels	Use selected rows and a specific location. Broad select-all states can block label printing.
Bulk update barcodes, Barcode1, Barcode2, SKU, or product details	inventory_products.md	Inventory > select products or edit product > batch action > Update Product Details / Update Identifiers	Use for shared values. For variants, barcode fields can use a base value with generated suffixes; SKU is shared.
Generate multiple barcodes for variants	inventory_products.md	Inventory > product Name or Action > Edit > Product Details > Generate Variants, then Inventory > Identifiers	Generate variants first, then use the variant identifier/barcode tools and review generated barcodes before printing labels.
Use product creation matrix for size/color/style/custom variants	inventory_products.md	Inventory > Add/Edit Product > Product Details > Does this product come in different variants... > Generate Variants	Choose existing options such as Size/Color/Style or Custom, enter values, click Generate Variants, then save.
Change quantities for all variants of one product	inventory_products.md	Inventory > product Name or Action > Edit > Inventory tab	After variants are generated, use Inventory to track inventory and update quantities for selected/all variants.
Edit product price directly from product list	inventory_products.md	Inventory > specific Location > click blue price in Price (Default Price List)	A location must be selected. The customer does not need to open Action > Edit for a quick price change.
Bulk edit product cost, minimum, suggested price, markup, negotiable, tax, sale limits	inventory_products.md, coupons_price_lists.md	Product edit > Pricing > selected rows > Update Pricing	New Nova uses Suggested / Suggested Price where customers may say markup. Only checked fields update.
Report damaged, lost, missing, tester, or other product loss	inventory_products.md	Blue menu > Inventory > product action/bulk action	Use comments/reason so the inventory change is traceable.
Print product labels	print_labels.md	Blue menu > Print Labels	The live label screen uses controls in the screen body, not a page-action dropdown.
Request items from another location	transfers_purchase_orders.md	Blue menu > Transfers > page-action dropdown > Request Items	Choose origin and destination before adding products.
Send a requested transfer	transfers_purchase_orders.md	Transfers > requested transfer row Action > Send	Review requested quantity, enter actual Send Quantity, and use Auto Fill only when sending the requested amount.
Send items to another location	transfers_purchase_orders.md	Transfers > page-action dropdown > Send Items	Confirm source, destination, quantities, and notes.
Send and receive immediately	transfers_purchase_orders.md	Transfers > Send Items > Send & Receive	Use only when the destination should receive the same quantities right away. Do not use when the destination still needs to count items.
Receive transfer	transfers_purchase_orders.md	Transfers > page-action dropdown > Receive Items	Enter received and damaged quantities. Use auto-fill only when exact quantities arrived.
Receive only after counting	transfers_purchase_orders.md	Transfers > sent transfer row Action > Receive	Count first, then enter Received and Losses before clicking Receive.
Receive from air	transfers_purchase_orders.md	Transfers > page-action dropdown > Receive Items	Adds received quantity to the selected location without a normal source transfer history.
New purchase order	transfers_purchase_orders.md	Transfers > page-action dropdown > New P.O.	Choose vendor and destination location first. This is the New Nova layout version of Classic automatic purchase orders. Capacities and vendor links still drive suggested quantities. If sending through Gmail, use a Gmail app password because the email send is part of generating the P.O.
Automatic purchase order from Classic	transfers_purchase_orders.md	Transfers > page-action dropdown > New P.O.	Classic Inventory > Automatic Purchase Orders questions route to New Nova Transfers > New P.O.. Check minimum/maximum capacities, preferred vendor/wholesaler link, and vendor contact/email information.
Purchase order email fails or Gmail blocks P.O. send	transfers_purchase_orders.md	Transfers > New P.O. send/email step	Gmail requires an app password for Nova when normal Gmail password sign-in is blocked. Customer can send the P.O. to themselves and forward it.
Receive purchase order	transfers_purchase_orders.md	Transfers > P.O. row Action > Receive	A P.O. creates pending incoming inventory, similar to a pending incoming transfer. Inventory increases only after the counted Received quantity is received.
Purchase order created but inventory did not increase	transfers_purchase_orders.md	Transfers > pending P.O. row Action > Receive	Explain that creating/sending the P.O. does not finish inventory. The store must receive the pending P.O. after counting the vendor shipment.
Transfer quantities, capacities, missing quantity, auto fill	transfers_purchase_orders.md	Transfers > request/send/receive/P.O. product grid	Missing quantity is based on destination maximum minus current quantity when capacity is set. Verify capacities before using Auto Fill.
Download transfer or P.O. PDF	transfers_purchase_orders.md	Transfers > row Action > Download PDF	Receive/edit screens can also show Download copy of PO or Download copy of Transfer. I did not find a CSV export option for opened transfers or P.O.s; CSV export belongs to product Import/Export and Inventory Report workflows.
Create or review inventory count	inventory_counts.md	Blue menu > Inventory Counts > page-action dropdown > Add Count	Confirm location, count mode, comments, and expected count before saving.
Create coupon	coupons_price_lists.md	Blue menu > Coupons > page-action dropdown > Add Coupon	New Nova coupons have Coupon Details, Coupon Activation, and Coupon Value.
BOGO or buy-one-get-one-style coupon	coupons_price_lists.md	Coupons > Add/Edit Coupon > Coupon Activation and Coupon Value	Use There are specific items in the cart plus Fixed Discount. The discount amount should match the value being made free.
Automatic coupon	coupons_price_lists.md	Coupons > Add/Edit Coupon > Apply Automatically?	Configure activation rules first. Add prompt if employee should confirm.
Prompt-before-applying coupon	coupons_price_lists.md	Coupons > Add/Edit Coupon > Prompt user before applying?	Use with automatic rules when the salesperson should decide.
Loyalty-only coupon	coupons_price_lists.md	Coupons > Add/Edit Coupon > Only available to Loyalty program members?	Customer on the sale must be enrolled for the coupon to apply.
Category coupon	coupons_price_lists.md	Coupons > Add/Edit Coupon > activation/category rule	Category setup coupons cannot use percentage discounts. Use a fixed amount/category-compatible setup.
Specific-item coupon not applying	coupons_price_lists.md	Coupons > Add/Edit Coupon > The following items will activate the coupon	Every activation product/category and required quantity must be in the cart. If only some are in the cart, the coupon will not apply.
Optional products in a promotion or bundle	Classic products.md	Nova Classic > Products > Kits and Bundles	New Nova coupon activation rows are strict requirements. Use Classic Kits and Bundles for optional bundle choices.
Price list or location pricing	coupons_price_lists.md	Blue menu > Price Lists > page-action dropdown > Add Price List	Assign locations and review price settings before saving.
Classic vs New Nova price-list differences	coupons_price_lists.md, Classic products.md	New Nova Price Lists or Classic Products > Price Lists	New Nova has bulk percentage/dollar price-list updates. Classic price lists live under Products and use Classic actions.
Bulk price-list update	coupons_price_lists.md	Price Lists > open price list > select products > bulk pricing	Pending batch updates can be overwritten. Review before applying.
Bulk increase or decrease price list prices by percentage	coupons_price_lists.md	Price Lists > open price list > selected products > Update Pricing > %	Use adding to increase and removing to decrease. Choose Suggested Price or Minimum Price.
Bulk increase or decrease price list prices by dollar amount	coupons_price_lists.md	Price Lists > open price list > selected products > Update Pricing > $	Use adding or removing and confirm the selected products.
Bulk update price-list settings without changing prices	coupons_price_lists.md	Price Lists > open price list > bulk pricing > Price Settings Information	Leave Update pricing information? off if prices should stay unchanged.
Add customer	customers_loyalty.md	Blue menu > Customers > page-action dropdown > Add Customer	Required customer fields are controlled by Customers > Settings.
Customer required fields	customers_loyalty.md	Customers > page-action dropdown > Settings	Required fields include customer info, shipping info, loyalty, and company settings.
Export customers	customers_loyalty.md	Customers > filter/select customers > Export Customers	Filter before exporting so the file contains the intended customers.
Customer dashboard, invoices, loyalty, layaways	customers_loyalty.md, users_invoices.md	Customers > row action/customer dashboard	Use customer dashboard for customer-specific invoice history and loyalty status.
Create loyalty program	customers_loyalty.md	Blue menu > Loyalty Programs > page-action dropdown > New Loyalty Program	Configure Summary, Loyalty Points, and Benefits.
Loyalty automatic enrollment	customers_loyalty.md	Loyalty Programs > Add/Edit Program > Automatic Enrollment	Review minimum amount to join before turning on.
Add user	users_invoices.md, users_access.md	Blue menu > Users > page-action dropdown > Add New User	Fill User Info and System Access.
User cannot see a menu item	users_access.md, users_invoices.md	Users > edit user > System Access	Confirm correct user, selected region, access, and relogin.
Invoice lookup, layaway code, notes	invoices.md, users_invoices.md, dashboard.md	Dashboard or Customers > invoice link	Do not send direct internal invoice URLs. Open invoices through the app.
Print, email, refund, or correct an invoice	invoices.md	Dashboard or Customers > invoice link	Open the invoice through New Nova, review payments/refunds/users/coupons, and avoid duplicate corrections until the saved state is confirmed.
Hard Rules
Kits and Bundles is Classic-only. Use Classic Products > Kits and Bundles.
New Nova combines product settings and inventory management into Inventory. If the customer asks for Product Settings or Inventory Management in New Nova, route them to Inventory.
Product Import/Export is New Nova Inventory > Import/Export.
New Nova product matrix/variants are inside Inventory > product > Product Details with Does this product come in different variants... and Generate Variants.
Inventory Report/export is answered from New Nova for current support.
Classic automatic purchase order questions route to Transfers > New P.O. in New Nova. Creating the P.O. creates pending incoming inventory; the P.O. must be received after the shipment is counted before destination inventory increases.
Category setup coupons cannot use percentage discounts in Nova Classic, New Nova / NextGen, or Nova Wave-style coupon answers.
Specific-product/category coupon activation requires every activation row and required quantity to be in the cart. Use Classic Kits and Bundles when optional item choices are needed.
NovaFAQ/NovaKB Classic articles can inspire workflow wording, but they are not proof of New Nova screen layout.
