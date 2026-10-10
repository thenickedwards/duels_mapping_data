DROP TABLE IF EXISTS dim_WhoScored_mls_players;

-- Resolves each WhoScored player id to the identity the app already knows them by.
--
-- WhoScored's match data has no nationality or birth year, yet player_yob is part of
-- every Schmetzer Score id and is how the app links a player across seasons. So a
-- player who appears in the FBref tables (2018-2025) carries over FBref's name,
-- nationality and birth year, keeping their history joined up; anyone else is filled
-- from their WhoScored profile page. detail_source records which rule applied.
CREATE TABLE dim_WhoScored_mls_players (
    player_id           INTEGER PRIMARY KEY, -- WhoScored's player id
    whoscored_name      TEXT NOT NULL,
    player_name         TEXT NOT NULL,       -- FBref's spelling when carried over, else WhoScored's
    player_nationality  TEXT,                -- FIFA trigram, as FBref recorded it (USA, GER, ENG...)
    player_yob          INTEGER,
    birth_date          TEXT,                -- YYYY-MM-DD, from the profile when fetched
    fbref_season        INTEGER,             -- The FBref season carried over from, if any
    fbref_age           INTEGER,             -- FBref's age for that season, to age forward from
    fallback_position   TEXT,                -- GK/DF/MF/FW for players who never start
    detail_source       TEXT,                -- 'fbref_name', 'fbref_profile', 'whoscored_profile' or NULL
    load_datetime       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
