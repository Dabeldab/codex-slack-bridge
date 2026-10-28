# Locations Settings AI FAQ V 1

Source: Zoom Knowledge Library browser export
KB ID: n669kbqjs5h1h01ev55em8ki
Article ID: cmnnticba00o0r407ydj7kyrx
Product lane: Nova Wave
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/n669kbqjs5h1h01ev55em8ki/articles/cmnnticba00o0r407ydj7kyrx
Updated: 05/18/2026, 05:22 PM

Q: What is Location Settings?

A: Location Settings is the Back Office area where a store/location is configured. Path: Back Office > Locations > Settings.

Q: Who can edit location settings?

A: Documented access is Owner and Partial Owner. Partial Owner access is region-scoped.

Q: Do I need permission to edit location settings?

A: Yes. Documented Location Settings access is Owner or Partial Owner, and Partial Owner access is region-scoped.

Q: Why don't I see my store in Location Settings?

A: First check the Region selected in the top bar. Location visibility depends on the active region. Also confirm you have access to that region.

Q: Why can't I edit my store?

A: First check the Region selected in the top bar. Then confirm you have Location Settings access. Documented access is Owner or Partial Owner, with Partial Owner access limited by region.

Q: Why can't I click Edit on my store?

A: Check the selected Region in the top bar first. Then confirm you have Location Settings access and region access for that store.

Q: How do I change my store's name?

A: Go to Back Office > Locations > Settings. Find the store, click Edit, open General Info, update Name, and save.

Q: Do I need permission to change my store name?

A: Yes. Changing the store name requires Location Settings access. Documented access is Owner or Partial Owner, with Partial Owner access limited by region.

Q: Can I move my store to a different region?

A: Yes, but only Owner can change the Region field for a location.

Q: What happens when I move a location to another region?

A: The location moves with its settings and price list. Regional reporting is affected. The location manager remains assigned only if that user has access to the destination region.

Q: Can I add a 3rd tax rate to my location?

A: No. The documented location tax fields are Tax Rate and 2nd Tax Rate only.

Q: How many decimals can I enter for tax?

A: Up to 3 decimal places.

Q: Can I rename my tax?

A: Yes. You can change the tax display name. If left blank, it displays as Tax.

Q: Can tax be zero?

A: Yes.

Q: Can tax be negative?

A: No.

Q: What is the 2nd Tax Rate used for?

A: It is used when the location needs to apply a second tax.

Q: Does the second tax stack on the first tax?

A: The two taxes are shown separately. They do not combine into a single stacked line.

Q: How do I hide employee name on the receipt?

A: Go to Back Office > Locations > Settings > Edit > General Info > Receipt Options and enable Hide sales representative(s) from receipt.

Q: Do receipt settings affect emailed receipts too?

A: Yes. Receipt-option toggles affect both printed and emailed receipts.

Q: Why did my custom receipt header disappear?

A: If contact information changed after you edited the header, the system regenerated the header and overwrote the prior manual changes.

Q: What is the location password used for?

A: It reduces accidental sign-in to the wrong store. It is an operational control, not a strong security feature.

Q: Does changing the location password sign users out immediately?

A: No. The new password takes effect on the next login.

Q: Where is the screen timeout setting?

A: Back Office > Locations > Settings > Edit > Preferences > Security > Set screen lock time.

Q: How do I set the screen timeout for my store?

A: Go to Back Office > Locations > Settings. Find the store, click Edit, open Preferences, go to Security, update Set screen lock time, and save.

Q: Why can't I save Preferences?

A: The Time Zone field is mandatory. Preferences cannot be saved until a time zone is selected.

Q: What does list mode do?

A: List mode refers to Change sell screen to list mode. It changes the storefront selling screen from box-style display to list view.

Q: What is list mode in Location Settings?

A: It refers to Change sell screen to list mode in Preferences > Sales and changes the storefront sell screen from boxes to a list.

Q: How do I turn on list mode?

A: Go to Back Office > Locations > Settings > Edit > Preferences > Sales and enable Change sell screen to list mode.

Q: How do I block out-of-stock sales?

A: Go to Back Office > Locations > Settings > Edit > Preferences > Inventory and turn on Block sale of items out of stock.

Q: Do service products go out of stock?

A: No. Service products cannot be out of stock.

Q: How do I copy preferences from another location?

A: Go to Back Office > Locations > Settings > Edit > Preferences and use Copy preferences from another location.

Q: Why can't I copy preferences from another location?

A: Only locations in the same region are available as copy sources.

Q: Does Copy Preferences copy everything?

A: Yes. It copies everything as-is.

Q: What is Spare?

A: Spare is the amount above minimum price preserved on an invoice. It is a core Nova concept.

Q: Is Spare tied to the customer?

A: No. Spare is not customer-specific.

Q: Can any salesperson use Spare?

A: Yes. Eligible Spare is global within the location and can be used by any salesperson at that location, subject to system rules.

Q: What does Minimum spare price restriction do?

A: It adds a time barrier to Spare transfer. A setting of 0 means no additional time barrier.

