begin;

-- The MCP resource moved from Koyeb's default hostname to api.langfour.com
-- (the same service). Only the audience changes; see 20261029160840_mcp_oauth.sql
-- for why each claim is set. Apply after the API that accepts the new audience
-- is deployed: it also accepts the old one, so tokens issued before this ran
-- keep working until they expire.
create or replace function public.langfour_mcp_access_token(event jsonb)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  claims jsonb := event->'claims';
  client_id text := coalesce(nullif(event->>'client_id', ''), nullif(event->'claims'->>'client_id', ''));
begin
  if client_id is not null then
    -- /auth/v1/user requires authenticated as its first audience. The MCP
    -- resource checks the second audience too, after Supabase verifies the
    -- signature and live session. Do not add other resource audiences here.
    claims := jsonb_set(claims, '{aud}',
      '["authenticated", "https://api.langfour.com/mcp"]'::jsonb);
    claims := jsonb_set(claims, '{client_id}', to_jsonb(client_id));
    -- Deliberately NOT a Postgres role: PostgREST cannot SET ROLE to it, so a
    -- third-party token cannot reuse first-party grants, RPCs or RLS policies.
    -- Do not create this role or grant it to authenticator.
    claims := jsonb_set(claims, '{role}', '"langfour_mcp"'::jsonb);
    return jsonb_set(event, '{claims}', claims);
  end if;
  return event;
end;
$$;

revoke all on function public.langfour_mcp_access_token(jsonb) from public, anon, authenticated;
grant execute on function public.langfour_mcp_access_token(jsonb) to supabase_auth_admin;

commit;
