\set ON_ERROR_STOP on
begin;
do $$
declare
  direct jsonb := '{"claims":{"aud":"authenticated","role":"authenticated","sub":"user-a"}}';
  oauth jsonb := '{"claims":{"aud":"authenticated","role":"authenticated","sub":"user-a","client_id":"client-a"},"authentication_method":"token_refresh"}';
  result jsonb;
begin
  assert public.langfour_mcp_access_token(direct) = direct, 'Direct login changed';
  result := public.langfour_mcp_access_token(oauth);
  assert result#>>'{claims,role}' = 'langfour_mcp', 'Wrong role';
  assert result#>'{claims,aud}' = '["authenticated","https://major-wynny-victorfriedrich-7c04e8cd.koyeb.app/mcp"]'::jsonb, 'Wrong audience';
  assert result#>>'{claims,client_id}' = 'client-a', 'Missing OAuth client';
  assert result#>>'{claims,sub}' = 'user-a', 'Identity changed';
  assert public.langfour_mcp_access_token(result) = result, 'Hook not idempotent';
end;
$$;
do $$
begin
 assert has_function_privilege('supabase_auth_admin', 'public.langfour_mcp_access_token(jsonb)', 'execute');
 assert has_schema_privilege('supabase_auth_admin', 'public', 'usage');
 assert not has_function_privilege('anon', 'public.langfour_mcp_access_token(jsonb)', 'execute');
 assert not has_function_privilege('authenticated', 'public.langfour_mcp_access_token(jsonb)', 'execute');
 assert not exists(select from pg_roles where rolname='langfour_mcp');
end;
$$;
rollback;
