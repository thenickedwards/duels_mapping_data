DROP TABLE IF EXISTS stg_MLSPA_mls_players_salaries;

CREATE TABLE stg_MLSPA_mls_players_salaries (
    salary_key       TEXT PRIMARY KEY, -- Normalized name (lowercase, whitespace removed, snakecase, i.e. playername-season-club)
    season           INTEGER  NOT NULL,
    player_name      TEXT     NOT NULL, -- First and last name joined as published by the MLSPA
    player_first_name TEXT,
    player_last_name TEXT     NOT NULL,
    mlspa_club       TEXT, -- Club as published by the MLSPA
    squad            TEXT, -- Club crosswalked to the FBref spelling; NULL for non-club buckets
    mlspa_position   TEXT, -- Position as published by the MLSPA; the FBref position remains authoritative
    base_salary      REAL, -- Annual base salary in USD
    guaranteed_comp  REAL, -- Annual average guaranteed compensation in USD
    release_label    TEXT,
    schmetzer_id     TEXT, -- id of the schmetzer_scores row this salary was matched to; NULL when unmatched
    salary_match_tier TEXT, -- Which matching rule produced schmetzer_id (see dependencies/match_players.py)
    load_datetime    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_stg_MLSPA_salaries__season_squad
    ON stg_MLSPA_mls_players_salaries (season, squad);

CREATE INDEX IF NOT EXISTS idx_stg_MLSPA_salaries__schmetzer_id
    ON stg_MLSPA_mls_players_salaries (schmetzer_id);
