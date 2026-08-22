-- Creates the Supabase (Postgres) copy of dim_schmetzer_score_points.
--
-- The SQLite side gets this table from etl/sql/create/, but Supabase is a separate
-- database whose schema is not built by those scripts. Run this once in the Supabase SQL
-- editor before the first sync that carries the weights, or insert_SQLite_to_Supabase()
-- will fail its final step with PGRST205 ("Could not find the table
-- 'public.dim_schmetzer_score_points' in the schema cache").
--
-- The score tables upload before this one, so a failure here does not block the data the
-- app serves -- only the record of the weights that produced it.
--
-- Safe to re-run, and self-healing: step 2 repairs a table that already exists without a
-- unique constraint on stat_name. That case is not hypothetical -- a table created outside
-- this script can end up with no constraint on stat_name at all, and CREATE TABLE IF NOT
-- EXISTS then silently does nothing. The sync fails on that with 42P10 ("there is no unique
-- or exclusion constraint matching the ON CONFLICT specification"), because
-- insert_SQLite_to_Supabase() upserts on stat_name.
--
-- Such a table is also unable to publish deletes to Supabase Realtime (error 55000, "does
-- not have a replica identity and publishes deletes"), so step 2 handles its own replica
-- identity rather than assuming one exists.

-- stat_name: the statistic, matching the keys under schmetzer_score_points in data_vars.json
-- point_value: what one occurrence of that statistic contributes to the Schmetzer Score
-- abbrev: short label for display

-- 1. Create the table when it is absent, with the constraint the upsert needs.
CREATE TABLE IF NOT EXISTS "dim_schmetzer_score_points" (
    stat_name   TEXT PRIMARY KEY,
    point_value REAL,
    abbrev      TEXT
);

-- 2. Repair a table that already existed without a single-column unique constraint on
--    stat_name. UNIQUE rather than PRIMARY KEY, so this coexists with a surrogate key the
--    table editor may already have added; ON CONFLICT accepts any unique constraint.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        JOIN pg_attribute a
          ON a.attrelid = c.conrelid
         AND a.attnum = ANY (c.conkey)
        WHERE c.conrelid = 'public.dim_schmetzer_score_points'::regclass
          AND c.contype IN ('p', 'u')
          AND array_length(c.conkey, 1) = 1
          AND a.attname = 'stat_name'
    ) THEN
        -- A unique constraint cannot be added over duplicates or NULLs, so any existing
        -- rows are pruned first. The table is a copy of SQLite truth that the next sync
        -- repopulates, so pruning is safe. Skipped entirely when the table is empty,
        -- which is the common case.
        IF EXISTS (SELECT 1 FROM "dim_schmetzer_score_points") THEN
            -- Supabase Realtime publishes this table, and Postgres refuses to publish a
            -- DELETE from a table with no replica identity -- precisely the state a table
            -- without a primary key is in (error 55000). FULL is the only identity
            -- available until the unique constraint below exists.
            ALTER TABLE "dim_schmetzer_score_points" REPLICA IDENTITY FULL;

            DELETE FROM "dim_schmetzer_score_points" a
            USING "dim_schmetzer_score_points" b
            WHERE a.ctid < b.ctid
              AND a.stat_name IS NOT DISTINCT FROM b.stat_name;

            DELETE FROM "dim_schmetzer_score_points"
            WHERE stat_name IS NULL;
        END IF;

        ALTER TABLE "dim_schmetzer_score_points"
            ALTER COLUMN stat_name SET NOT NULL;

        ALTER TABLE "dim_schmetzer_score_points"
            ADD CONSTRAINT dim_schmetzer_score_points_stat_name_key UNIQUE (stat_name);

        -- With a NOT NULL unique index in place the table can identify its own rows, so
        -- replication no longer needs to carry every column to do it.
        ALTER TABLE "dim_schmetzer_score_points"
            REPLICA IDENTITY USING INDEX dim_schmetzer_score_points_stat_name_key;
    END IF;
END
$$;

-- 3. The app reads scores, not weights, so this table is reference data rather than a
--    served endpoint. Read-only to the anon key, matching the score tables.
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
