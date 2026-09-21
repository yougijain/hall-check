/**
 * Every read the site makes.
 *
 * All of it goes through the anon key against views and tables that row level
 * security has already narrowed. There is no write path here and no server
 * secret; if this file ever needs one, the access model has gone wrong rather
 * than the file.
 *
 * A failed query returns empty rather than throwing. The dining hall page is
 * not important enough to show an error screen over - an unknown count is a
 * perfectly good answer and the page is built to say it.
 */

import { supabase } from "./supabase";
import { startOfCampusDay } from "./hours";
import type { CountPoint, HallLatest, HallSummary } from "./types";

export async function getHallLatest(): Promise<HallLatest[]> {
  if (!supabase) return [];

  const { data, error } = await supabase
    .from("hall_latest")
    .select("*")
    .order("name", { ascending: true });

  if (error) {
    console.error("hall_latest query failed:", error.message);
    return [];
  }
  return (data ?? []) as HallLatest[];
}

export async function getHalls(): Promise<HallSummary[]> {
  if (!supabase) return [];

  const { data, error } = await supabase
    .from("halls_public")
    .select("hall_id, name, opens_at, closes_at")
    .order("name", { ascending: true });

  if (error) {
    console.error("halls_public query failed:", error.message);
    return [];
  }
  return (data ?? []) as HallSummary[];
}

/** Readings for one hall since the start of the current campus day. */
export async function getTodaysCounts(hallId: string, now: Date = new Date()): Promise<CountPoint[]> {
  if (!supabase) return [];

  const { data, error } = await supabase
    .from("counts")
    .select("ts, count")
    .eq("hall_id", hallId)
    .gte("ts", startOfCampusDay(now).toISOString())
    .order("ts", { ascending: true });

  if (error) {
    console.error("counts query failed:", error.message);
    return [];
  }
  return (data ?? []) as CountPoint[];
}
