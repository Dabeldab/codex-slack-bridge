# Products Settings AI Knowledge V 8

Source: Zoom Knowledge Library browser export
KB ID: n669kbqjs5h1h01ev55em8ki
Article ID: cmnqomqm802xco6075plfycm3
Product lane: Nova Wave
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/n669kbqjs5h1h01ev55em8ki/articles/cmnqomqm802xco6075plfycm3
Updated: 06/02/2026, 07:09 PM

Products Settings - AI Knowledge V8
Document Metadata
Title: Products Settings - AI Knowledge
Version: 8.0
Audience: AI chatbot / automated support
Environment: Back Office for setup, Storefront where stated
Primary Scope: Product
Covered Areas:
Product listing page
Add New Product / Create Product
Edit Product
Product Information
Categories
Single Product Details
Inventory Options
Product Commission Policy
Product Variations
1. Component Description
Title

Products Settings

Target Audience
Owner
Partial Owner
Product Manager
AI chatbot / automated support
Environment
Back Office for configuration
Storefront where product visibility, ordering, scan behavior, and sellability are relevant
Scope
Product / Category / Vendor = Account scope
Inventory assignment = Location scope
Access
Owner
Partial Owner
Product Manager

Region access rule:

users only see and operate within regions they can access
within accessible regions, only Owner, Partial Owner, Product Manager can create or edit products in Products > Settings
Exact Navigation Path

Back Office > Products > Settings

2. The Why

Products define sellable items or services and their pricing, tax, inventory, display behavior, identifiers, commission behavior, and variation setup.

Nova keeps products global at the account level so the business can maintain one product catalog across multiple locations, while each location controls what it actually sells through location-specific inventory assignment.

This area is used for:

product creation
product editing
product organization
location sellability
scan and identifier retrieval
pricing control
tax setup
commission setup
variation setup
3. The How
Primary Navigation Path

Back Office > Products > Settings

From there:

click Add New Product to create a new product
or click Edit on an existing product row to update a product
use:
Product Information
Categories
Single Product Details
Inventory Options
Variable Product Details to finish setup
4. Quick Intent Index
Common tasks and exact paths
Add a new product

Back Office > Products > Settings > Add New Product

Edit a product

Back Office > Products > Settings > Edit

Deactivate a product / remove it from all locations

Back Office > Products > Settings > Edit > Product Information > Active Product

Remove products from a specific region or location inventory

Back Office > Inventory > Settings > select Region and Location > use Remove Product > click REMOVE in the confirmation dialog. Repeat this per individual location in the region.

Change product category

Back Office > Products > Settings > Edit > Categories > Edit Categories

Add a product to a store location

Back Office > Products > Settings > Edit > Inventory Options

Add product commission

Back Office > Products > Settings > Add New Product or Edit > Product Information > Commission Policy

Add product variations

Back Office > Products > Settings > Edit > Variable Product Details

Change product pricing

Back Office > Products > Settings > Edit > Single Product Details

Change product rank

Back Office > Products > Settings > Add New Product or Edit > Product Information > Rank

Update SKU or barcodes

Back Office > Products > Settings > Add New Product or Edit > Single Product Details

5. Create and Edit Product
5.1 Component Description
Title: Add New Product / Edit Product
Target Audience: Owner, Partial Owner, Product Manager, AI chatbot
Environment: Back Office
Scope Level: Product (account-global) with location inventory assignment where relevant
Access: Owner, Partial Owner, Product Manager
5.2 The Why

This workflow creates and maintains products that can later be made sellable at one or more store locations.

5.3 The How
Add a new product
Go to Back Office > Products > Settings
Click Add New Product
On Settings / Create Product, complete the minimum required fields:
Product Name
at least one Category
Product Suggested Price
Save using:
SUBMIT
SUBMIT & CLONE
SUBMIT & NEW
Recommended complete product setup

After the minimum required fields are entered, Nova recommends filling in as much product information as possible.

Recommended fields to complete when available:

Vendor
Description
SKU
Barcode 1
Barcode 2
Product Cost Price
Is Negotiable
Product Minimum Price
tax settings
Size
Color

Why Nova recommends this:

Vendor helps with reporting and purchase-order workflows
Description makes product lists easier to review
SKU, Barcode 1, and Barcode 2 improve search, scan, retrieval, and reporting
a more complete product record is easier to manage later

Important Note: Required fields save the product. Recommended fields improve reporting, retrieval, and organization.

Important sellability rule

Creating a product does not automatically make it sellable at a store.

If the product should appear on the Storefront or sales screen:

