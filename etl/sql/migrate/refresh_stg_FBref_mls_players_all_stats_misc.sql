-- Rebuilds one season of stg_FBref_mls_players_all_stats_misc from the raw table.
-- {year} is filled in by DataHandler.refresh_stg_FBref_mls_players_all_stats_misc().
--
-- load_stg_FBref_mls_players_all_stats_misc.sql only inserts players staging has not
-- seen, so a raw season reloaded mid-season never reached staging: 2025 was reloaded
-- with the full regular season on 2025-10-23, but staging kept the early-August totals.
-- Raw is still intact and this is offline, so it is safe to re-run.
DELETE FROM stg_FBref_mls_players_all_stats_misc WHERE season = {year};

INSERT INTO stg_FBref_mls_players_all_stats_misc (
    season,
    player_name,
    player_nationality,
    position,
    squad,
    player_age,
    player_yob,
    nineties,
    yellow_cards1,
    red_cards,
    yellow_cards2,
    fouls_committed,
    fouls_drawn,
    offside,
    crosses,
    interceptions,
    tackles_won,
    pks_won,
    pks_con,
    own_goals,
    recoveries,
    aerial_duels_won,
    aerial_duels_lost,
    aerial_duels_total,
    aerial_duels_won_pct,
    load_datetime
)
SELECT
    raw.season,
    raw.player,
    raw.nation,
    raw.pos,
    COALESCE(crosswalk.squad, raw.squad) AS squad,
    raw.age,
    raw.born,
    raw.nineties,
    raw.crdy,
    raw.crdr,
    raw.second_crdy,
    raw.fls,
    raw.fld,
    raw.off,
    raw.crs,
    raw.intercept,
    raw.tklw,
    raw.pkwon,
    raw.pkcon,
    raw.og,
    raw.recov,
    raw.duels_won,
    raw.duels_lost,
    COALESCE(raw.duels_won, 0) + COALESCE(raw.duels_lost, 0) AS aerial_duels_total,
    CASE
        WHEN (COALESCE(raw.duels_won, 0) + COALESCE(raw.duels_lost, 0)) > 0
        THEN ROUND(1.0 * raw.duels_won / (raw.duels_won + raw.duels_lost), 3)
        ELSE 0.0
    END AS aerial_duels_won_pct,
    CURRENT_TIMESTAMP
FROM raw_FBref_mls_players_all_stats_misc raw
LEFT JOIN dim_mls_club_crosswalk crosswalk
       ON crosswalk.club_alias = raw.squad
      AND crosswalk.source = 'fbref'
WHERE raw.season = {year};
