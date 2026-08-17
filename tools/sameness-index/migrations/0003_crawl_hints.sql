-- What it takes to read a given host.
--
-- Reading a pharma brand site is a negotiation: some serve their words to a
-- plain HTTP request, some serve a shell and build the copy in the browser,
-- and most put a region selector or an audience attestation in front of the
-- content. Working that out costs a wasted request and sometimes a wasted
-- browser render — every run, for the same hosts, forever.
--
-- So it is worked out once and remembered here. A host known to need a browser
-- gets one on the first request instead of the second, which is a page load and
-- several seconds saved per brand. A host known to open with a particular
-- button gets that button tried first.
--
-- Nothing here is private and nothing here is about a person: it is a hostname
-- and a note on how its front door works.

create table if not exists crawl_hints (
  host           text primary key,          -- lower-cased, no www.

  -- Plain HTTP was not enough last time: go straight to the browser.
  needs_browser  boolean not null default false,
  -- The text on the control that got through the front door, so the next run
  -- tries the one that worked rather than the whole list in order.
  gate_text      text,
  -- How many doors there were. Two is region-then-audience, the common
  -- pharma arrangement.
  gate_hops      smallint not null default 0,

  -- What actually happened last time, so a host that starts refusing can be
  -- spotted without reading a whole run's narration.
  last_chars     integer,                   -- readable characters recovered
  last_status    smallint,
  ok_at          timestamptz,
  fail_count     smallint not null default 0,

  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

-- RLS on with no policies, exactly as `runs` and `brand_sites` are: only the
-- service role reads it, and an anon key exposes nothing.
alter table crawl_hints enable row level security;