open the product
go to Inventory Options
choose Region
choose Select Location
click ADD LOCATIONS
enter Qty, Max, and Min as needed
click UPDATE

Important Note: Saving the product does not make it sellable. Add it to the correct location inventory.

Edit an existing product
Go to Back Office > Products > Settings
Use Search or Scan if needed
Find the product row
Click Edit
Update the relevant fields
Save the product
5.4 Intent Map
What is this workflow?

This is the Back Office workflow used to create or edit products.

Where is it?

Back Office > Products > Settings

Who can access it?

Owner, Partial Owner, Product Manager

Why can I not see it?

Check:

Back Office vs Storefront
region access
account/location context
allowed role
What is required to save a product?
Product Name
at least one Category
Product Suggested Price
What does Nova recommend?
fill out as much product information as possible
add Vendor when known
add Description
add SKU, Barcode 1, and Barcode 2 when available
if the product should be sellable right away, add it to the correct location inventory after creating it
5.5 Option Details
Product Name
Exact UI Label: Product Name
Scope Level: Account
Default State: blank
Required: Yes
Maximum length: 35
What it does:
sets the product name
Important rule:
save is blocked if empty

Where is this setting? Back Office > Products > Settings > Add New Product / Edit > Product Information > Product Name

How do I change it? Enter or edit Product Name and save.

Vendor
Exact UI Label: Vendor
Scope Level: Account
Default State: no default
Required: No
What it does:
links the product to a vendor
Important recommendation:
add a vendor when known because it helps with product organization, reporting, and purchase-order workflows

Where is this setting? Back Office > Products > Settings > Add New Product / Edit > Product Information > Vendor

How do I change it? Select a Vendor and save.

Add New Vendor
Exact UI Label: Add New Vendor
Scope Level: Account
Default State: no default
What it does:
creates a new vendor from the product form

Where is this setting? Back Office > Products > Settings > Add New Product / Edit > Product Information > Add New Vendor

How do I change it? Click Add New Vendor, create the vendor, then save the product.

Description
Exact UI Label: Description
Scope Level: Account
Default State: blank
Required: No
What it does:
stores a short product description
Recommendation:
keep it short
Additional note:
may print on receipts

Where is this setting? Back Office > Products > Settings > Add New Product / Edit > Product Information > Description

How do I change it? Enter Description and save.

Upload Product Image
Exact UI Label: Upload Product Image
Scope Level: Account
Default State: no image
Required: No
Supported formats:
PNG
BMP
JPG
What it does:
stores a product image
Additional behavior:
system resizes the image

Where is this setting? Back Office > Products > Settings > Add New Product / Edit > Product Information > Upload Product Image

How do I change it? Upload the image and save.

Active Product
Exact UI Label: Active Product
Scope Level: Account
Default State: On
What it does:
controls whether the product is active or inactive for sale
On:
active product
Off:
inactive or dormant product
unavailable for sale until reactivated
removes the product from all locations / sales screens until the product is reactivated
Important note:
Active Product is account-level and should be used only when the product should be inactive everywhere
do not use Active Product for a single region or selected locations
for a specific region, remove the product from each individual location in that region through Inventory Management

Where is this setting? Back Office > Products > Settings > Add New Product / Edit > Product Information > Active Product

How do I change it? Toggle Active Product and save.

Categories
Exact UI Label: Categories
Scope Level: Account
Default State: none selected on blank create form
Required: Yes
What it does:
assigns one or more categories to the product
Important rules:
at least one category is required to save
categories are account-global
if no category is selected, save is blocked and an error is shown

Where is this setting? Back Office > Products > Settings > Add New Product / Edit > Categories

How do I change it? Use Edit Categories, select the needed category or categories, and save.

5.6 Bot-Logic
IF the user asks how to add a product THEN answer with:
exact path
minimum required fields
recommended complete setup
sellability note about location inventory
IF the user asks whether that is all they need THEN explain the minimum required fields first, then explain the recommended complete setup
IF the user asks why their product is not visible THEN prioritize:
Active Product
location inventory assignment
location context
5.7 Troubleshooting
Cannot save the product:
check Product Name
check category selection
check Product Suggested Price
Product created but not sellable:
check Inventory Options assignment
Product visible in Back Office but not in Storefront:
check Active Product
check location inventory assignment
check correct location context
5.8 FAQs
How do I add a new product?

Go to Back Office > Products > Settings and click Add New Product. To save a product, complete Product Name, at least one Category, and Product Suggested Price. Nova also recommends filling out as much product information as possible, including Vendor, Description, SKU, Barcode 1, and Barcode 2, because that helps with reporting, retrieval, organization, and purchase-order workflows. If the product should be sellable in a store, also add it to the correct location inventory after creating it.