Q: Can gift cards be restricted to one location only?

A: No direct single-location restriction is documented. Region-based restriction is available.

Q: Does default gift card expiration affect existing gift cards?

A: No. It applies only to newly created gift cards.

Q: What is external credit?

A: External credit means the location uses a standalone card terminal that is not connected to Nova. The employee must process the card on the terminal first, then return to Nova and enter the transaction details.

Q: Why is external credit risky if employees are not trained?

A: Nova does not communicate with the terminal. Employees must process the card on the terminal first and then enter the details correctly in Nova.

Q: What information do employees enter after using an external terminal?

A: Last four digits of the card, transaction number, and card type.

Q: Why can't I click the credit card button?

A: Check whether integrated merchant services is configured, or whether Block use of external credit card machine is still On.

Q: What does Block use of external credit card machine do?

A: When Off, external credit becomes available during checkout. When On, external credit use is blocked.

Q: What does Allow the user to manually enter credit card information do?

A: When integrated payments are used, it allows manual card entry from within Nova.

Q: What does Force the user to enter the card's CV information do?

A: It requires entry of the card security code during manual entry.

Q: What is Merchant Gateway?

A: Merchant Gateway is the provider selection field for integrated payment processing.

Q: Why is Merchant Gateway blank?

A: It has no default. It remains blank until a provider is selected.

Q: I just received my credit card terminal. What should I do?

A: Go to Back Office > Locations > Settings > Edit > Merchant Services. If you are setting up an integrated terminal, Nova support should verify the setup because provider-specific terminal setup is sensitive.

Q: How do I configure merchant services?

A: Go to Back Office > Locations > Settings > Edit > Merchant Services. Complete the provider-specific setup required for your payment solution. Integrated terminal setup should usually be verified with support.

Q: How do I set up my integrated credit card terminal?

A: Go to Back Office > Locations > Settings > Edit > Merchant Services. Integrated terminal setup is provider-specific and should usually be verified with support.

Q: Should I contact support to set up my terminal?

A: Yes. Integrated terminal and merchant-services setup is sensitive and provider-specific, so it should usually be verified with support.

Q: Why can't I see the TEST TRANSACTION button?

A: It is only available after integrated terminal setup has been completed.

Q: What is Competition?

A: Competition is a ranking feature that motivates either employees or stores as teams. It is configured in Back Office and appears in Storefront after it is enabled for the location.

Q: Why don't I see Competition on the sell screen?

A: Competition must be enabled and applied for that location in Back Office > Locations > Settings > Edit > Competition using START COMPETITION.

Q: Why don't I see Competition in Storefront?

A: Competition must be enabled for that location in Back Office and applied with START COMPETITION.

Q: Who can access Competition?

A: Competition access is inherited from Location Settings access. Documented Location Settings access is Owner and Partial Owner, with region scope.

Q: Why don't I see the Competition tab?

A: Check whether you can access Location Settings, then check the top-bar region and region scope.

Q: How do I set up Competition?

A: Go to Back Office > Locations > Settings > Edit > Competition, turn on Start Competition, choose the mode and metric, select region(s), choose a time frame, enter View top, optionally select Show ranking only, then click START COMPETITION.

Q: What are all the options in Competition?

A: Start Competition, INDIVIDUAL MOTIVATION, TEAM MOTIVATION, Total Sale, Highest Sale, Number of Products, Select Region, Competition Time frame, View top, Show ranking only, and START COMPETITION.

Q: Can you explain the Competition options?

A: INDIVIDUAL MOTIVATION ranks employees. TEAM MOTIVATION ranks stores. Total Sale ranks by highest total sales amount. Highest Sale ranks by largest single sale. Number of Products ranks by product count sold. Select Region controls which region or regions participate. Competition Time frame controls Daily, Weekly, or Monthly competition. View top controls how many ranked positions are shown. Show ranking only shows rank without exposing the value for Total Sale or Highest Sale. START COMPETITION applies the setup.

Q: What does Individual Motivation do?

A: It ranks employees against other employees.

Q: What does Team Motivation do?

A: It ranks stores against other stores.

Q: What does Total Sale mean in Competition?

A: It ranks by highest total sales amount in the selected time frame.

Q: What does Highest Sale mean in Competition?

A: It ranks by the largest single sale.

Q: What does Number of Products mean in Competition?

A: It ranks by product count sold.

Q: Can Competition include more than one region?

A: Yes. You can select one, multiple, or all regions.

Q: What does Competition Time frame do?

A: It controls whether the competition runs Daily, Weekly, or Monthly.

Q: What does View top do?

A: It controls how many ranked positions are shown, up to 24.

Q: What does Show ranking only do?

A: It shows ranking positions without exposing the sales value behind the ranking for Total Sale or Highest Sale.

Q: What setup does Nova usually recommend for Competition?

A: Individual Motivation, Total Sale, Daily, View top = 3, and Show ranking only = Off.

Q: What are CRM Mandatory Fields?

A: This tab controls which customer-information fields become required during customer entry.

