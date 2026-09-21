-- 0004_harden_function_search_path.sql
--
-- Pins the search_path on touch_updated_at().
--
-- Supabase's database linter flags this as function_search_path_mutable, and
-- it is a real finding rather than noise. A plpgsql function with an inherited
-- search_path resolves its unqualified names against whatever the *calling*
-- role's search_path happens to be. Anyone able to create objects in a schema
-- that sits earlier in that path can shadow a function this one calls and have
-- their version run instead - with this function's privileges, inside a
-- trigger, on every update to halls.
--
-- The blast radius here is small: the body calls now() and nothing else, and
-- it runs as the invoker. But the cost of closing it is one line, the argument
-- for leaving it open is "probably fine", and this trigger fires on the one
-- table that holds operational configuration.
--
-- search_path is set empty rather than to a schema list, so every name has to
-- be schema-qualified and nothing is resolved by position. pg_catalog is still
-- searched implicitly, so pg_catalog.now() is written out for clarity rather
-- than necessity.
--
-- https://supabase.com/docs/guides/database/database-linter?lint=0011_function_search_path_mutable

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    new.updated_at = pg_catalog.now();
    return new;
end;
$$;

-- The trigger already points at this function by name, so replacing the body
-- is enough; it is recreated here only so the file stands alone if applied to
-- a database that somehow lost it.
drop trigger if exists halls_touch_updated_at on public.halls;
create trigger halls_touch_updated_at
    before update on public.halls
    for each row execute function public.touch_updated_at();