What is the minimum required to create a product?

The minimum required fields are Product Name, at least one Category, and Product Suggested Price.

What do you recommend filling out when creating a product?

Nova recommends completing as much product information as possible. Add Vendor when known, add Description, and enter SKU, Barcode 1, and Barcode 2 when available. This improves retrieval, reporting, organization, and purchase-order workflows.

Why should I add a vendor to the product?

Adding a vendor helps with product organization, reporting, and purchase-order workflows.

Do I need to add the product to inventory after creating it?

Yes, if you want it to appear on the Storefront or sales screen for a location. Creating the product alone does not automatically make it sellable at a store.

Is that all I need to fill out when creating a product?

No. Those are only the minimum required fields to save the product. Nova recommends filling out as much product information as possible, especially Vendor, Description, SKU, Barcode 1, and Barcode 2, because that helps with reporting, retrieval, organization, and purchase-order workflows.

What else should I fill out when I create a product?

After the minimum required fields, Nova recommends completing the optional product details when available, especially Vendor, Description, SKU, Barcode 1, and Barcode 2. That makes the product easier to find later and more useful in reporting and organization.

6. Deactivate Product / Remove From All Locations
6.1 Component Description
Title: Deactivate Product / Remove From All Locations
Target Audience: Owner, Partial Owner, Product Manager, AI chatbot
Environment: Back Office with Storefront visibility effect
Scope Level: Product at account level
Access: inherited from Products Settings access
6.2 The Why

Nova does not delete products through this workflow. To remove a product from all locations / sales screens, make it inactive.

This is useful when the business wants to stop selling a product everywhere now but may want to restore it later.

6.3 The How

Navigation path: Back Office > Products > Settings > Edit > Product Information > Active Product

Steps:

Go to Back Office > Products > Settings
Find the product
Click Edit
In Product Information, turn Active Product Off
Save the product
6.4 Important behavior
Nova does not delete the product through Products Settings
making the product inactive is account-level
making the product inactive removes it from all locations / sales screens until it is reactivated
this is useful if the business may want to restore the product later
do not use Active Product when the request is to remove the product only from one region or selected locations
for a specific region, remove the product from the individual locations in that region through Inventory Management, repeating the removal per location

Important Note: To remove a product from every location, turn Active Product Off. For a specific region or selected locations, remove the product from each individual location inventory instead.

6.5 Bot-Logic
IF the user asks how to delete a product or remove it from all locations THEN explain that Nova does not delete the product in Products Settings and the correct action is to make the product inactive by turning Active Product Off
IF the user asks how to remove a product from the screen everywhere THEN route to Active Product and explain that turning it Off removes the product from all locations / sales screens
IF the user asks how to remove a product from a specific region, most regions, one location, or selected locations THEN do not route to Active Product and do not describe a direct region-level removal. Explain that Region only filters/selects locations, and the product must be removed from each individual location inventory in that region.
IF the user asks how to remove a product THEN first clarify whether they mean all locations or a specific region/location. If all locations, use Active Product. If a specific region/location, use the Inventory Management removal workflow.
6.6 FAQs
How do I delete a product?

Nova does not delete a product through Products Settings. To remove a product from every location / sales screen, go to Back Office > Products > Settings, open the product, and turn Active Product Off, then save. This is account-level and is useful if you may want to restore the product later.

How do I remove a product?

If you want to remove the product from every location, open the product in Back Office > Products > Settings and turn Active Product Off, then save. If you only want to remove it from a specific region, selected regions, or selected locations, remove it from each individual location inventory instead.

How do I take a product off the screen?

Open the product in Back Office > Products > Settings, find Active Product, turn it Off, and save. That makes the product inactive account-wide, so it no longer appears for sale at any location until it is reactivated.

How do I remove a product from a specific region?

There is not a direct region-level removal step. Select the region to identify the locations in that region, then remove the product from the inventory for each individual location. Repeat the inventory-removal workflow per location.

7. Rank and Ordering
7.1 Component Description
Title: Rank
Target Audience: Owner, Partial Owner, Product Manager, AI chatbot
Environment: Back Office with Storefront ordering effect
Scope Level: Account
Access: inherited from Products Settings access
7.2 The Why

Rank controls product placement order on the Storefront or sales screen.

7.3 The How

Navigation path: Back Office > Products > Settings > Add New Product or Edit > Product Information > Rank

7.4 Option Details
Rank
Exact UI Label: Rank
Scope Level: Account
Default State: None
Required: No
Documented order:
Blue
Yellow
Red
Green
Gray
White
Orange
What it does:
affects where the product appears in Storefront or on the sales screen
Important behavior:
if no rank is selected, ordering falls back to None then alphabetical ordering
ranked products are shown in the documented rank-color order
Orange is last among ranked values

