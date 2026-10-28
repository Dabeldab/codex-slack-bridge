# 2 A Core Concepts For AI Agent V 2

Source: Zoom Knowledge Library browser export
KB ID: h46cdey0grsoysh5ncyso0h3
Article ID: cmo7whj5z097nnp07m47jrmlt
Product lane: General
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/h46cdey0grsoysh5ncyso0h3/articles/cmo7whj5z097nnp07m47jrmlt
Updated: 05/15/2026, 05:49 PM

What Nova Is Nova is a specialty retail point-of-sale platform designed to help retail businesses operate, sell, manage customer relationships, and grow.

Nova is not only a transaction tool. It is a business operations platform that supports retail sales, pricing flexibility, customer management, reporting, employee performance tracking, inventory management, and other store operations.

Nova is intended to support retail businesses as a long-term partner, not just as a software vendor. Its model is subscription-based, but Nova is also built to help stores increase sales, improve retention, and operate more successfully over time.

Nova Positioning Nova is built as a retail business partner, not only as a software provider. Its goal is to help retail businesses succeed by supporting stronger sales performance, customer retention, operational control, and long-term growth.

Platform Hierarchy Nova is organized in layers.

The account is the top-level standalone data container. Regions provide logical and permission-based separation under the account. Locations represent the store-level operating units. Much operational activity is tied to the location context. Many business events are represented by multiple related backend objects rather than a single isolated record.

Back Office and Storefront Nova has two major sides:

Back Office, also called manager's area or back-end Storefront, also called the sale screen The Back Office is where administrative and operational setup is managed. The Storefront is where active selling takes place.

Storefront Actor Language For Storefront operational actions, the bot should use employee, Storefront employee, or salesperson.

Use customer only for customer-facing outcomes such as: receipt output promotional offer description CRM and customer-history context customer contact data other shopper-facing business outcomes

Do not describe Storefront cart actions as customer actions unless the documented workflow is explicitly customer self-service.

At a general level: Back Office actions are usually performed by managers, owners, partial owners, product managers, administrators, or other authorized Back Office users. Storefront selling actions are usually performed by employees, salespeople, or Storefront employees. Customer language should be reserved for customer-facing outcomes rather than normal employee-operated sales flow.

Identity Layers The bot should not assume that the account name, store name, and user identity are the same thing.

At a general level:

the account is the top-level business container the store name or DBA name is the operational identity that matters most in day-to-day store activity the user is the person accessing and operating within the system

Account The account is the top-level standalone data container in Nova. It contains the point-of-sale data for that business, including products, users, inventory, settings, customer information, and other business data.

An account is not linked to other accounts and does not share data with them. Accounts are independent of one another.

A person may have access to more than one account. In those cases, the Back Office may show a list of the accounts that person is allowed to manage. The person selects the account they want to enter and then signs into that account normally.

An account may have more than one owner.

Each account has one main contact. That main contact information is stored in Salesforce CRM, not inside the point-of-sale system itself.

Accounts are authenticated using a username and password pair. This may also be referred to as the company username, company password, or company access key.

The primary contact typically has that account name and key. They may share it with others, though this is not recommended. If the credentials need to be retrieved, the customer should contact human support.

Do not confuse account/company credentials with an employee/user password. For app or workstation sign-in questions, make clear which layer is being used:

the account/company name, key, or code identifies the business account the user name identifies the employee or person signing in the user password is the password on that user record, when one is set

If a user says "account password," "company key," "user password," "no location available," or "mobile/iPad login," answer with the credential distinction before giving reset or support steps.

The account name itself is fixed and cannot be changed. However, the account name usually has limited significance in day-to-day store operations. Operationally, the more meaningful name is usually the store name, sometimes referred to as the DBA name.

Ownership Authority Owners and partial owners are key administrative authorities at the account level.

At a general level:

an account may have more than one owner a partial owner may have highly elevated access access can still be restricted by assigned region This concept is important when explaining permissions and administrative authority at a high level.

Regions Regions are a logical way to separate locations and to compartmentalize access.

Key concepts:

you can create as many regions as needed regions are free to open regions are used for logical separation of locations regions are also used for permission separation Regions help determine who can access which part of the business structure. For example:

one set of salespeople may have access to one region but not another managers can be limited to one region and not another partial owners can have very elevated access but still be restricted to specific regions only The bot should treat region structure as an important visibility and permission boundary.

Locations A location is effectively a store. Nova may use the term location, but in practice this usually means the individual store or business site.

Locations can be organized under regions. A location belongs to its own operational context.

In day-to-day operations, the store name is often more meaningful than the account name. This may also be referred to as the DBA name.

Much of Nova's operational business activity is tracked in relation to a location. This includes store-level activity and records such as invoices, refunds, payment details, reports, expenses, employee information, employee salary information, inventory, inventory movements, purchase orders, activity, logs, and other operational records.

The account remains the top-level data container, while the location is one of the main operating contexts within that account.

Permissions and Access A very common reason a user cannot see a certain function or setting in the Back Office is a permission issue.

For broad access questions, the default answer pattern should be:

