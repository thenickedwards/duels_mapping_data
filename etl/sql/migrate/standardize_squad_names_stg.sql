-- Applies the club crosswalk to the FBref staging table that predates it.
--
-- The staging load standardizes squad names going forward, but a database built before
-- that still holds FBref's own spellings, and the FBref raw table cannot be re-sourced
-- (see the January 2026 note in the README) -- so the values are corrected in place.
--
-- Safe to re-run: once a squad has been standardized its name is no longer an FBref
-- alias, so the WHERE clause stops matching and the statement becomes a no-op.

UPDATE stg_FBref_mls_players_all_stats_misc
SET squad = (
    SELECT crosswalk.squad
    FROM dim_mls_club_crosswalk crosswalk
    WHERE crosswalk.club_alias = stg_FBref_mls_players_all_stats_misc.squad
      AND crosswalk.source = 'fbref'
)
WHERE EXISTS (
    SELECT 1
    FROM dim_mls_club_crosswalk crosswalk
    WHERE crosswalk.club_alias = stg_FBref_mls_players_all_stats_misc.squad
      AND crosswalk.source = 'fbref'
      AND crosswalk.squad IS NOT NULL
);