Important Note: Rank changes Storefront or sales-screen order. No rank means alphabetical order. Because unranked products sort alphabetically, leading numbers in product names such as 01, 02, 03 can be used to influence the Storefront or sales-screen order when no Rank is selected. Those numbers are part of the product name, so use them only if that display is acceptable.

Where is this setting? Back Office > Products > Settings > Add New Product or Edit > Product Information > Rank

How do I change it? Select the desired rank and save.

7.5 FAQs
What is ranking in products?

In Nova, Ranking (Rank) is an optional ordering setting that controls where the product appears on the Storefront or sales screen. If you do not set a rank, products display alphabetically by default. If you do set a rank, products are ordered by rank in this sequence: Blue, Yellow, Red, Green, Gray, White, Orange.

Can numbers be used to sort products on the Storefront?

Yes. If no Rank is selected, products sort alphabetically by product name, so leading numbers such as 01, 02, 03 can be used to influence the Storefront or sales-screen order. The numbers are part of the product name, so use this only if that display is acceptable.

8. Identifiers
8.1 Component Description
Title: Product Identifiers
Target Audience: Owner, Partial Owner, Product Manager, AI chatbot
Environment: Back Office with Storefront and reporting implications
Scope Level: Account
Access: inherited from Products Settings access
8.2 The Why

Identifiers help the business search, scan, retrieve, report on, and organize products.

8.3 The How

Navigation path: Back Office > Products > Settings > Add New Product or Edit > Single Product Details

8.4 Option Details
SKU
Exact UI Label: SKU
Scope Level: Account
Default State: blank
Required: No
Validation:
letters and numbers allowed
maximum length 35
uniqueness not enforced
What it does:
internal identifier
Additional behavior:
not visible on Storefront
does not print on the receipt
can be used to search or retrieve the product in management screens
can appear in some reports

Where is this setting? Back Office > Products > Settings > Add New Product or Edit > Single Product Details > SKU

How do I change it? Enter SKU and save.

Barcode 1
Exact UI Label: Barcode 1
Scope Level: Account
Default State: blank
Required: No
Validation:
letters and numbers allowed
maximum length 35
uniqueness not enforced
What it does:
primary barcode-style identifier
Additional behavior:
visible on Storefront
prints on the receipt
can be used to search, scan, or retrieve the product in management screens and Storefront workflows
can appear in some reports

Where is this setting? Back Office > Products > Settings > Add New Product or Edit > Single Product Details > Barcode 1

How do I change it? Enter Barcode 1 and save.

Barcode 2
Exact UI Label: Barcode 2
Scope Level: Account
Default State: blank
Required: No
Validation:
letters and numbers allowed
maximum length 35
uniqueness not enforced
What it does:
secondary barcode-style identifier
Additional behavior:
not visible on Storefront
does not print on the receipt
still retrievable from Storefront or management screens when scanned
can appear in some reports

Where is this setting? Back Office > Products > Settings > Add New Product or Edit > Single Product Details > Barcode 2

How do I change it? Enter Barcode 2 and save.

Identifier recommendation
Enter SKU, Barcode 1, and Barcode 2 when available because these fields improve retrieval in Products Settings, inventory workflows, scan workflows, and some reports.
Filling out identifiers also makes long product lists easier to manage later.
Identifier caution
barcode uniqueness is not enforced
duplicate barcodes are possible
users should treat barcode uniqueness as a best practice even though Nova does not require it
duplicate active barcodes can cause the wrong product to be retrieved when users search or scan

Important Note: SKU and barcodes improve retrieval. Duplicate active barcodes can return the wrong product.

8.5 FAQs
What is SKU and Barcode 1 and Barcode 2?

SKU is an internal identifier that does not print on the receipt and is not visible on Storefront. Barcode 1 is visible on Storefront and prints on the receipt. Barcode 2 does not print on the receipt and is not visible on Storefront, but it can still retrieve the product when scanned.

Can I search products by SKU or barcode in the backend?

Yes. SKU, Barcode 1, and Barcode 2 can all be used to search or retrieve products in management areas such as Products > Settings and inventory-related workflows, and some reports can also surface these fields.

Do barcodes have to be unique?

No. Nova does not enforce barcode uniqueness. Users should still treat unique barcodes as a best practice.

9. Pricing and Controls
9.1 Component Description
Title: Pricing and Controls
Target Audience: Owner, Partial Owner, Product Manager, AI chatbot
Environment: Back Office with Storefront pricing effect
Scope Level: Account
Access: inherited from Products Settings access
9.2 The Why