Q: Who can access CRM Mandatory Fields?

A: CRM Mandatory Fields access is inherited from Location Settings access. Documented Location Settings access is Owner and Partial Owner, with region scope.

Q: How do I make Email mandatory for customer entry?

A: Go to Back Office > Locations > Settings > Edit > CRM Mandatory Fields, check Email, then click SAVE.

Q: Are any CRM fields required by default?

A: No. By default, none are selected.

Q: What tabs are under Location Settings?

A: Go to Back Office > Locations > Settings, find the location, click Edit, then choose General Info, Preferences, Merchant Services, Competition, CRM Mandatory Fields, or Alerts.

Q: What columns are on the Location Settings list?

A: The list shows Id, Location & Address, Phone, Merchant Number, Location Manager, Status, Price List, and Actions.

Q: How do I add a new location?

A: Go to Back Office > Locations > Settings and use Add New Location. If you do not see it, check Location Settings access and selected Region.

Q: Where do I change the receipt refund policy?

A: Go to Back Office > Locations > Settings > Edit > General Info > Refund Policy, update the text, then save.

Q: Where do I change the receipt header or footer?

A: Go to Back Office > Locations > Settings > Edit > General Info. Use Receipt Header Text for the top receipt message and Receipt Footer Text for the bottom receipt message.

Q: Where do I change the tax label from Tax to VAT?

A: Go to Back Office > Locations > Settings > Edit > General Info and use Tax Display As. For the second tax label, use Tax2 Display As.

Q: Where do I turn on tips for a location?

A: Go to Back Office > Locations > Settings > Edit > General Info > Receipt Options, enable Allow tip, then set Default tip (%) if needed.

Q: Why can't I set a default tip?

A: Check whether Allow tip is enabled. Default tip is tied to the tipping setup and may be disabled or ignored until Allow tip is on.

Q: What sections are inside Preferences?

A: Preferences includes Users, Sales, Security, Time zone, Inventory, Inventory History, Reports, Layaways General Setting, and Price List.

Q: Where do I set auto clock out?

A: Go to Back Office > Locations > Settings > Edit > Preferences > Users and use Automatic check out employee at this location after.

Q: Where do I enable cash count?

A: Go to Back Office > Locations > Settings > Edit > Preferences > Security and turn on Enable cash count.

Q: Where do I stop employees from opening the cash drawer before a sale?

A: Go to Back Office > Locations > Settings > Edit > Preferences > Security and enable Open cash drawer only after a sale has been made.

Q: Where do I set the store time zone?

A: Go to Back Office > Locations > Settings > Edit > Preferences > Time zone and set Location Time zone. The page may also show Auto Detect.

Q: Where do I set the location's price list?

A: Go to Back Office > Locations > Settings > Edit > Preferences > Price List and choose the Location's Price list.

Q: Where do I set up the integrated credit card terminal?

A: Go to Back Office > Locations > Settings > Edit > Merchant Services. Select Yes for the Nova integrated payment solution, complete Merchant Gateway, Merchant Number, Terminal Id, Transaction Key, and EMV device fields as applicable. Provider-specific setup should be verified with support.

Q: Where do I allow a standalone credit card terminal?

A: Review Back Office > Locations > Settings > Edit > Preferences > Sales > Enable external credit card transactions, then review Merchant Services > Credit Card Settings > Block use of external credit card machine. External credit is manual, so employees must process the card on the outside terminal and then enter the details in Nova.

Q: What fields can I make mandatory for customers?

A: CRM Mandatory Fields can require First Name, Middle Initial, Last Name, Home Phone, Birthday, Mobile Phone, Email, Address 1, Address 2, Notes, City, State, Country, and Zipcode.

Q: How do I make customer phone required?

A: Go to Back Office > Locations > Settings > Edit > CRM Mandatory Fields. Check Home Phone or Mobile Phone, depending on which phone field you want required, then click SAVE.

Q: Walk me through changing a location setting.

A: Go to Back Office > Locations > Settings, confirm the correct Region is selected, find the location, click Edit, open the needed tab, make the change, then use the tab's Save, SAVE, SAVE PREFERENCES, or START COMPETITION button depending on the page.

Q: Walk me through changing receipt text.

A: Go to Back Office > Locations > Settings, click Edit for the location, open General Info, scroll to Receipt Options, update Receipt Header Text, Receipt Footer Text, or Refund Policy, review Receipt Preview, then click Save.

Q: Walk me through requiring customer information at checkout.

A: Go to Locations > Settings > Edit > Preferences > Sales, enable Enforce customer information collection during the sale, and save preferences. Then open CRM Mandatory Fields, check the specific customer fields that must be required, and click SAVE.

Q: Walk me through setting up a competition.

A: Go to Locations > Settings > Edit > Competition, turn on Start Competition, choose Individual or Team Motivation, choose Total Sale, Highest Sale, or Number of Products, select Region, choose Daily, Weekly, or Monthly, enter View top, optionally enable Show ranking only, then click START COMPETITION.
