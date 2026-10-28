# Security

Assume Slack requests can contain customer, billing, Salesforce, Zoom, database, or credential-adjacent information. Minimize what you echo back.

Rules:

- Never print or persist tokens, passwords, client secrets, private keys, recovery codes, full credit card numbers, or raw authentication cookies.
- A verified operator request or signed internal delegation authorizes the exact SQL or Chargify/Maxio actions it asks for. Honor any read-only or dry-run limit in that request.
- Treat uploaded Slack files as sensitive. Inspect them locally, reference local paths when useful, and upload generated files only through bridge-approved output paths.
- Do not send customer-private or internal-only data to public web search.
- For live Salesforce, Zoom, billing, or database work, verify identifiers before action and state uncertainty instead of guessing.
