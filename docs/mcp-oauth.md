# Connecting an AI app to Langfour

The streamable HTTP MCP endpoint is:

```
https://major-wynny-victorfriedrich-7c04e8cd.koyeb.app/mcp
```

Use **OAuth** in ChatGPT's developer-mode custom app or a Claude remote
connector. Supabase handles client registration, authorization codes, PKCE,
refresh tokens and consent grants. Langfour supplies the consent page and
protected-resource metadata. RemNote does not need to be published to test MCP.
The only tool currently exposed is `record_practice`.

## Deployment order

1. Deploy the API and web changes together. The consent page is
   `https://app.langfour.com/oauth/consent`.
2. Apply `supabase/migrations/20261029160840_mcp_oauth.sql` to the project.
   It adds an inert function until step 3; it does not change learner data.
3. In Supabase **Authentication → Auth Hooks**, enable the **Custom Access
   Token** Postgres hook `public.langfour_mcp_access_token`. If another token
   hook is already configured, integrate these restrictions into it instead
   of replacing it.
4. In **Authentication → URL Configuration**, verify that **Site URL** is
   `https://app.langfour.com`. Keep the existing login callback allowlist.
5. In **Authentication → OAuth Server**, enable OAuth, set the authorization
   path to `/oauth/consent`, and enable dynamic client registration. Registration
   alone grants no access: each user must sign in and approve the client.
6. Add the MCP URL in ChatGPT or Claude, choose OAuth, then sign in and approve.
   No static client ID or secret is needed with dynamic registration enabled.

The Supabase MCP integration can apply the SQL, but does not expose Auth
configuration updates; steps 3–5 require the dashboard or Management API.

The requested scope is `email`. OIDC ID tokens are unnecessary. Do not request
`openid` on a project still using HS256; Supabase requires an asymmetric signing
key for ID tokens. This integration verifies access tokens through Supabase
Auth, so it works with either existing HS256 or asymmetric signing keys.

## Access boundaries

- `/.well-known/oauth-protected-resource/mcp` (and the root alias) is public.
  A 401 from `/mcp` advertises it with `WWW-Authenticate`.
- The advertised resource comes from `MCP_RESOURCE_URL`, never the incoming
  Host header. Its default is the production endpoint above. For a different
  deployment, change both this environment variable and the hook's audience.
- The hook applies to **all third-party OAuth clients in this Supabase project**.
  It preserves `authenticated` as the first audience for Supabase's `/user`
  validation endpoint, and adds the exact MCP URL as the second audience.
- OAuth grants carry `role: langfour_mcp`. This is intentionally **not a
  Postgres role**. Do not create that role or grant it to `authenticator`.
  Supabase's Data API cannot assume it, preventing reuse of normal user RLS
  grants or RPC permissions. The API rejects OAuth tokens outside `/mcp`.
- The MCP middleware checks the token with Supabase Auth (signature and live
  user/session), then checks issuer, exact audiences, client, role, subject,
  expiry and non-anonymous status. Its successful-verification cache lasts at
  most 120 seconds; expiry is checked on every MCP request.
- Normal web and extension sessions are unchanged by the hook. Existing manual
  session-token access to `/mcp` is replaced by OAuth; RemNote tokens remain
  restricted to their sync endpoints.

## Smoke test

1. `GET /.well-known/oauth-protected-resource/mcp` must return the correct
   `resource` and Supabase `authorization_servers` without a bearer token.
2. `POST /mcp` without a token must return 401 with a metadata challenge.
3. Connect through an OAuth client. Verify both Deny and Allow paths, and that
   a signed-out user returns to consent after following the login email.
4. List tools; expect `record_practice`. Ask the AI to report a short practice
   session with one **existing learning word** and check that Langfour records
   the result. This changes real learning progress; choose the example yourself.
5. A token refresh must retain the MCP audiences and role. The OAuth token must
   fail on `/api/translate-word`, RemNote pairing/admin endpoints, and Supabase's
   Data API. Another user's data must never be used for the practice event.
6. Revoke the client grant (Supabase Auth OAuth `revokeGrant(clientId)`), then
   verify refresh fails and MCP access stops within the 120-second cache TTL.

## Local verification

```
PYTHONPATH=apps/api apps/api/.venv/bin/pytest apps/api -q
npm run test:web
npm run build:web
```

`supabase/tests/mcp_oauth.sql` verifies the hook in Postgres without changing
learner data. Run after the migration with `psql -v ON_ERROR_STOP=1 -f ...`.
The tests use a rollback and exercise normal sessions, OAuth refresh claims,
audience binding, idempotence, and execution permissions.

References: [Supabase MCP authentication](https://supabase.com/docs/guides/auth/oauth-server/mcp-authentication),
[Supabase token security](https://supabase.com/docs/guides/auth/oauth-server/token-security),
[OpenAI MCP authentication](https://developers.openai.com/plugins/build/auth).
