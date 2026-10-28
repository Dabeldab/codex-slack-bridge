# Nova Openapi Support Kb

Source: Zoom Knowledge Library browser export
KB ID: maiforn3tkhhimo9c68wnh63
Article ID: re71ou1jy7t68lwmhitp63ce
Product lane: General
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/maiforn3tkhhimo9c68wnh63/articles/re71ou1jy7t68lwmhitp63ce
Updated: 06/30/2026, 12:22 PM

# Nova OpenAPI support guidance

Use this knowledge when a customer asks about the Nova OpenAPI, API base URL, Swagger, developer API keys, API username/password, Bearer token, JWT, permanent token, production API access, invoice sync, accounting sync, CRM sync, Alegra, GoHighLevel, or similar custom integration access.

Customer-facing answer

The Nova OpenAPI production base URL is:

https://openapi.novapointofsale.com

API reference and Swagger documentation:

https://docs.openapi.novapointofsale.com/ https://openapi.novapointofsale.com/swagger/index.html

Authentication uses POST /api/auth/login with username and password. The username is the Nova account name, not an email address. The password is an API password provisioned by Nova. A successful login returns accessToken, tokenType Bearer, and tenantId. Use the returned token as Authorization: Bearer <token> on later requests.

Tokens are not permanent. The published docs state that tokens are valid for 60 minutes by default. There is no refresh-token mechanism in the published docs; authenticate again when the token expires or a previously working request returns 401.

GET /api/health and POST /api/auth/login are the only unauthenticated endpoints in the published docs.

The published API includes these documented endpoint groups:

Regions: GET /api/regions
Locations: GET /api/locations/{regionId}/locationsbyregion, GET /api/locations/timezones, GET/PUT location general settings and preferences
Invoices: GET/POST /api/invoices, GET/PUT/DELETE /api/invoices/{invoiceId}, GET/PUT /api/invoices/{invoiceId}/payments, PUT /api/invoices/{invoiceId}/customer-notes
Customers: GET/POST /api/customers, GET/PUT /api/customers/{customerId}
Products: GET/POST /api/products, GET/PUT /api/products/{productId}, variants, categories, and category product/subcategory lookups
Inventory: GET /api/inventory, product inventory lookups, product transactions, quantity adjustment, threshold update, removal from a location, and tester/damage/loss entries
Users: GET/POST /api/users, GET /api/users/{userId}, update user general info, roles, and salary
Employee timeclock: check in, check out, clock-in/out records, and totals
Appointments and appointment types: list, create, update, delete
Health: GET /api/health

For billing, accounting, CRM, or reporting integrations, the most relevant documented resources are usually invoices, invoice payments, customers, products, regions, and locations. Do not promise that a specific third-party integration, such as Alegra or GoHighLevel, is already built in unless support confirms it. The API can provide the Nova-side endpoints; the customer or integrator is responsible for their external system's mapping unless Nova Support confirms a supported integration path.

If a customer asks for a "permanent Bearer token" or "permanent JWT", correct that gently: the published API uses short-lived Bearer JWT access tokens from POST /api/auth/login, valid for 60 minutes by default. The documented pattern is to re-authenticate when the token expires.

If a customer asks what they can test first after receiving credentials, suggest GET /api/regions as a safe read-only smoke test.

Security and escalation rules

Never provide, generate, guess, expose, or request API passwords, JWTs, bearer tokens, secrets, card numbers, or private credentials in chat.

If the customer is asking to receive or provision API credentials, API username/password, developer keys, a production token, or account-specific access, explain that support must verify the account and handle credential provisioning securely. Then offer the Support button.

Do not ask the customer to restate an API credential request when it is already clear. Answer the public documentation facts first, then explain that account-specific credentials require Support verification.

Use a warm handoff like:

I can help point you in the right direction. The production API base URL is https://openapi.novapointofsale.com, and API access uses a short-lived Bearer JWT from POST /api/auth/login. For security, I cannot issue or share API credentials in chat. To get API credentials provisioned for your account, I will connect you with Nova Support so they can verify the account and handle the request safely. Please click Support below and I will pass along that you need production OpenAPI credentials for your billing/CRM integration.

Preserve the customer's company name, requested integration purpose, and requested systems in the handoff context when possible.

Example for Orogold Cosmetics request

Customer asks: I need the Production API URL and a Developer API Access Token/Bearer Token to integrate POS sales with Alegra or GoHighLevel.

Answer: The production API base URL is https://openapi.novapointofsale.com. The docs are available at https://docs.openapi.novapointofsale.com/ and Swagger is at https://openapi.novapointofsale.com/swagger/index.html.

Access is handled through POST /api/auth/login using the Nova account name and an API password provisioned by Nova. The API returns a Bearer JWT accessToken, but the token is not permanent. The published docs say tokens are valid for 60 minutes by default, with no refresh-token mechanism.

The API includes documented resources for invoices, invoice payments, customers, products, regions, and locations, which are usually the relevant Nova-side resources for billing and CRM sync work.

For security, I cannot issue or share API credentials in chat. I will connect you with Nova Support so they can verify Orogold Cosmetics and help provision the API credentials for your billing and CRM integration. Please click Support below and I will pass this context along.