Pricing and control fields define how the product is sold and whether the selling price can change at checkout.

9.3 The How

Navigation path: Back Office > Products > Settings > Add New Product or Edit > Single Product Details

9.4 Option Details
Product Cost Price
Exact UI Label: Product Cost Price
Scope Level: Account
Default State: documented default 0
Required: No
Validation:
2 decimals
allowed value >= 0
What it does:
stores product cost
Product Suggested Price
Exact UI Label: Product Suggested Price
Scope Level: Account
Default State: blank
Required: Yes
Validation:
2 decimals
allowed value >= 0
Error if empty:
default pricing suggested must not be empty
What it does:
stores the normal selling price
Is Negotiable
Exact UI Label: Is Negotiable
Scope Level: Account
Default State: On
What it does:
controls whether the product can be discounted
On:
product may be discounted
Off:
fixed-price item
Product Minimum Price
Exact UI Label: Product Minimum Price
Scope Level: Account
Default State: blank on create
Required: No
Validation:
2 decimals
allowed value >= 0
must be <= Product Suggested Price
Error if violated:
minimum price should be less than or equal to the suggested price
What it does:
discount floor / employee discount leeway
Block sale above suggested price
Exact UI Label: Block sale above suggested price
Scope Level: Account
Default State: Off
What it does:
prevents sale above Product Suggested Price
Block sale below minimum price
Exact UI Label: Block sale below minimum price
Scope Level: Account
Default State: Off
What it does:
prevents sale below Product Minimum Price
Override authority:
Owner
Partial Owner
Regional Manager
Pricing recommendations
If a product should be fixed-price, set Is Negotiable = Off
If Is Negotiable = On and Product Minimum Price = 0, a user may be able to sell the item for $0
If Product Suggested Price = Product Minimum Price, the configuration is valid, but the documented fixed-price control is still Is Negotiable = Off
If products are always sold at one price, recommended setup is:
set Product Suggested Price to the normal selling price
set Is Negotiable = Off
leave Product Minimum Price unused unless a separate floor is needed

Important Note: For one fixed price, use Is Negotiable = Off. Zero minimum with negotiable on can allow $0 sales.

9.5 FAQs
Which price setup should I use if my products are always one price?

Recommended setup is to set Product Suggested Price to the normal selling price and set Is Negotiable to Off. Product Minimum Price is mainly relevant when negotiation is allowed.

What happens if Product Suggested Price equals Product Minimum Price?

That setup is valid because minimum price can be less than or equal to suggested price. It does not by itself define the product as fixed price. The documented fixed-price control is Is Negotiable = Off.

10. Inventory Options
10.1 Component Description
Title: Inventory Options
Target Audience: Owner, Partial Owner, Product Manager, AI chatbot
Environment: Back Office with Storefront sellability effect
Scope Level: Location assignment inside product workflow
Access: inherited from Products Settings access
10.2 The Why

Inventory Options determine whether and where a product is sellable, and whether quantity tracking is enforced.

10.3 The How

Navigation path: Back Office > Products > Settings > Add New Product or Edit > Inventory Options

10.4 Option Details
Is Trackable:
Exact UI Label: Is Trackable:
Scope Level: Location behavior controlled through inventory assignment
Default State: On
What it does:
controls inventory quantity tracking
On:
quantity tracking is enforced
Off:
product can still be sold and assigned to inventory, but quantity tracking is not enforced
Recommendation:
Off is recommended for services
Region
Exact UI Label: Region
Scope Level: Region
Default State: no default documented
What it does:
determines which region's locations are available for inventory assignment
Select Location
Exact UI Label: Select Location
Scope Level: Location
Default State: no default documented
What it does:
selects the location to assign
ADD LOCATIONS
Exact UI Label: ADD LOCATIONS
Scope Level: Location
Default State: no default
What it does:
adds the selected location or locations into the inventory assignment table
Qty / Max / Min
Exact UI Labels:
Qty
Max
Min
Scope Level: Location
Default State:
Qty blank
Max blank
Min blank
What they do:
Qty = initial quantity
Max = maximum quantity
Min = minimum quantity
Additional rule:
Qty accepts 0
UPDATE
Exact UI Label: UPDATE
Scope Level: Location
Default State: no default
What it does:
applies the entered inventory values
Important sellability rule
creating a product does not automatically make it sellable at a location
if the product should appear on the Storefront or sales screen, add it to the correct location inventory
Region is used to choose or filter the locations available for inventory assignment; Region is not a direct bulk-remove control

