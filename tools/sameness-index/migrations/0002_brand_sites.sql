-- The brand directory.
--
-- Finding a brand's real website is the slowest and least reliable part of a
-- run: candidate addresses are guessed from the brand name and then fetched one
-- by one to see which exist. That work is identical every time anybody runs the
-- same category, so it is paid for once and remembered here.
--
-- Two addresses per brand because they are two different sites with two
-- different audiences, and reading the wrong one produces a report about the
-- wrong conversation.
--
-- `confirmed_by` distinguishes an address the crawler proved works from one a
-- human corrected. A hand-corrected entry is never overwritten by the crawler,
-- because a person looking at the page knows something the fetcher does not.

create table if not exists brand_sites (
  brand          text primary key,          -- lower-cased, the lookup key
  display_name   text not null,             -- as it should appear on the page
  generic_name   text,
  company        text,
  pharm_class    text,

  patient_url    text,
  hcp_url        text,

  -- What was actually served when the address was last checked, so a site that
  -- quietly starts turning crawlers away can be spotted without a full run.
  patient_ok     boolean,
  hcp_ok         boolean,

  confirmed_by   text not null default 'crawler',   -- 'crawler' | 'human'
  checked_at     timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

-- Finding every brand in a class is how the competitive set is proposed, so it
-- is worth an index once the table has more than a page of rows in it.
create index if not exists brand_sites_class_idx on brand_sites (pharm_class);

-- The table holds nothing private — published brand names and published web
-- addresses — but RLS is on with no policies, exactly as `runs` is, so only the
-- service role reads it and nothing is exposed by an anon key.
alter table brand_sites enable row level security;
