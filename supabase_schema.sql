create table if not exists public.library_books (
  id bigint generated always as identity primary key,
  title text not null unique,
  status text not null default 'available' check (status in ('available', 'borrowed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.library_books enable row level security;

drop policy if exists "Allow public read library books" on public.library_books;
create policy "Allow public read library books"
on public.library_books
for select
to anon
using (true);

drop policy if exists "Allow public insert library books" on public.library_books;
create policy "Allow public insert library books"
on public.library_books
for insert
to anon
with check (true);

drop policy if exists "Allow public update library books" on public.library_books;
create policy "Allow public update library books"
on public.library_books
for update
to anon
using (true)
with check (true);

drop policy if exists "Allow public delete library books" on public.library_books;
create policy "Allow public delete library books"
on public.library_books
for delete
to anon
using (true);
