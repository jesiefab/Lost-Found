-- Lost & Found Board — the only table.
-- Run once in the Supabase SQL editor (project → SQL → New query).
--
-- RLS is enabled with NO policies on purpose: the anon key can read nothing.
-- Every read and write goes through the Flask function, which holds the
-- service role key in Vercel's environment variables only.

create table if not exists items (
  id bigserial primary key,
  kind text not null check (kind in ('lost', 'found')),
  title text not null,
  description text not null default '',
  category text not null default 'other',
  location text not null default '',
  date_iso date not null,
  status text not null default 'open' check (status in ('open', 'claimed', 'returned')),
  reporter text not null default '',
  tags jsonb not null default '[]'::jsonb,
  owner_token text not null,
  is_sample boolean not null default false,
  created_at timestamptz not null default now()
);

alter table items enable row level security;  -- and no policies: anon does nothing

create index if not exists items_date_idx on items (date_iso desc);
create index if not exists items_sample_idx on items (is_sample);

-- After `python scripts/seed.py --push` (which inserts explicit ids, so the
-- snapshot and the table share them), move the sequence past the seed:
--
--   select setval(pg_get_serial_sequence('items', 'id'), (select max(id) from items));
--
-- Without that line the next insert from the browser would collide with id 1.
