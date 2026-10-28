# Nova OpenAPI

Use the production API at `https://openapi.novapointofsale.com` only through the
typed `nova_api_*` operations in the lane's scoped operations MCP. The public
health endpoint and OpenAPI document are not proof that a tenant credential is
valid.

Required sequence:

1. Call `nova_api_health` and require HTTP 200 / provider status `ok`.
2. Call `nova_api_preflight` with one exact Nova account name. It must complete
   a tenant login and authenticated `GET /api/regions` read.
3. Use only the exposed read operations for that same configured tenant.
4. If preflight is unavailable or fails, keep the existing bounded Nova SQL read
   fallback. Never substitute a database/company password for an API password.

The current MCP intentionally exposes no Nova API create, update, adjust,
check-in/out, payment, or delete operation. API responses are bounded to 200
rows per page and 5 MB. Tokens and passwords never appear in tool output.

Configure one tenant credential through `NOVA_OPENAPI_USERNAME` plus
`NOVA_OPENAPI_PASSWORD`, or preferably a service-only JSON file referenced by
`NOVA_OPENAPI_CREDENTIAL_FILE`. The JSON object has `username` and `password`
keys. Keep the file outside shared workspaces with a service/operator-only ACL.

Official references:

- `https://openapi.novapointofsale.com/swagger/index.html`
- `https://docs.openapi.novapointofsale.com/`
