-- ZeeChecker rule store: document styles and their rules, plus a history of every change.
-- Safe to run more than once.

create table if not exists public.styles (
    id          text primary key,                 -- e.g. daily_report
    name        text not null,                    -- e.g. Daily report
    description text not null default '',
    detect      jsonb not null default '[]',      -- words used by Auto-detect
    rules       jsonb not null default '[]',      -- list of rules, same shape as rules/*.yaml
    updated_at  timestamptz not null default now(),
    updated_by  text not null default ''
);

-- The version of a style *before* each change, so any change can be undone
create table if not exists public.style_history (
    history_id  bigint generated always as identity primary key,
    style_id    text not null,
    name        text,
    description text,
    detect      jsonb,
    rules       jsonb,
    updated_at  timestamptz,
    updated_by  text,
    action      text not null,                    -- 'update' or 'delete'
    archived_at timestamptz not null default now()
);

create index if not exists style_history_style_id_idx on public.style_history (style_id, archived_at desc);

-- No policies on purpose: only the app's secret key (server side) can read or write
alter table public.styles enable row level security;
alter table public.style_history enable row level security;

-- New Supabase projects don't expose new tables to the API automatically: allow the secret key only
grant usage on schema public to service_role;
grant select, insert, update, delete on public.styles, public.style_history to service_role;
grant usage, select on all sequences in schema public to service_role;

create or replace function public.archive_style()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    insert into public.style_history (style_id, name, description, detect, rules, updated_at, updated_by, action)
    values (old.id, old.name, old.description, old.detect, old.rules, old.updated_at, old.updated_by, lower(tg_op));
    if tg_op = 'DELETE' then
        return old;
    end if;
    new.updated_at := now();
    return new;
end;
$$;

drop trigger if exists archive_style on public.styles;
create trigger archive_style
    before update or delete on public.styles
    for each row execute function public.archive_style();
