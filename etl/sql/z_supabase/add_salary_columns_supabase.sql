-- Adds the salary columns to the Supabase (Postgres) copies of the Schmetzer Score tables.
--
-- The SQLite side gets these columns from etl/sql/create/, but Supabase is a separate
-- database whose schema is not built by those scripts. Run this once in the Supabase SQL
-- editor before the first salary sync, or pipeline_*_MLSPA_* will fail its upload step with
-- PGRST204 ("Could not find the 'base_salary' column ... in the schema cache").
--
-- Safe to re-run: every statement is IF NOT EXISTS.

-- base_salary: MLSPA annual base salary in USD
-- guaranteed_comp: MLSPA annual average guaranteed compensation in USD
-- salary_match_tier: Which rule joined this player to their salary record
-- schmetzer_score_per_million: Schmetzer Score earned per $1M of guaranteed compensation
-- schmetzer_value_rk: Rank by the metric above, among players past the minutes floor

ALTER TABLE "schmetzer_scores_all" ADD COLUMN IF NOT EXISTS base_salary REAL;
ALTER TABLE "schmetzer_scores_all" ADD COLUMN IF NOT EXISTS guaranteed_comp REAL;
ALTER TABLE "schmetzer_scores_all" ADD COLUMN IF NOT EXISTS salary_match_tier TEXT;
ALTER TABLE "schmetzer_scores_all" ADD COLUMN IF NOT EXISTS schmetzer_score_per_million REAL;
ALTER TABLE "schmetzer_scores_all" ADD COLUMN IF NOT EXISTS schmetzer_value_rk INTEGER;

ALTER TABLE "schmetzer_scores_2018" ADD COLUMN IF NOT EXISTS base_salary REAL;
ALTER TABLE "schmetzer_scores_2018" ADD COLUMN IF NOT EXISTS guaranteed_comp REAL;
ALTER TABLE "schmetzer_scores_2018" ADD COLUMN IF NOT EXISTS salary_match_tier TEXT;
ALTER TABLE "schmetzer_scores_2018" ADD COLUMN IF NOT EXISTS schmetzer_score_per_million REAL;
ALTER TABLE "schmetzer_scores_2018" ADD COLUMN IF NOT EXISTS schmetzer_value_rk INTEGER;

ALTER TABLE "schmetzer_scores_2019" ADD COLUMN IF NOT EXISTS base_salary REAL;
ALTER TABLE "schmetzer_scores_2019" ADD COLUMN IF NOT EXISTS guaranteed_comp REAL;
ALTER TABLE "schmetzer_scores_2019" ADD COLUMN IF NOT EXISTS salary_match_tier TEXT;
ALTER TABLE "schmetzer_scores_2019" ADD COLUMN IF NOT EXISTS schmetzer_score_per_million REAL;
ALTER TABLE "schmetzer_scores_2019" ADD COLUMN IF NOT EXISTS schmetzer_value_rk INTEGER;

ALTER TABLE "schmetzer_scores_2020" ADD COLUMN IF NOT EXISTS base_salary REAL;
ALTER TABLE "schmetzer_scores_2020" ADD COLUMN IF NOT EXISTS guaranteed_comp REAL;
ALTER TABLE "schmetzer_scores_2020" ADD COLUMN IF NOT EXISTS salary_match_tier TEXT;
ALTER TABLE "schmetzer_scores_2020" ADD COLUMN IF NOT EXISTS schmetzer_score_per_million REAL;
ALTER TABLE "schmetzer_scores_2020" ADD COLUMN IF NOT EXISTS schmetzer_value_rk INTEGER;

ALTER TABLE "schmetzer_scores_2021" ADD COLUMN IF NOT EXISTS base_salary REAL;
ALTER TABLE "schmetzer_scores_2021" ADD COLUMN IF NOT EXISTS guaranteed_comp REAL;
ALTER TABLE "schmetzer_scores_2021" ADD COLUMN IF NOT EXISTS salary_match_tier TEXT;
ALTER TABLE "schmetzer_scores_2021" ADD COLUMN IF NOT EXISTS schmetzer_score_per_million REAL;
ALTER TABLE "schmetzer_scores_2021" ADD COLUMN IF NOT EXISTS schmetzer_value_rk INTEGER;

ALTER TABLE "schmetzer_scores_2022" ADD COLUMN IF NOT EXISTS base_salary REAL;
ALTER TABLE "schmetzer_scores_2022" ADD COLUMN IF NOT EXISTS guaranteed_comp REAL;
ALTER TABLE "schmetzer_scores_2022" ADD COLUMN IF NOT EXISTS salary_match_tier TEXT;
ALTER TABLE "schmetzer_scores_2022" ADD COLUMN IF NOT EXISTS schmetzer_score_per_million REAL;
ALTER TABLE "schmetzer_scores_2022" ADD COLUMN IF NOT EXISTS schmetzer_value_rk INTEGER;

ALTER TABLE "schmetzer_scores_2023" ADD COLUMN IF NOT EXISTS base_salary REAL;
ALTER TABLE "schmetzer_scores_2023" ADD COLUMN IF NOT EXISTS guaranteed_comp REAL;
ALTER TABLE "schmetzer_scores_2023" ADD COLUMN IF NOT EXISTS salary_match_tier TEXT;
ALTER TABLE "schmetzer_scores_2023" ADD COLUMN IF NOT EXISTS schmetzer_score_per_million REAL;
ALTER TABLE "schmetzer_scores_2023" ADD COLUMN IF NOT EXISTS schmetzer_value_rk INTEGER;

ALTER TABLE "schmetzer_scores_2024" ADD COLUMN IF NOT EXISTS base_salary REAL;
ALTER TABLE "schmetzer_scores_2024" ADD COLUMN IF NOT EXISTS guaranteed_comp REAL;
ALTER TABLE "schmetzer_scores_2024" ADD COLUMN IF NOT EXISTS salary_match_tier TEXT;
ALTER TABLE "schmetzer_scores_2024" ADD COLUMN IF NOT EXISTS schmetzer_score_per_million REAL;
ALTER TABLE "schmetzer_scores_2024" ADD COLUMN IF NOT EXISTS schmetzer_value_rk INTEGER;

ALTER TABLE "schmetzer_scores_2025" ADD COLUMN IF NOT EXISTS base_salary REAL;
ALTER TABLE "schmetzer_scores_2025" ADD COLUMN IF NOT EXISTS guaranteed_comp REAL;
ALTER TABLE "schmetzer_scores_2025" ADD COLUMN IF NOT EXISTS salary_match_tier TEXT;
ALTER TABLE "schmetzer_scores_2025" ADD COLUMN IF NOT EXISTS schmetzer_score_per_million REAL;
ALTER TABLE "schmetzer_scores_2025" ADD COLUMN IF NOT EXISTS schmetzer_value_rk INTEGER;

CREATE INDEX IF NOT EXISTS idx_schmetzer_scores_all__value
    ON "schmetzer_scores_all" (schmetzer_score_per_million);