this is usually controlled by permissions access may depend on the user's assigned role and assigned region access if access is needed, the user should request that permission from the owner or partial owner of the account This explanation should remain general and should not attempt to define the full permissions model.

Inventory Inventory is tied to the location level.

Key concepts:

each store or location has its own inventory inventory is managed separately for each location inventory can be transferred between locations even when transfers are possible, the inventory structure itself is tied to the location The bot should treat inventory as location-based infrastructure.

Invoices and Sales Data Invoices are one of the core records in Nova and store essential sales data for the business.

At a general level, invoice-related data can include:

the location tied to the sale the date and time of the transaction subtotal, tax, and total customer association discounts payment-related totals employee-related sale attribution notes, refunds, and other sale outcomes Spare and other values used in Nova's sales and reporting logic An invoice record alone does not necessarily represent the full business event. A sale can also depend on other related backend objects, such as payment information, employee attribution, and other linked sale components.

The invoice is one of the most important business records in Nova because it captures key transactional details used across operations, reporting, customer history, and performance measurement.

Composite Data Model Many major Nova business events and features are built from multiple related backend objects. What appears to the user as one sale, one customer history item, or one reportable event may depend on several connected records behind the scenes.

The bot does not need to understand the backend structure in detail, but it should understand that Nova often works through linked data components rather than one isolated object.

Backend Versus Visible UI Not all important business data is directly visible on the screen where the user expects to see it.

Some important values exist on the backend and support logic, reporting, and cross-feature behavior even when they are not directly shown in the visible interface.

The bot should understand that not seeing a value in the UI does not always mean that value does not exist in the system.

Core Records Drive Other Features Some records in Nova are foundational and drive other features and business logic.

For example:

invoices drive much of the sales history and reporting logic customer records support CRM behavior pricing values support discounting and Spare behavior This helps explain Nova as an interconnected system rather than a set of isolated tools.

CRM and Customer Data Nova includes CRM functionality as one of its core concepts.

Nova can collect and store customer information in the system. At a general level, customer data may include:

name addresses birthday purchase history phone number email address other customer-related information defined by the business The CRM concept is important because Nova is designed not only to record sales, but also to help businesses build, manage, and retain customer relationships.

Reporting Nova has reporting as a core concept.

At a general level, Nova can generate different kinds of reports and dashboards, including:

location reports user reports product reports a general dashboard a real-time dashboard a profit and loss report other operational and performance reports Reporting is one of the ways Nova helps businesses monitor performance, understand operations, and make decisions.

This document should describe reporting only at a conceptual level and should not attempt to define exact report behavior, formulas, navigation, or filters.

Product Pricing Model Nova supports more than one pricing approach.

At a general level, Nova can support:

a fixed-price model, where the product is sold at its normal set price and no minimum price is designated a flexible pricing model, where the product has both a retail price and a minimum price In the fixed-price model, the item behaves more like a traditional point-of-sale product with a standard selling price.

In the flexible pricing model:

the retail price is the standard selling price the minimum price defines the lower pricing floor the value preserved above minimum is what allows Spare to exist This means Nova can operate either like a more conventional POS for standard fixed-price items, or like a more flexible pricing system where minimum price and Spare are part of the selling logic.

Spare Spare applies to Nova's flexible pricing model, not to fixed-price products that do not use a minimum price.

Spare is one of Nova's defining core concepts and one of the main ideas that sets Nova apart from more traditional point-of-sale systems.

At a general level:

the retail price is the standard selling price the minimum price is the lowest intended selling floor within normal pricing logic the value above the minimum price is where Spare is created The maximum possible Spare for an item is the difference between its retail price and its minimum price.

The realized Spare for a sale is the amount preserved above the minimum price when the item is sold.

Example:

retail price = $10 minimum price = $5 If the item is sold for:

$10, the Spare is $5 $8, the Spare is $3 $5, the Spare is $0 Spare is stored within the invoice on the backend. It is not typically visible when viewing the invoice directly, but it remains part of the invoice data.

Spare is not only a pricing concept. It also behaves as a usable value pool within the sales flow. Spare generated in one part of a transaction can be used to support discounts on other items in that same sales stream.

This is especially important in package-based selling. For example, a package with a retail price of $10,000 and a minimum price of $0 generates $10,000 Spare when sold at retail. That Spare can then be used to support other items or services added at no customer charge. If a product with a retail price of $100 and a minimum price of $80 is added at $0, the system can consume $80 from the available Spare pool.

Spare can be used within the same transaction, and it is also possible for Spare to be transferred from one invoice to another. The detailed transfer mechanics are covered elsewhere.

Because of this, Spare should not be treated as just another discount mechanic. It is a core part of Nova's pricing logic, sales strategy, invoice data model, and reporting model. It also plays a role in employee performance measurement through reporting.

Common Tier-One Patterns For broad tier-one reasoning, the bot should understand a few common patterns:

if a user cannot see a function or setting, permissions are often a likely reason if something appears to be missing, account, region, and location context may matter if a value is not visible on screen, it may still exist on the backend and affect logic or reporting many business events in Nova depend on more than one related backend object These are broad support patterns only and should not replace feature-specific procedures.
