-- user_media_layout: how each user arranged their Library in one language,
-- the folders they made and the order of everything in them.
--
-- Runbook, applied by hand through the Supabase connector as migration
-- `user_media_layout` on project Lang, like docs/user-media.sql.
--
-- One jsonb tree per (user, language) rather than folder and position
-- columns: a drag rewrites the order of a whole level, and saving the tree
-- in one write keeps it consistent. The API validates its shape
-- (media_import.validate_layout). Items the tree doesn't mention, such as
-- new imports, are shown at the top level, so an import never writes here,
-- and a deleted item's entry is skipped when the page reads the tree.
--
--   [{"type": "folder", "id": "f1a2b3", "name": "Songs", "color": "rose",
--     "open": true, "children": [{"type": "item", "id": "cancion-x"}]},
--    {"type": "item", "id": "el-tranvia-vuelve-3f9a1c"}]
--
-- RLS as on user_media: the API writes with the service-role key; signed-in
-- clients can read only their own row and cannot write; anon gets nothing.

create table if not exists public.user_media_layout (
    user_id     uuid not null references auth.users (id) on delete cascade,
    language    text not null check (language in ('es', 'de', 'it', 'fr')),
    tree        jsonb not null default '[]'::jsonb check (jsonb_typeof(tree) = 'array'),
    updated_at  timestamptz not null default now(),
    primary key (user_id, language)
);

alter table public.user_media_layout enable row level security;

drop policy if exists user_media_layout_select_own on public.user_media_layout;
create policy user_media_layout_select_own on public.user_media_layout
    for select to authenticated
    using (user_id = (select auth.uid()));

revoke all on public.user_media_layout from anon;
revoke insert, update, delete on public.user_media_layout from authenticated;
