# Weekendkrant Ingress

Private Site and single MCP producer tool `submit_weekendkrant_fiche`.
Input: any top-level JSON object; the entire object is posted unchanged.
Discovery: fixed public raw GitHub main/config/ingress-endpoint.json.
Outbound: raw.githubusercontent.com and only the validated single-label
*.trycloudflare.com endpoint; HTTPS only, no credentials/ports/fragments,
redirects disabled. No retries. No logging or upstream error-body forwarding.

Requires Sites runtime secret WEEKENDKRANT_INGRESS_TOKEN (is_secret=true),
read exclusively through Worker env. Never put its value in source or chat.
Sites secret configuration is Site-wide, not bound to a destination.

STATUS: NOT PUBLISHED. Awaiting secure owner secret configuration and a live
fictitious POST test. The numeric ingress response `id` field must be verified
against the actual API before publication. Mock tests do not establish that
contract or live connectivity. Owner-only Sites boundary plus authenticated
user header guards MCP writes.

Run npm test and npm run build. No dependencies are needed.
