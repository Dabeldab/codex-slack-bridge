# Nova Storefront KB

Source: Zoom Knowledge Library browser export
KB ID: tk2jz1wmpfl3ut2yyuzlevip
Article ID: cmp4pd8hb0by4rc07i4dozgi5
Product lane: Nova Wave
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/tk2jz1wmpfl3ut2yyuzlevip/articles/cmp4pd8hb0by4rc07i4dozgi5?language=en-US
Updated: 06/29/2026, 11:54 AM

Extract table (Keep table structure)
Nova-Sales Storefront — Knowledge Base Article

Version: 1.0.4.0 | Last Verified: May 2026
Use: Load into ZVA Knowledge Base tool. Each section is a discrete lookup topic.

TOPIC: What is Nova-Sales / Nova Storefront?

Nova-Sales (v1.0.4.0) is a point-of-sale (POS) application for retail environments. The checkout screen has two panels:

Left Panel — sale summary: customer, products, running totals, applied payments, and change due. The red ✕ next to any payment removes it.
Right Panel — the active workflow with three tabs: Customer → Payment → Sales Team. Tabs advance in strict linear order using the back arrow (‹) at the bottom-left. Clicking a tab header directly does nothing.
TOPIC: How to Install Nova Storefront

Nova Storefront is available for Windows through the Microsoft Store and on iPad through the Nova POS iPad app in the Apple App Store (https://apps.apple.com/us/app/nova-pos/id1347240054). For roaming checkout, iPad checkout and Windows Storefront are confirmed options; do not tell customers that Nova Wave has no iOS or iPad checkout option.

Open the Microsoft Store on your Windows computer.
Search for "nova pos store front" or "novapos".
Install the application.
On first launch, the Add Your Account screen appears — enter your Company Name and Access Key, then click Save.

Where to find your credentials: Your Company Name and Access Key are sent to the email address used when the Nova account was opened. Check that inbox for a welcome email from Nova. If you cannot locate them, contact Nova support — credentials cannot be provided verbally or through unverified channels. Nova support can resend the credentials email to the address on file.

Adding multiple accounts: From the login screen, click "+ ADD NEW ACCOUNT" at the top. Saved accounts appear as labeled tiles. Remove an account with the ✕ button on its tile.

TOPIC: How to Log In / Log Out

Login fields:

Company Name (auto-filled from selected account, shown in red)
Region — select from dropdown
Location — select from dropdown
Password — employee PIN or location password
"Use only with [Location Name]" checkbox — locks app to that location (recommended for fixed terminals)
Fingerprint icon — biometric login if a fingerprint reader is connected

To log in: Select Region and Location, enter your password (or use fingerprint), click Login.

To log out: Click your user avatar (top-right corner) → your name and role appear → click Logout. Returns to the login screen; session is fully cleared.

Storefront vs Back Office: The button in the top-left of the login screen always shows the opposite mode. Click it to switch.

TOPIC: Storefront Toolbar Buttons

Located across the top of the checkout screen.

Button	What it does
Discount+	Opens Add Discount dialog — Percentage, Fixed Amount, or Tax Exempt
Coupon+	Opens Add Coupon dialog — search by name or code
More ▾	Expands to show: Hide ×, Layaways, Quotes
TOPIC: How to Apply a Discount

Click Discount+ from the toolbar. Choose one of three modes:

Percentage — enter a % (e.g., 10%) applied to the subtotal.
Fixed Amount — enter a flat dollar amount to subtract.
Tax Exempt — removes all applicable taxes. Requires an authorized user to log in and approve. A "Tax Exempted" badge appears in the left panel.

⚠️ Tax Exempt blocks Layaway and Quote creation. Remove Tax Exempt first before using those features.

TOPIC: How to Apply a Coupon

Click Coupon+ from the toolbar → use the search field to find a coupon by name or code → select it from the list to apply it to the current transaction.

TOPIC: How to Process a Regular Sale (Step-by-Step)
Add items to the cart (appear in the left panel).
Open the Customer tab → search for or add the customer → click Next.
On the Payment tab → select a payment method, enter amount → click Confirm Payment.
Click Next to advance to the Sales Team tab.
Add and select a sales associate → click Complete.
The Sale Completed screen appears — choose a receipt option → click Done.
TOPIC: How to Search for a Customer

On the Customer tab, type the customer's name, phone number, or ID in the search field. Results appear as you type. Click a result to select — the row turns red with an eye icon and a ✕ to deselect. Click Next to proceed.

You can also proceed as a walk-in by clicking Next without selecting a customer (except for Layaway — a customer is required).

TOPIC: How to Add a New Customer

On the Customer tab, click + Add New Customer (top-right). The Create Customer dialog has three tabs:

Customer Information:

Photo, Shop Name, First/Middle/Last Name, Email
Opt-out checkboxes (text campaigns, event notifications, email campaigns)
Mobile No., Gender, Date of Birth, Notes

Shipping Information:

Address 1, Address 2, City, State, Country, Zip Code

Custom Fields:

Store-specific fields configured by management (varies by location)

Click Next inside the dialog to move between tabs. X closes without saving.

TOPIC: How to Attach a File to a Customer

On the Customer tab, click the paperclip icon (📎) at the top-right. A Windows file picker opens. Attach any document, image, or file to the selected customer's record.

⚠️ A customer must be selected (row highlighted) before the paperclip is active.

TOPIC: Payment Methods

Five payment methods are available at the bottom of the Payment tab.

Cash

Default method. Use denomination buttons (1, 5, 10, 20, 50, 100) or Custom to enter any amount. Once the charged amount meets or exceeds the total, Total Due turns red at $0.00 and Change Due appears. Click Confirm Payment. Multiple separate cash entries are allowed and each appears as a separate line on the receipt.

Credit Card
Status indicator shows "Terminal Ready" when the card reader is connected.
Customer can Tap / Insert / Swipe.
Manual Entry allows keying card details if the reader is unavailable.
Check

Requires: Name (required), Check No. (required), Check Type (Personal or Traveler's). ⚠️ Check payment must be enabled in Location Settings first.

Gift Card

Search by number or customer. Card Balance and Expiry Date are read-only. Gift card expiration is managed in Location Settings.

External

Generic panel for any external payment processor. No fields required — records that an external payment was taken.

TOPIC: How to Confirm Payment

After entering a payment amount, click Confirm Payment at the bottom of the right panel. This:

Records the payment against the sale total.
Changes the button to Next.
Unlocks the Sales Team tab.

To remove a payment: click the red ✕ next to it in the Payments section of the left panel.

TOPIC: Sales Team Tab — Assigning an Employee

The Sales Team tab unlocks only after confirming payment and clicking Next. Assigning a sales associate requires two steps:

Step 1 — Add the user:

Click + Add User (top-right).
The Users dialog shows all clocked-in employees (ID, Name, Email, Position).
Use the Search field to filter if needed.
Check the checkbox on the employee row → button changes to "Add [N] Selected Users."
Click Add [N] Selected Users.

Step 2 — SELECT the user (critical):

The employee now appears in the Sales Team list with a + circle in the Select column.
Click the + circle — the row highlights pink/red. Sales Share auto-populates.
⚠️ Until the + circle is clicked, the employee is listed but NOT credited for the sale.

Other controls:

Select All Users — activates all listed employees at once.
Clear Users Selection — deselects all.
Pencil icon (✏) on Sales Share — manually adjust the commission split.

Click Complete to finalize the sale.

TOPIC: Sale Completed Screen / Receipt Options

After clicking Complete, the Sale Completed screen shows a green checkmark. Receipt options:

Option	Result
Print	Sends to connected receipt printer
Email	Emails receipt to address on file
Print & Email	Does both simultaneously
Done Without Printing	Closes without generating a receipt

Choose how many copies to print (1, 2, or 3). Receipt emails are sent from donotreply@novapointofsale.com — advise customers to check their spam folder.

TOPIC: How to Process a Layaway

Layaway holds items with a partial deposit. A customer record is required — walk-in layaways are not permitted.

Add items to the cart.
Search for and select a customer on the Customer tab (required).
Click More ▾ → Layaways.
Enter the deposit amount (must meet the minimum % set in Location Settings) → click Confirm.
The Layaway Summary screen opens:
Review Layaway Total, Layaway Paid (purple), and Layaway Due (teal).
Adjust the Expiration Date using the calendar picker if permitted.
Review the itemized product table.
Customer must draw their signature in the signature box (touchscreen or mouse). Use Clear Signature to redo.
Click Proceed to finalize. A receipt prints with a unique layaway code for pickup.

⚠️ The Proceed button is only active after the customer has signed.
⚠️ Tax Exempt mode blocks Layaway. Remove Tax Exempt first.
⚠️ Layaway confirmation emails come from donotreply@novapointofsale.com.

Layaway Summary Fields Reference
Field	Description
Layaway Total	Full sale amount on layaway
Layaway Paid	Deposit paid today (purple)
Layaway Due	Remaining balance owed on pickup (teal)
Expiration Date	Pickup deadline (editable via calendar icon)
Refund Policy	Displayed in red — set in Location Settings Layaway Disclaimer
Product Table	Itemized list: Product, Qty, Discount, Tax, Subtotal, Total
Signature Box	Customer signature area
Proceed	Finalizes layaway and prints receipt with layaway code
TOPIC: How to Create a Quote

Quotes generate a price proposal without processing payment.

Add items to the cart.
Proceed through the Customer tab.
Click More ▾ → Quotes — the Quote flow skips the payment step.
The customer receives a quote document to return and purchase later.

⚠️ Quote settings must be configured in the Management screen before this is available. If you see "Please update your quote settings from management screen," ask your manager to configure it first.
⚠️ Tax Exempt mode blocks Quotes. Remove Tax Exempt first.

TOPIC: Receipt — What's on It?
Receipt Element	Description
Invoice Number	Unique transaction identifier
Date & Time	Exact time the sale was completed
Products	Itemized list with quantities and prices
Payment Entries	Each payment listed separately (multiple cash entries = separate lines)
Sales Representative	Employee credited with the sale
Tax Numbers	TPS (GST) and TVQ (QST) registration numbers (Quebec compliance)
Refund Policy	Store return/refund policy
Barcode	Scannable barcode — scan from POS to instantly look up the transaction
TOPIC: Back Office — Location Settings

Access via Back Office navigation. Controls store-wide defaults.

General Settings
Currency Selector — set currency for all transactions.
Time Zone — accurate receipt timestamps and reporting.
Check Payment Toggle — enable/disable check as a payment method.
Gift Card Expiration — how many days gift cards remain valid.
Inventory History — days of inventory change history to retain.
Layaway Settings
Minimum Payment % — minimum deposit percentage required (cashiers see an error below this).
Expiration Days — days before an unclaimed layaway expires.
Disclaimer — custom text printed on the layaway receipt (refund/exchange terms).
Allow Customer to Change Expiration — when enabled, expiration date can be modified at deposit time.
TOPIC: Quick Reference — Buttons & Locations
Button / Feature	Location	Action
Access Store Front / Back Office	Login screen	Switch between modes
Fingerprint reader	Login screen	Biometric authentication
User avatar	Top-right (any screen)	View profile and Logout
Discount+	Storefront toolbar	Apply % / fixed / tax-exempt discount
Tax Exempt	Add Discount dialog	Requires auth; shows badge; blocks Layaway & Quotes
Coupon+	Storefront toolbar	Search and apply coupon code
More > Layaways	Storefront toolbar	Open layaway flow (requires customer + min deposit)
More > Quotes	Storefront toolbar	Create quote — no payment step
Attach File (📎)	Customer tab (top-right)	Attach document to selected customer
+ Add New Customer	Customer tab (top-right)	Open Create Customer form (3 tabs)
Red ✕ on customer row	Customer tab	Deselect current customer
Next	Bottom of right panel	Advance to next tab
Back arrow (‹)	Bottom-left of right panel	Return to previous tab
Red ✕ in Payments	Left panel — Payments section	Remove a payment entry
Confirm Payment	Payment tab (bottom)	Apply payment; unlock Sales Team tab
+ Add User	Sales Team tab	Open Users dialog to add employees
+ circle (SELECT)	Sales Team tab — Select column	Activate employee for sale credit (row turns pink)
Select All Users	Sales Team tab	Activate all listed employees at once
Complete	Bottom of Sales Team panel	Finalize sale → Sale Completed screen
Print / Email / Print & Email	Sale Completed screen	Receipt delivery options (1–3 copies)
Done Without Printing	Sale Completed screen	Close without receipt
Layaway General Settings	Back Office > Location Settings	Set min deposit %, expiration days, disclaimer
Currency / Time Zone	Back Office > Location Settings	Configure store currency and time zone
Check Payment Toggle	Back Office > Location Settings	Enable/disable check as a payment method
Gift Card Expiration	Back Office > Location Settings	Set gift card validity period (days)
TOPIC: Common Errors & What They Mean
Message / Symptom	Cause	Fix
"A layaway cannot be created with tax-exempt products."	Tax Exempt is active	Remove Tax Exempt from the sale first
"Please update your quote settings from management screen."	Quote settings not configured	Manager must configure Quote settings in Management screen
Layaway Proceed button is greyed out	Customer has not signed	Have customer sign the signature box
Coupon/Layaway/Quote option not visible	Feature not enabled or conditions not met	Check toolbar More ▾ menu; verify Tax Exempt is not active
Check payment option not shown at checkout	Check not enabled in Location Settings	Manager enables it in Back Office > Location Settings
Customer not found in search	Customer not in system	Use + Add New Customer to create record
Receipt not received by email	Spam filter	Advise customer to check spam; emails come from donotreply@novapointofsale.com
Sales associate not credited after sale	+ circle (Select) was not clicked	Must click the + circle to highlight the row; adding ≠ selecting
"Payment gateway is not configured." (blue banner)	Integrated card reader has not been set up for this location	Manager must configure the payment device in the Back Office. If you know which device is being used, Nova support can provide the setup guide for that specific terminal.
"Credit card payments are not currently available at this location." (red banner)	Credit card processing is disabled or not configured at this location	Contact your manager — this is a Back Office / payment gateway configuration issue, not a hardware issue at the register.
Product images not showing	Display Settings — images toggled off	From the Storefront, open Display Settings and enable product image display.
Items showing as a list instead of a grid (or vice versa)	Display Settings — view mode	From the Storefront, open Display Settings and switch between List View and Button/Grid View.
TOPIC: Payment Gateway Errors — "Payment gateway is not configured" / "Credit card payments are not currently available"

These are two distinct but related credit card errors that appear as banners on the Payment tab.

"Payment gateway is not configured." (blue info banner)

What it means: The integrated card processing device (e.g., Stripe Terminal, Dejavoo, PAX, Ingenico, etc.) has not been set up for this location in the Back Office. The terminal may be physically connected but the gateway configuration is missing.

What to do:

Confirm which card terminal hardware is being used at this location.
Contact Nova support or refer to the device-specific setup documentation for your terminal model.
A manager or owner must complete the payment gateway configuration in the Back Office under Location Settings.

If you know which device you have, Nova support can point you to the correct setup guide for that specific terminal.

"Credit card payments are not currently available at this location." (red error banner)

What it means: Credit card processing has been disabled or is not configured for this location. This is a location-level setting, not a register-level hardware problem.

What to do:

This requires a manager or owner to review payment method settings in the Back Office > Location Settings.
If the gateway was previously working, check whether a configuration change was recently made or whether the payment processor account is still active.

Both errors require Back Office action — they cannot be resolved from the Storefront.

TOPIC: Display Settings — Changing How Products Appear

Display Settings are accessible directly from the Storefront and control how products are shown on the product catalog screen.

How to access Display Settings

Look for the Display Settings icon (sliders/filter icon ≡⊟) on the product catalog screen toolbar.

Available options
Setting	Description
Show Product Images	Toggle product photos on or off. When off, products show as blank/dark tiles. Useful if images are not loaded or for faster rendering.
Show Barcode	Toggle whether the product barcode (ID number) is visible on each product tile.
List View	Displays products as a vertical scrollable list — one product per row with details.
Button / Grid View	Displays products as an Instagram-style grid of tiles — multiple columns of product cards. This is the default visual layout shown in the product catalog.
Which view should I use?
Grid/Button View — best for browsing by sight when product images are loaded; shows more products per screen.
List View — best when searching by name or when images are not available; easier to scan text quickly.
TOPIC: When a Storefront Issue Is Actually a Back Office Setting

Many things customers notice at the Storefront are controlled by Back Office configuration. If a feature is missing, disabled, or behaving unexpectedly, it is often a Back Office / Location Settings issue — not a Storefront bug.

Common Storefront symptoms that require Back Office changes
What you see at the Storefront	Where to fix it (Back Office)
Check payment option not visible	Location Settings → General Settings → Check Payment Toggle
Credit card not working / gateway error	Location Settings → Payment Gateway configuration
Layaway minimum deposit too high or not enforced	Location Settings → Layaway General Settings → Minimum Payment %
Layaway expiration date cannot be changed	Location Settings → Layaway General Settings → Allow Customer to Change Expiration
Gift card balance or expiry incorrect	Location Settings → General Settings → Gift Card Expiration
Quote workflow shows settings warning	Management screen → Quote Settings
Tax numbers wrong on receipts	Location Settings → Tax configuration
Currency or time zone wrong on receipts	Location Settings → General Settings → Currency / Time Zone
Inventory counts wrong or products not showing	Back Office → Inventory management
Product images missing from catalog	Display Settings (Storefront) OR check Back Office product catalog for missing image uploads
Location-specific custom fields missing	Back Office → Customer Custom Fields configuration
How to tell the difference
Storefront issue — something breaks mid-transaction or a button doesn't respond as documented.
Back Office issue — a feature or option is entirely absent, shows a configuration warning, or the values (amounts, dates, toggles) are wrong.

When in doubt, ask: "Was this ever working?" If yes and nothing changed at the register, a Back Office setting was likely changed. If it never worked, it was probably never configured.

TOPIC: Product Catalog Screen — Overview

The product catalog is the main shopping screen accessed after login.

NOVA logo + grid icon — top-left branding and app menu.
Search products — search bar at the top to find items by name or barcode.
Category tabs — filter products by category (e.g., "NEW", "Spa Lumineux"). Click the arrow (›) on a category to expand subcategories.
Product tiles — each tile shows a size/volume badge (e.g., "75 ml", "300 ml"), product name, barcode ID, price, and a cart icon to add to cart.
Filter/Display Settings icon (⊟≡) — top-right of the product grid, opens Display Settings.
Cart panel — right side shows added items, quantities, subtotal, tax, discount, total, and a Pay / $X.XX button to proceed to checkout.
Clear Cart — removes all items from the cart.
Top-right toolbar icons — quick-access icons for settings, security/lock, clock/time, reports, and user profile.
The number next to "Clear Cart" — this is The Spare

The number that appears at the top of the cart panel (for example, "75") is The Spare — the dollar amount of discount room available on the current sale. This is one of Nova's most important sales features. See the dedicated Spare topic below for full mechanics. It is critical that staff understand this is not an arbitrary number — it represents real margin available for negotiation and upselling.

Sample products visible in catalog (Spa Lumineux)
Product	Barcode	Price
Deposit	ID-312	$0.00
Shampoo (75 ml)	ID-333	$30.00
Conditioner (75 ml)	ID-334	$30.00
Hair Mask (300 ml)	ID-335	$80.00
Hair Serum (60 ml)	ID-336	$115.00
Hair Ampoules (10×10 ml)	ID-337	$200.00
Hair Regrowth Foam (60 ml)	ID-338	$40.00
Glider Soleil	ID-339	$300.00
Regular Straightener	ID-341	$300.00
Infrared Blowdryer	ID-343	$500.00
Samples by Box	ID-344	$0.00
Neck Machine	ID-345	$1,500.00

Note: Product catalog contents, images, and pricing are managed in the Back Office product catalog. Missing images on tiles mean no photo has been uploaded for that product.

TOPIC: The Spare — Nova's Built-In Discount & Upsell Tool

The Spare is one of Nova's most powerful sales features. Every salesperson and manager must understand it.

What is The Spare?

The Spare is the difference between a product's Markup Price and its Minimum Price:

Spare = Markup Price − Minimum Price

Markup Price = the retail price you normally sell the product for (shown on the sales screen as "Price Per Item")
Minimum Price = the lowest price you allow employees to sell it for without manager approval. This is hidden inside the product's barcode so the customer can't see it, but the system tracks it.

The Spare is the amount of "discount room" the salesperson has to negotiate without needing manager authorization.

Where to find The Spare on the Storefront

Once a product is added to the cart, the Spare appears as a number at the top of the cart panel, next to the Clear Cart button (for example, the "75" visible in the catalog screen). This is the total available Spare for the current sale, in dollars.

How The Spare grows with the sale

The more Non-Fixed Price items added to the cart, the larger the Spare becomes. Each Non-Fixed Price product contributes its individual Spare to the sale's total Spare pool. This is intentional design — bigger sales give salespeople more room to negotiate.

What The Spare can be used for
Use	How
Item discount	Lower the price of an item below the Markup Price, drawing from the Spare. As long as you stay at or above the Minimum Price, no manager approval is required.
Free or discounted gift card	Override a gift card's price to $0 (free) or a reduced amount — only works if there is enough Spare in the sale to cover it.
Upselling leverage	Use Spare on Item A to incentivize the customer to add Item B. Example: $30 off the customer's main item to convince them to add a $100 accessory — still profitable, no manager approval needed.
Critical rule: Spare goes down with each use

Every time you apply a discount or issue a free/reduced gift card, the Spare amount decreases by that value. Track it as you go — if you spend $50 of a $75 Spare on a discount, you only have $25 left for further negotiation or gift cards on this sale.

What happens if you price below the Minimum Price?

If a salesperson tries to override an item's price below its Minimum Price (or apply a discount larger than the available Spare), the "Cannot Complete Sale" / Minimum Price Alert window opens. Two options to resolve:

Get manager authorization — a manager logs in and approves the below-minimum sale.
Attach an Invoice with available Spare — select "Attach Invoice" and enter the invoice number of a previous sale that still has unused Spare. If the old Spare covers the deficit, the sale is approved without manager auth.
Strategy: Upselling with The Spare (recommended workflow)

This is the use case Nova explicitly promotes as a "money-making feature":

Customer shows interest in a single item — let's say a $115 product with $75 Spare.
Instead of giving a full $75 discount on that one item, offer $30 off.
Use the remaining $45 of Spare to encourage the customer to add a second item — apply a discount on that second item too.
The store walks away with two products sold, the customer feels they got two discounts, and no manager approval was needed because both discounts stayed within the combined Spare.

Net result: higher transaction value, happier customer, faster checkout — and the salesperson hits their sales targets without escalation.

Where Spare is configured (Back Office)

The Spare is configured per product, in the Back Office (Manager screen) when creating or editing a Non-Fixed Price Product. The manager sets:

Markup Price — what employees see as the default retail price
Minimum Price — the floor below which manager auth is required

Fixed Price products do not have Spare — they sell only at one price with no negotiation room. Only Non-Fixed Price products contribute to the Spare pool.

Common cashier questions about The Spare
Question	Answer
"What does the number at the top of my cart mean?"	That's The Spare — your available discount room in dollars without needing manager approval.
"Where do I see the Minimum Price?"	It's hidden inside the product barcode. You can scan or inspect it; the customer cannot see it on the screen.
"Why didn't my discount go through?"	You exceeded the available Spare and dropped below the Minimum Price. Either reduce the discount, get manager approval, or attach a prior invoice with unused Spare.
"Can I give a free gift card?"	Yes, by overriding the gift card price to $0 — but only if there is enough Spare in the sale to cover the card's value.
"Why does my cart's Spare keep changing?"	It updates in real time as you add items (Spare grows) and apply discounts or free gift cards (Spare shrinks).
"Why does this product have no Spare?"	It's set up as a Fixed Price product. Only Non-Fixed Price products contribute Spare. A manager can change this in the Back Office.
Why this is "insider context" for salespeople

The Spare is visible to the salesperson but the Minimum Price is intentionally hidden from the customer (it's tucked inside the barcode). This lets salespeople negotiate strategically without revealing how low they can actually go. Treat the Spare as a tool — not something to mention to customers by name.

End of Nova-Sales Storefront KB Article — v1.0.4.0 — May 2026 (Updated with payment gateway errors, display settings, Back Office triage guide, product catalog screen, and The Spare)

TOPIC: Main Navigation Menu — The Grid Icon (⠿)

The 9-dot grid icon (⠿) next to the NOVA logo on the product catalog screen opens the main navigation menu — a full feature panel that most new cashiers never discover because nothing on the screen indicates it exists.

How to open it

Click the 9-dot grid icon (⠿) immediately to the right of the NOVA logo in the top-left of the product catalog screen.

What is in the menu
Feature	What it does
Sales	Return to the product catalog / sales screen
Inventory	Access inventory management and counts
Reports	Full reporting and analytics
Gift Card	Gift card management (sell, look up, manage)
Cash Drawer	Open or manage the cash drawer outside of a sale
CRM	Customer Relationship Management — customer records, history
Chat	Internal team messaging or customer-facing chat
Layaways	Direct access to layaway management
Quotes	Direct access to quote creation and management
Competition	Competitor price tracking and comparison tool
My Report	Individual salesperson's own performance and sales report
Appointments	Appointment scheduling and booking management
Important notes
Layaways and Quotes are accessible BOTH from this menu AND from the More ▾ button during an active checkout. If a cashier is not in a checkout, they should use this menu.
My Report is the individual-level report — it does not require management-level access.
My Report includes From Date and To Date date pickers. If employees can only see today's My Report data or cannot change the date range, check Back Office > Locations > Settings > Edit > Preferences > Reports and clear Block employees from reviewing the salaries. Once unblocked, the employee can use My Report to review weekly or other custom timeframes.
Competition is a sales tool for referencing competitor pricing during customer negotiation.
Appointments allows booking and managing customer appointments directly from the POS.
This menu provides access to features that are not visible anywhere on the checkout flow tabs.
TOPIC: Checkout Flow — Step-by-Step for New Cashiers

A complete guide to completing a standard sale from start to finish. Print this or display it at the register for new team members.

The flow has exactly three steps

Step 1: Customer → Step 2: Payment → Step 3: Sales Team

The three tabs at the top show your progress. You cannot click the tabs — use the Next button at the bottom to advance and the back arrow (‹) at the bottom-left to go back one step.

Step 1 — Customer Tab

What you will see: A search field and large white space. This is normal — it is not broken.

Action	How to do it
Find a customer	Type their name, phone number, email, or ID in the search field
Select a customer	Click their result row — it highlights red
Continue as walk-in	Click Next without selecting anyone — this is intentional
Add a brand new customer	Click + Add New Customer (top right)
Attach a file to a customer	Select the customer first, then click the paperclip icon (📎)
Go to Payment	Click Next at the bottom

⚠️ Layaway transactions require a customer — walk-in is not permitted for layaways.

Step 2 — Payment Tab

What you will see: The Charge Amount and payment method options at the bottom.

Action	How to do it
Take a credit card	Customer Taps / Inserts / Swipes on the terminal. Click Confirm Payment.
Take cash	Click Cash at bottom → use denomination buttons or Custom → Click Confirm Payment
Take a check	Click Check → enter Name and Check No. → Click Confirm Payment
Take a gift card	Click Gift Card → search for the card → Click Confirm Payment
Card reader not working	Click Manual Entry (below the terminal box, collapsed by default) to enter card details manually
Remove a payment	Click the red ✕ next to the payment in the left panel
Go to Sales Team	Click Next after Confirm Payment changes the button

⚠️ "Payment gateway is not configured" (blue banner) means the card processing setup is incomplete in the Back Office — contact your manager. The terminal hardware may still show "Ready" even when the gateway is not configured — these are two separate things.

Step 3 — Sales Team Tab

What you will see: A list area for assigning sale credit to employees. This step has two parts that BOTH must be completed.

This is the most common training failure — read carefully.

Action	How to do it
Part 1 — Add the employee	Click + Add User → check the employee's checkbox in the dialog → click Add [N] Selected Users
Part 2 — SELECT the employee (critical)	Back in the Sales Team list, click the + circle in the Select column → the row turns pink/red
Confirm it worked	The row MUST be highlighted pink before clicking Complete
Adjust commission split	Click the pencil icon (✏) next to Sales Share
Complete the sale	Click Complete — only after the row is highlighted pink

⚠️ Adding is not the same as selecting. An employee in the list but NOT highlighted is NOT credited for the sale. There is no warning if you skip Part 2 — the sale will complete silently and the employee gets zero commission.

Sale Completed Screen

After clicking Complete, a green checkmark confirms the sale is done. Choose your receipt option:

Option	Result
Print	Sends to receipt printer (select 1, 2, or 3 copies)
Email	Sends to the customer's address on file
Print & Email	Both simultaneously
Done Without Printing	Closes the sale with no receipt generated

📧 Receipt emails come from donotreply@novapointofsale.com — advise customers to check spam if they do not receive it.

TOPIC: Common New Cashier Questions — Checkout
"Why is my screen blank after clicking Pay?"	The Customer tab shows empty white space until you search. It is not broken. Type a name to search, or click Next to continue as walk-in.
"Why can't I click Payment?"	The tabs are progress indicators, not buttons. Only the Next button at the bottom advances you.
"How do I skip the customer step?"	Click Next without selecting anyone — walk-in is automatic.
"The employee was added but didn't get credit."	They were not selected. Go back and click the + circle in the Select column so the row turns pink.
"The terminal says Ready but nothing processes."	The terminal hardware is connected but the payment gateway software is not configured. Contact your manager.
"What is that number next to Clear Cart?"	That is The Spare — your available discount room in dollars. See the Spare topic for full details.
"Where is the cash payment option?"	Click the Cash button at the bottom of the Payment tab.
"Where are Layaways?"	Either More ▾ during checkout, or the grid menu (⠿) on the catalog screen.
"Where are Appointments?"	In the grid menu (⠿) next to the NOVA logo on the catalog screen.

End of Nova-Sales Storefront KB Article — v1.0.4.0 — May 2026 (Updated: checkout UX feedback integration, grid navigation menu, new cashier step-by-step guide)
