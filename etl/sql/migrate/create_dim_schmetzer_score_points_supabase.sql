-- Creates the Supabase (Postgres) copy of dim_schmetzer_score_points.
--
-- The SQLite side gets this table from etl/sql/create/, but Supabase is a separate
-- database whose schema is not built by those scripts. Run this once in the Supabase SQL
-- editor before the first sync that carries the weights, or insert_SQLite_to_Supabase()
-- will fail its final step with PGRST205 ("Could not find the table
-- 'public.dim_schmetzer_score_points' in the schema cache").
--
-- The score tables upload before this one, so a missing table here does not block the
-- data the app serves -- only the record of the weights that produced it.
--
-- Safe to re-run: every statement is IF NOT EXISTS.

-- stat_name: the statistic, matching the keys under schmetzer_score_points in data_vars.json
-- point_value: what one occurrence of that statistic contributes to the Schmetzer Score
-- abbrev: short label for display

CREATE TABLE IF NOT EXISTS "dim_schmetzer_score_points" (
    stat_name   TEXT PRIMARY KEY,
    point_value REAL,
    abbrev      TEXT
);

-- The app reads scores, not weights, so this table is reference data rather than a
-- served endpoint. Read-only to the anon key, matching the score tables.
ALTER TABLE "dim_schmetzer_score_points" ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'dim_schmetzer_score_points'
          AND policyname = 'Allow public read access'
    ) THEN
        CREATE POLICY "Allow public read access"
            ON "dim_schmetzer_score_points"
            FOR SELECT
            USING (true);
    END IF;
END
$$;
