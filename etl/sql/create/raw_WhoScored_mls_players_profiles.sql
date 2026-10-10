DROP TABLE IF EXISTS raw_WhoScored_mls_players_profiles;

-- WhoScored's player profile page, as fetched. A profile is only fetched for a player
-- whose name could not be matched to an FBref player (see dim_WhoScored_mls_players),
-- so this holds the newcomers rather than every player.
CREATE TABLE raw_WhoScored_mls_players_profiles (
    player_id        INTEGER PRIMARY KEY, -- WhoScored's player id
    player           TEXT,
    nationality      TEXT,                -- As displayed, e.g. 'USA' or 'Germany'
    nationality_iso  TEXT,                -- The flag's ISO 3166 code, e.g. 'us' or 'gb-eng'
    birth_date       TEXT,                -- YYYY-MM-DD
    positions        TEXT,                -- As displayed, e.g. 'Defender, Midfielder'
    load_datetime    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