Important Note: Product created is not the same as product sellable. Add location inventory.

Remove products from a specific region or location inventory

Use this workflow when the customer wants a product removed only from a specific region, most regions, one location, selected locations, or many products in inventory. This is a location-level inventory action, not a direct region-level product action.

Navigation path: Back Office > Inventory > Settings

Steps:

Go to Back Office > Inventory > Settings.
Select the target Region.
Select the first Location in that region.
Use View Inventory By Item or View Inventory By Category.
Find the product or products to remove.
Use the Remove Product column/action for each product that should be removed from that location. For bulk removal, remove the target products for that same location before moving to the next location.
Click Remove Product for each target product. In the confirmation dialog that asks Do you want to remove this product from inventory?, click REMOVE. Once you click REMOVE, the product is removed from that location.
Repeat the same steps for each individual location in the region.

Important Note: For region-specific removal, the user must repeat the bulk inventory-removal workflow per location. Do not tell the customer to remove the product directly from the region, and do not use Active Product unless the product should be removed from all locations.

Customer-facing answer pattern for removing products from most regions

When the customer asks how to remove products from most regions, remove products from a specific region, take products out of a region, or bulk remove products from inventory by region, answer with the steps below. Do not give Nova Classic steps. Do not ask a clarification question before giving these steps.

Recommended answer:

Go to Back Office > Inventory > Settings.
Select the target Region.
Select the first Location in that region.
Choose View Inventory By Item or View Inventory By Category.
Find the product or products that need to be removed.
In the inventory table, use the Remove Product column/action for each product. For bulk removal, remove all products that should be removed from that one location before moving to the next location.
Click Remove Product for each target product. In the confirmation dialog that asks Do you want to remove this product from inventory?, click REMOVE. Once you click REMOVE, the product is removed from that location.
Select the next location in that same region and repeat the same steps.
Continue until the product or products have been removed from each individual location in the region.

Answer rules:

Say that there is no direct region-level remove-product action.
Say that Region is used to choose or filter the locations; the removal itself is done location by location.
For many products, describe this as bulk inventory removal per location, repeated for each location.
Only mention Active Product if the customer wants the product removed from all locations / sales screens. Making the product inactive is account-level and removes it everywhere.
10.5 FAQs
How do I add a product to inventory?

Open the product, go to Inventory Options, choose Region, choose Select Location, click ADD LOCATIONS, enter Qty, Max, and Min as needed, then click UPDATE.

How do I remove a product from a specific region?

There is not a direct region-level removal action. Go to Back Office > Inventory > Settings, select the Region, select one Location in that region, find the product in inventory, use the Remove Product column/action, and submit the change. Repeat this for each individual location in that region.

How do I remove many products from a region?

Use the bulk inventory-removal workflow one location at a time. Go to Back Office > Inventory > Settings, select the Region and one Location, mark all target products using the Remove Product column/action, submit the change, then repeat for the next location in that region.

Should I make the product inactive instead?

Only make the product inactive when it should be removed from all locations / sales screens. If the request is for one region, most regions, or selected locations, remove the product from each individual location inventory instead.

Why is my product not showing on the sales screen?

The most common causes are that Active Product is Off, the product was not added to the correct location inventory, or you are checking the wrong location context.

11. Product Commission Policy
11.1 Component Description
Title: Product Commission Policy
Target Audience: Owner, Partial Owner, Product Manager, AI chatbot
Environment: Back Office
Scope Level: Account
Access: inherited from Products Settings access
11.2 The Why

Product commission controls how commission is paid when that specific product is sold.

This is a sensitive payroll-affecting setup area because it can increase, reduce, or override expected commission behavior and materially affect payouts, margins, and employee expectations.

11.3 The How

Navigation path: Back Office > Products > Settings > Add New Product or Edit > Product Information > Commission Policy

Setup flow:

Go to Back Office > Products > Settings
Open the product you want to update, or click Add New Product
In Product Information, find Commission Policy
Choose one of:
None
Regular
Extra Commission
If Extra Commission is selected, enter the value in Extra Commission(%)
Save the product
11.4 Option Details
Commission Policy
Exact UI Label: Commission Policy
Scope Level: Account
Default State: Regular
What it does: controls product-level commission behavior for the product
Important rule: this is a sensitive payroll-affecting setting. When users ask about product commission, the answer must include both the setup path and a caution summary.

Where is this setting? Back Office > Products > Settings > Add New Product or Edit > Product Information > Commission Policy

How do I change it? Open the product, go to Product Information, choose the needed Commission Policy option, and save the product.

Documented options:

