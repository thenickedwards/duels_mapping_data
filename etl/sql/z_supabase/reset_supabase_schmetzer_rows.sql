-- Clears the Supabase copies of the Schmetzer Score tables so the next sync repopulates
-- them from scratch.
--
-- Needed once, after squad names were standardized. The id embeds the squad slug, so
-- 'cristianroldan-1995-2024-seattlesounders-usa' became
-- 'cristianroldan-1995-2024-seattlesoundersfc-usa'. insert_SQLite_to_Supabase() upserts
-- on id, so without this the new rows insert alongside the old ones and every affected
-- player appears twice.
--
-- The SQLite database is the source of truth for these tables (see the README), so
-- everything deleted here comes straight back on the next sync:
--     source ./duels_mapping.sh sync
--
-- Run this in the Supabase SQL editor, then run the sync.

DELETE FROM "schmetzer_scores_all";
DELETE FROM "schmetzer_scores_2018";
DELETE FROM "schmetzer_scores_2019";
DELETE FROM "schmetzer_scores_2020";
DELETE FROM "schmetzer_scores_2021";
DELETE FROM "schmetzer_scores_2022";
DELETE FROM "schmetzer_scores_2023";
DELETE FROM "schmetzer_scores_2024";
DELETE FROM "schmetzer_scores_2025";
