DROP VIEW IF EXISTS stg_mls_players_all_stats_misc;

-- Every season's staged misc stats, whichever source delivered them. FBref covers
-- 2018-2025 and stopped there (Opta cut Sports Reference off in January 2026);
-- WhoScored covers 2026 onward. The Schmetzer Score scripts read this view, so a
-- season scores the same way whichever source it came from.
--
-- FBref takes precedence: a WhoScored season is only read where FBref has none, so
-- loading WhoScored for an FBref season (to compare them, say) never double counts.
CREATE VIEW stg_mls_players_all_stats_misc AS
SELECT
    season, player_name, player_nationality, position, squad, player_age, player_yob,
    nineties, yellow_cards1, red_cards, yellow_cards2, fouls_committed, fouls_drawn,
    offside, crosses, interceptions, tackles_won, pks_won, pks_con, own_goals,
    recoveries, aerial_duels_won, aerial_duels_lost, aerial_duels_total,
    aerial_duels_won_pct, load_datetime
FROM stg_FBref_mls_players_all_stats_misc
UNION ALL
SELECT
    season, player_name, player_nationality, position, squad, player_age, player_yob,
    nineties, yellow_cards1, red_cards, yellow_cards2, fouls_committed, fouls_drawn,
    offside, crosses, interceptions, tackles_won, pks_won, pks_con, own_goals,
    recoveries, aerial_duels_won, aerial_duels_lost, aerial_duels_total,
    aerial_duels_won_pct, load_datetime
FROM stg_WhoScored_mls_players_all_stats_misc
WHERE season NOT IN (SELECT DISTINCT season FROM stg_FBref_mls_players_all_stats_misc);
