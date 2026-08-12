-- Sameness Index — run storage.
--
-- One row per run. It holds what was asked for, what the run said while it
-- worked, and what it produced. The result JSON is the whole of what /r/<id>
-- renders, so a permalink needs nothing else.
--
-- The crawled website text is deliberately not stored. Re-scoring a past run
-- without re-crawling would be useful, but it means holding copies of other
-- companies' websites, and that is not a thing to do casually.
--
-- Applied to the Rupture Tools project. Kept here so the schema is readable
-- alongside the code that depends on it.

create table if not exists runs (
    id           text primary key,
    status       text        not null default 'running'
                             check (status in ('running', 'complete', 'failed')),
    created_at   timestamptz not null default now(),
    started_at   timestamptz,
    finished_at  timestamptz,

    -- what was asked for
    brands       jsonb       not null default '[]'::jsonb,
    category     text,

    -- what happened
    progress     jsonb       not null default '[]'::jsonb,
    result       jsonb,
    error        text,

    -- the headline numbers, lifted out of result so a run is legible in a
    -- table without opening the JSON
    summary      jsonb,

    -- who ran it. email and email_domain are filled by the email gate, which
    -- is the next phase; the columns exist now so that does not need a
    -- migration mid-flight.
    client_ip    text,
    user_agent   text,
    email        text,
    email_domain text,
    notified     boolean     not null default false
);

create index if not exists runs_created_at_idx on runs (created_at desc);
create index if not exists runs_status_idx     on runs (status);
create index if not exists runs_ip_recent_idx  on runs (client_ip, created_at desc);

-- The service talks to this table with the service role, which bypasses row
-- level security. Enabling RLS with no policies means the anon and
-- authenticated keys can read nothing — so a leaked publishable key exposes
-- no run, no competitor set and no email address.
alter table runs enable row level security;

comment on table runs is
    'Sameness Index runs. One row per analysis; result holds the full report rendered at /r/<id>.';
