-- Rebuilds one season of stg_WhoScored_mls_players_all_stats_misc from the match rows.
-- {year} is filled in by DH_WhoScored. A season is replaced whole on every run, unlike
-- the FBref load, so totals keep up as matches are added through the season.
DELETE FROM stg_WhoScored_mls_players_all_stats_misc WHERE season = {year};

INSERT INTO stg_WhoScored_mls_players_all_stats_misc (
    season,
    player_id,
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
-- WhoScored records a starter's position per match; FBref recorded a season position
-- as GK/DF/MF/FW, adding a second when the player spent real time there ('MF,FW').
-- Each match code is folded into one of those four, as in get_from_whoscored.py.
WITH starts AS (
    SELECT
        player_id,
        team,
        CASE
            WHEN position = 'GK' THEN 'GK'
            WHEN position IN ('DC', 'DL', 'DR', 'DML', 'DMR') THEN 'DF'
            WHEN position IN ('DMC', 'MC', 'ML', 'MR', 'AMC', 'AML', 'AMR') THEN 'MF'
            WHEN position IN ('FW', 'FWL', 'FWR') THEN 'FW'
        END AS position_group
    FROM raw_WhoScored_mls_players_match_stats
    WHERE season = {year} AND is_starter = 1
),
position_counts AS (
    SELECT
        player_id,
        team,
        position_group,
        COUNT(*) AS starts,
        ROW_NUMBER() OVER (PARTITION BY player_id, team ORDER BY COUNT(*) DESC, position_group) AS position_rank,
        SUM(COUNT(*)) OVER (PARTITION BY player_id, team) AS total_starts
    FROM starts
    WHERE position_group IS NOT NULL
    GROUP BY player_id, team, position_group
),
positions AS (
    -- A second position is listed when it accounts for at least a quarter of the starts
    SELECT
        player_id,
        team,
        MAX(CASE WHEN position_rank = 1 THEN position_group END)
            || COALESCE(',' || MAX(CASE WHEN position_rank = 2 AND starts * 4 >= total_starts
                                        THEN position_group END), '') AS position
    FROM position_counts
    GROUP BY player_id, team
),
season_start AS (
    -- FBref gave each player's age at the start of the season
    SELECT MIN(game_date) AS game_date
    FROM raw_WhoScored_mls_players_match_stats
    WHERE season = {year}
),
totals AS (
    SELECT
        raw.player_id,
        raw.team,
        MAX(raw.player) AS whoscored_name,
        MAX(raw.age) AS fetched_age,
        SUM(raw.minutes) AS minutes,
        SUM(raw.crdy) AS crdy,
        SUM(raw.crdr) AS crdr,
        SUM(raw.second_crdy) AS second_crdy,
        SUM(raw.fls) AS fls,
        SUM(raw.fld) AS fld,
        SUM(raw.off) AS off,
        SUM(raw.crs) AS crs,
        SUM(raw.intercept) AS intercept,
        SUM(raw.tklw) AS tklw,
        SUM(raw.pkwon) AS pkwon,
        SUM(raw.pkcon) AS pkcon,
        SUM(raw.og) AS og,
        SUM(raw.recov) AS recov,
        SUM(raw.duels_won) AS duels_won,
        SUM(raw.duels_lost) AS duels_lost
    FROM raw_WhoScored_mls_players_match_stats raw
    WHERE raw.season = {year}
    GROUP BY raw.player_id, raw.team
)
SELECT
    {year},
    totals.player_id,
    COALESCE(players.player_name, totals.whoscored_name),
    players.player_nationality,
    COALESCE(positions.position, players.fallback_position),
    -- COALESCE keeps an unrecognised squad rather than nulling it, as the FBref load does
    COALESCE(crosswalk.squad, totals.team),
    CASE
        -- Exact when the birth date is known
        WHEN players.birth_date IS NOT NULL THEN
            CAST(strftime('%Y', season_start.game_date) AS INTEGER)
            - CAST(strftime('%Y', players.birth_date) AS INTEGER)
            - (strftime('%m-%d', season_start.game_date) < strftime('%m-%d', players.birth_date))
        -- Aged forward from FBref's last record of them
        WHEN players.fbref_age IS NOT NULL THEN players.fbref_age + ({year} - players.fbref_season)
        -- WhoScored's age as of the fetch, the best left
        ELSE totals.fetched_age
    END,
    players.player_yob,
    ROUND(totals.minutes / 90.0, 1),
    totals.crdy,
    totals.crdr,
    totals.second_crdy,
    totals.fls,
    totals.fld,
    totals.off,
    totals.crs,
    totals.intercept,
    totals.tklw,
    totals.pkwon,
    totals.pkcon,
    totals.og,
    totals.recov,
    totals.duels_won,
    totals.duels_lost,
    totals.duels_won + totals.duels_lost,
    CASE
        WHEN (totals.duels_won + totals.duels_lost) > 0
        THEN ROUND(1.0 * totals.duels_won / (totals.duels_won + totals.duels_lost), 3)
        ELSE 0.0
    END,
    CURRENT_TIMESTAMP
FROM totals
CROSS JOIN season_start
LEFT JOIN dim_WhoScored_mls_players players
       ON players.player_id = totals.player_id
LEFT JOIN positions
       ON positions.player_id = totals.player_id
      AND positions.team = totals.team
LEFT JOIN dim_mls_club_crosswalk crosswalk
       ON crosswalk.club_alias = totals.team
      AND crosswalk.source = 'whoscored';
