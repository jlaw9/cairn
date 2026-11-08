-- Cairn's read-only mirror in Supabase. Written by `cairn export_supabase`;
-- see docs/supabase.md. Apply once per Supabase project (SQL editor, or
-- `supabase db push` with this as a migration). Re-running it is safe.
--
-- Git is the source of truth. These tables are a projection of it, rebuilt on
-- every export: nothing here is ever merged back, and a row that changes in
-- Supabase is simply overwritten by the next push.
--
-- Access: row-level security is ON and there are NO policies, so the anon and
-- authenticated keys can read nothing. Only the service role (the exporter, and
-- a server-side MCP) can. Add read policies when Crello has auth and board
-- membership — keyed on `project`, which is the unit of sharing (see
-- 2026-08-05-cairn-webapp), never on individual nodes.

create table if not exists public.cairn_exports (
    graph        text        not null,
    export_id    text        not null,
    source_sha   text        not null,          -- graph commit the mirror reflects
    exported_at  timestamptz not null,
    projects     text[]      not null,          -- what published-projects.txt allowed
    counts       jsonb       not null,
    primary key (graph, export_id)
);

create table if not exists public.cairn_nodes (
    graph         text not null,
    id            text not null,
    project       text not null,
    type          text not null,
    status        text not null,
    title         text not null,
    created       date,
    updated       date,
    author        text,                         -- derived from git, never stored in a node
    review_state  text,                         -- reviewed | unreviewed | unclassified
    meta          jsonb not null,               -- frontmatter, minus history/parents/relates
    history       jsonb not null,               -- the status event log
    body          text  not null,
    export_id     text  not null,
    source_sha    text  not null,
    fts tsvector generated always as (
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(body,  '')), 'B')
    ) stored,
    primary key (graph, id)
);

create index if not exists cairn_nodes_project on public.cairn_nodes (graph, project);
create index if not exists cairn_nodes_status  on public.cairn_nodes (graph, status);
create index if not exists cairn_nodes_fts     on public.cairn_nodes using gin (fts);

-- `target` is null when target_state = 'hidden': the edge exists, into a project
-- that is not published. A hidden edge must never look like an absent one.
create table if not exists public.cairn_edges (
    graph         text not null,
    edge_id       text not null,
    source        text not null,
    kind          text not null,                -- parent | supports | contradicts | supersedes | resolves | mentions
    target        text,
    target_state  text not null check (target_state in ('visible', 'hidden', 'missing')),
    note          text not null default '',
    export_id     text not null,
    source_sha    text not null,
    primary key (graph, edge_id)
);

create index if not exists cairn_edges_source on public.cairn_edges (graph, source);
create index if not exists cairn_edges_target on public.cairn_edges (graph, target);

-- Cairn's own views, rendered by the same code as the terminal:
--   standup, standup:<project>, digest:7d, digest:7d:<project>,
--   report, report:<project>, coverage (data only).
create table if not exists public.cairn_views (
    graph         text not null,
    key           text not null,
    project       text,
    content       text not null,                -- markdown
    data          jsonb,                        -- structured form, where there is one
    generated_on  date not null,
    export_id     text not null,
    source_sha    text not null,
    primary key (graph, key)
);

alter table public.cairn_exports enable row level security;
alter table public.cairn_nodes   enable row level security;
alter table public.cairn_edges   enable row level security;
alter table public.cairn_views   enable row level security;

-- The latest finished export per graph: what the mirror is "as of".
-- security_invoker so the view obeys the tables' RLS rather than its owner's.
create or replace view public.cairn_latest_export
    with (security_invoker = true) as
    select distinct on (graph) *
    from public.cairn_exports
    order by graph, exported_at desc;
