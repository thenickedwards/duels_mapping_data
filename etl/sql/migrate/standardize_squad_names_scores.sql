-- Applies the club crosswalk to a Schmetzer Score table that predates it.
--
-- The id is rebuilt alongside the squad because it embeds the squad slug. The
-- expression below is the same one that builds ids in
-- z_schmetzer_scores/schmetzer_scores_players.sql, so a row updated here is identical
-- to the row a rebuild from staging would produce.
--
-- Safe to re-run: a standardized squad is no longer an FBref alias, so this no-ops.

UPDATE "{table}"
SET squad = (
        SELECT crosswalk.squad
        FROM dim_mls_club_crosswalk crosswalk
        WHERE crosswalk.club_alias = "{table}".squad
          AND crosswalk.source = 'fbref'
    ),
    id = LOWER(REPLACE(player_name, ' ', ''))
         || '-' || player_yob
         || '-' || season
         || '-' || LOWER(REPLACE(COALESCE((
                SELECT crosswalk.squad
                FROM dim_mls_club_crosswalk crosswalk
                WHERE crosswalk.club_alias = "{table}".squad
                  AND crosswalk.source = 'fbref'
            ), 'unknown_squad'), ' ', ''))
         || '-' || LOWER(REPLACE(COALESCE(player_nationality, 'unknown_nat'), ' ', ''))
WHERE EXISTS (
    SELECT 1
    FROM dim_mls_club_crosswalk crosswalk
    WHERE crosswalk.club_alias = "{table}".squad
      AND crosswalk.source = 'fbref'
      AND crosswalk.squad IS NOT NULL
);
