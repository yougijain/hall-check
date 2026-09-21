import { createClient } from "@supabase/supabase-js";

/**
 * Read-only Supabase client.
 *
 * The anon key is compiled into the browser bundle, which is intended rather
 * than tolerated: row level security and column grants mean it can select
 * counts and a subset of hall columns, and nothing else. There is no write
 * path for it to reach. See db/migrations/0002_rls_and_read_views.sql, and
 * db/tests/access_model.sql for the assertions that keep it that way.
 *
 * The service role key must never appear in this project.
 */

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export const isConfigured = Boolean(url && anonKey);

export const supabase = isConfigured
  ? createClient(url!, anonKey!, {
      auth: { persistSession: false, autoRefreshToken: false },
    })
  : null;
