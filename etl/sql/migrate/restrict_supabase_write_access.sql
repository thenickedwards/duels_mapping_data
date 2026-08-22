-- Makes the Supabase tables read-only to the public anon key.
--
-- The app reads these tables from the browser with SUPABASE_ANON_KEY, which is public by
-- design -- anyone can lift it out of the network tab. While the tables accept anon
-- writes, anyone can also rewrite them. This turns on row level security with a read-only
-- policy, so anon can SELECT and nothing else.
--
-- The sync keeps working because it authenticates with the service role key, which
-- bypasses RLS entirely. resolve_supabase_write_credentials() in etl/data_handler.py
-- reads it from SUPABASE_SERVICE_ROLE_KEY.
--
-- ORDER MATTERS. Add SUPABASE_SERVICE_ROLE_KEY to .env BEFORE running this, or the next
-- sync fails with 42501 ("new row violates row-level security policy"). Copy it from
-- Supabase: Project Settings -> API -> service_role. It is a secret -- it must never
-- reach the frontend, a client bundle, or a commit. .env is already gitignored.
--
-- Safe to re-run: every statement is guarded.

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
        'dim_schmetzer_score_points'
    ]
    LOOP
        -- Skip anything not actually present, so this runs on a partial environment.
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = 'public' AND tablename = target_table
        ) THEN
            RAISE NOTICE 'skipping %, not present', target_table;
            CONTINUE;
        END IF;

        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', target_table);

        -- Read stays open: this is public sports data behind a public dashboard.
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE schemaname = 'public'
              AND tablename = target_table
              AND policyname = 'Allow public read access'
        ) THEN
            EXECUTE format(
                'CREATE POLICY "Allow public read access" ON public.%I FOR SELECT USING (true)',
                target_table
            );
        END IF;

        -- No INSERT, UPDATE or DELETE policy is created. With RLS on and no policy for
        -- those commands, anon is denied them; the service role bypasses RLS and is
        -- unaffected.
        RAISE NOTICE 'locked down %', target_table;
    END LOOP;
END
$$;

-- Confirm the result: every table below should report rls_enabled = true with exactly one
-- policy, named "Allow public read access", whose cmd is SELECT.
SELECT
    c.relname                         AS table_name,
    c.relrowsecurity                  AS rls_enabled,
    COALESCE(p.policy_count, 0)       AS policies,
    COALESCE(p.commands, '{}')        AS policy_commands
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN (
    SELECT tablename, COUNT(*) AS policy_count, array_agg(DISTINCT cmd) AS commands
    FROM pg_policies
    WHERE schemaname = 'public'
    GROUP BY tablename
) p ON p.tablename = c.relname
WHERE n.nspname = 'public'
  AND (c.relname LIKE 'schmetzer_scores%' OR c.relname = 'dim_schmetzer_score_points')
ORDER BY c.relname;