None
product pays 0 commission
overrides user commission
Regular
no special product rule
commission follows the user's normal commission settings, if any
Extra Commission
adds extra commission on top of user-level commission, if any
extra amount is based on net sold price
net sold price means pre-tax and after discounts
Extra Commission(%)
Exact UI Label: Extra Commission(%)
Scope Level: Account
Default State: Disabled unless Commission Policy = Extra Commission
What it does: stores the extra commission percentage applied at the product level
Important rule: Extra Commission can increase payouts. Negative values can reduce payouts.

Where is this setting? Back Office > Products > Settings > Add New Product or Edit > Product Information > Extra Commission(%)

How do I change it? Set Commission Policy to Extra Commission, enter the percentage value in Extra Commission(%), then save the product.

Validation and behavior:

integer only
allowed range: -100 to 100
validation message if invalid or blank:
Error happened saving product: { "message": "Commission amount is a value between -100% and 100% different than 0" }
Commission caution
Product commission is a sensitive payroll-affecting setting
It can override, increase, or reduce normal user commission
Incorrect commission settings can create unexpected overpayment, underpayment, employee disputes, or business margin loss
Example:
if a user normally earns 30% commission and the product is set to Extra Commission = 20%, that user may receive 50% total commission on that sale
Negative Extra Commission can reduce commission
If a user has no normal commission configured, negative product commission can still act like a penalty on that sale
Refunds reverse product commission for the user
11.5 Bot-Logic
IF the user asks about product commission or extra commission THEN answer with:
exact path or setup path
Commission Policy explanation
Extra Commission(%) rule if relevant
caution summary
IF the user says they want to add product commission THEN explain:
where Commission Policy is
the available options
how to enter Extra Commission(%)
that this is a sensitive payroll-affecting setting
IF the user asks what policy to choose THEN explain:
None = zero commission
Regular = follow user commission
Extra Commission = product-level extra amount
include the caution summary
IF the user asks about Extra Commission THEN explain:
it is based on net sold price
it stacks on top of user commission, if any
negative values reduce payouts
11.6 Troubleshooting
Commission seems wrong:
check Commission Policy
check whether Extra Commission(%) is positive or negative
check the user's commission setup
check whether the invoice was refunded
User wants to add commission but is unsure which option:
explain None, Regular, Extra Commission
include the caution summary before giving a recommendation
User expects a normal payout but payout is too high:
check whether Extra Commission was added on top of user commission
User expects no payout but payout still changed:
check whether a negative or positive product commission was configured
11.7 FAQs
What is product commission?

Product commission is the commission behavior assigned at the product level through Commission Policy. It can block commission, follow the user's normal commission settings, or add Extra Commission based on net sold price before tax and after discounts. Be careful with this setting because it can override, increase, or reduce payouts, and incorrect setup can create overpayment, underpayment, disputes, or margin loss.

How do I add product commission?

Go to Back Office > Products > Settings, open the product or click Add New Product, then in Product Information set Commission Policy. If you choose Extra Commission, enter the value in Extra Commission(%). Allowed values are integers from -100 to 100. Be careful with this setting because it can stack with user commission, reduce payouts if negative, and materially change payroll outcomes.

How do I add extra commission to a product?

Go to Back Office > Products > Settings, open the product, set Commission Policy to Extra Commission, enter the Extra Commission(%) value, then save the product. Extra Commission is calculated from the net sold price before tax and after discounts. Be careful because this can create overpayment, underpayment, disputes, or margin loss if configured incorrectly.

What is the difference between None, Regular, and Extra Commission?

None pays 0 commission and overrides user commission. Regular follows the user's normal commission settings. Extra Commission adds extra commission on top of user-level commission, if any. Be careful because this setting can increase or reduce payouts.

Should I be careful when setting product commission?

Yes. Product commission is a sensitive payroll-affecting setting. It can override, increase, or reduce payouts, and incorrect setup can create unexpected overpayment, underpayment, disputes, or margin loss.

I want to add product commission. How do I do it?

Go to Back Office > Products > Settings, open the product or click Add New Product, then in Product Information choose Commission Policy. If you use Extra Commission, enter the Extra Commission(%) value and save. Important: product commission is a sensitive payroll-affecting setting. It can stack with user commission, reduce payouts if negative, and create overpayment or underpayment if configured incorrectly.

I want to add extra commission. What should I be careful about?

Extra Commission adds a product-level amount on top of user commission, if any. It is calculated from the net sold price before tax and after discounts. Be careful because it can materially change payouts. If set incorrectly, it can create overpayment, underpayment, disputes, or margin loss.

I need this item to have extra commission. How do I set it?

