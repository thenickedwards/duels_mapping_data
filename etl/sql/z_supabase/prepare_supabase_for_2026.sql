-- Readies the Supabase copies of the Schmetzer Score tables for the October 2026 changes.
-- Run this in the Supabase SQL editor, then run the sync:
--     source ./duels_mapping.sh sync
--
-- 1. schmetzer_scores_2026 is new. The sync upserts into tables that already exist, so it
--    is created here with the 2025 table's shape and the same read-only policy as the rest
--    (see restrict_supabase_write_access.sql).
-- 2. schmetzer_score_per_million is no longer stored; the app derives it from the score
--    and salary columns.
-- 3. The id dropped its nationality suffix ('cristianroldan-1995-2024-seattlesoundersfc-usa'
--    became 'cristianroldan-1995-2024-seattlesoundersfc'). The sync upserts on id, so
--    without clearing the tables every player would appear twice. SQLite is the source of
--    truth for these tables, so everything deleted here comes back on the next sync.
--
-- Safe to re-run: every statement is guarded.

CREATE TABLE IF NOT EXISTS public.schmetzer_scores_2026 (LIKE public.schmetzer_scores_2025 INCLUDING ALL);

ALTER TABLE public.schmetzer_scores_2026 ENABLE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'schmetzer_scores_2026'
          AND policyname = 'Allow public read access'
    ) THEN
        CREATE POLICY "Allow public read access" ON public.schmetzer_scores_2026 FOR SELECT USING (true);
    END IF;
END
$$;

DROP INDEX IF EXISTS public.idx_schmetzer_scores_all__value;

DO $$
DECLARE
    target_table TEXT;
BEGIN
    FOREACH target_table IN ARRAY ARRAY[
        'schmetzer_scores_all',
        'schmetzer_scores_2018',
        'schmetzer_scores_2019',
        'schmetzer_scores_2020',
        'schmetzer_scores_2021',
        'schmetzer_scores_2022',
        'schmetzer_scores_2023',
        'schmetzer_scores_2024',
        'schmetzer_scores_2025',
        'schmetzer_scores_2026'
    ]
    LOOP
        EXECUTE format('ALTER TABLE public.%I DROP COLUMN IF EXISTS schmetzer_score_per_million', target_table);
        EXECUTE format('DELETE FROM public.%I', target_table);
        RAISE NOTICE 'prepared %', target_table;
    END LOOP;
END
$$;
