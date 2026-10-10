DROP TABLE IF EXISTS raw_WhoScored_mls_players_match_stats;

-- One row per player per match, tallied from WhoScored's Opta event stream by
-- dependencies/get_from_whoscored.py. The counts mirror FBref's Player Miscellaneous
-- Stats columns (see raw_FBref_mls_players_all_stats_misc), which were season sums of
-- the same Opta events; stg_WhoScored_mls_players_all_stats_misc sums them per season.
CREATE TABLE raw_WhoScored_mls_players_match_stats (
    season         INTEGER  NOT NULL,
    game_id        INTEGER  NOT NULL, -- WhoScored's match id
    game_date      TEXT,              -- YYYY-MM-DD
    stage          TEXT,              -- 'Major League Soccer' for the regular season
    team           TEXT,              -- WhoScored's spelling; crosswalked in staging
    player_id      INTEGER  NOT NULL, -- WhoScored's player id
    player         TEXT     NOT NULL,
    position       TEXT,              -- WhoScored's position code for a starter (DC, MC, FW...); NULL off the bench
    age            INTEGER,           -- Age when the page was fetched, not at the match
    is_starter     INTEGER DEFAULT 0,
    minutes        INTEGER DEFAULT 0, -- Regulation minutes, stoppage time excluded as FBref did
    crdy           INTEGER DEFAULT 0,
    crdr           INTEGER DEFAULT 0,
    second_crdy    INTEGER DEFAULT 0,
    fls            INTEGER DEFAULT 0,
    fld            INTEGER DEFAULT 0,
    off            INTEGER DEFAULT 0,
    crs            INTEGER DEFAULT 0,
    intercept      INTEGER DEFAULT 0,
    tklw           INTEGER DEFAULT 0,
    pkwon          INTEGER DEFAULT 0,
    pkcon          INTEGER DEFAULT 0,
    og             INTEGER DEFAULT 0,
    recov          INTEGER DEFAULT 0,
    duels_won      INTEGER DEFAULT 0, -- Aerial duels, as FBref's 'Won'
    duels_lost     INTEGER DEFAULT 0, -- Aerial duels, as FBref's 'Lost'
    load_datetime  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (game_id, player_id)
);

CREATE INDEX IF NOT EXISTS idx_raw_WhoScored_match_stats__season_player
    ON raw_WhoScored_mls_players_match_stats (season, player_id);