Go to Back Office > Products > Settings, open the product, set Commission Policy to Extra Commission, enter the Extra Commission(%) value, and save. Important: Extra Commission increases payouts on that product. Negative values reduce payouts. Review the setting carefully before saving.

11.8 Intent Map
What is this feature?

Product Commission Policy controls how commission is paid when that specific product is sold.

Where is it?

Back Office > Products > Settings > Add New Product or Edit > Product Information > Commission Policy

How do I change it?

Open the product, go to Product Information, choose Commission Policy, optionally enter Extra Commission(%), then save.

Why do I not see it?

Check:

Back Office vs Storefront
Products > Settings access
role access
whether you are on the product record in Product Information
Who can access it?

Owner, Partial Owner, Product Manager

What are all the options?
None
Regular
Extra Commission
What does each option do?
None = zero commission and overrides user commission
Regular = follows user commission
Extra Commission = adds product-level extra amount on net sold price
What does the system recommend?

Treat this setting carefully. Always review the payout impact before saving because this setting can increase, reduce, or override payouts.

12. Product Variations
12.1 Component Description
Title: Product Variations
Target Audience: Owner, Partial Owner, Product Manager, AI chatbot
Environment: Back Office with Storefront variant-display effect
Scope Level: Account with location inventory assignment per variant where relevant
Access: inherited from Products Settings access
12.2 The Why

Product variations support multiple configurations such as sizes, colors, and combinations.

12.3 The How
Manual clone method

Use this for a small number of variants.

create the base product
set the attribute values such as Size or Color
save the product
clone the product
change the attribute values on each clone
each cloned record remains a standalone product
Variable Product Details matrix method

Use this for larger sets of variants.

open the product
go to Variable Product Details
click Add New Option
select or define a family
add option values such as colors or sizes
click Create Options
configure the first generated variant
use Copy for all if desired
save the product
12.4 Option Details
Variation recommendation
for only a few versions, use the manual clone method
for many sizes, colors, or combinations, use Variable Product Details
Variable product structure
one father product plus N linked child variants
Storefront behavior
each variant appears as a separate product item
there is no option-selection UI on the sales screen
Common variation phrasing
users may ask for:
options
sizes
colors
versions
combinations
these should all route to product variation creation guidance when the user is asking how to create multiple versions of one product
Limits
maximum families: 2
maximum option values per family: 10
maximum variants: 100
Validation
blank family name:
family cannot be empty
blank option value:
option cannot be empty
duplicate option value:
option already exists
Family memory
the system remembers previously used option values for a family
Add all options adds all remembered values for a family
Remove all options clears selected setup values during setup only
Field ownership
Father-level shared fields:
Product Name
Vendor
Rank
Commission Policy
Description
Category
Product Image
Variant-level child fields:
SKU
Barcodes
Cost
Suggested
Minimum
Negotiable and block settings
Tax toggles and rate
Inventory per location
Commission policy is father-level only
Copy for all
copies all settings from the first variant to all variants
overwrites existing variant values
includes barcodes and inventory
Save requirements
if Is Negotiable = On, Product Suggested Price and Product Minimum Price are required per variant
if Is Negotiable = Off, only Product Suggested Price is required
Archive rule
removed option values archive or deactivate affected variants
Nova does not delete products
re-adding a previously removed option can reactivate archived variants
12.5 FAQs
How do I create product variations?

Either clone the base product and change Size or Color for each copy, or open the product, go to Variable Product Details, add option families and values, create options, configure the first variant, optionally use Copy for all, and save.

How do I create colors or sizes for one product?

Use Product Variations. For a few versions, use the manual clone method. For scalable setup, use Variable Product Details to create color or size option values.

What is the difference between the clone method and Variable Product Details?

The clone method is simpler for a small number of variants. Variable Product Details is the scalable matrix method for building many combinations more efficiently.

13. Final Bot-Logic Summary
IF the user asks how to add a product THEN answer with the exact path, minimum required fields, recommended complete setup, and the location-inventory sellability note
IF the user asks about product commission or extra commission THEN always include the caution summary
IF the user asks about rank THEN explain the practical Storefront or sales-screen ordering effect, not only the color list
IF the user asks whether numbers can sort products on the Storefront THEN explain that unranked products sort alphabetically, so leading numbers in product names can influence order
IF the user asks about SKU or barcodes THEN explain visibility, printing behavior, search or scan use, and the duplicate-barcode caution
IF the user asks about product variations THEN choose clone for a few or Variable Product Details for many, and explain the correct path and limits
IF the user asks how to delete, remove, or take a product off the screen THEN explain that Nova uses deactivation in Products Settings and route the user to Active Product
