DROP TABLE IF EXISTS raw_MLSPA_mls_players_salaries;

CREATE TABLE raw_MLSPA_mls_players_salaries (
    season           INTEGER  NOT NULL,
    first_name       TEXT,
    last_name        TEXT     NOT NULL,
    club             TEXT,
    position         TEXT,
    base_salary      TEXT, -- Held as sourced ('$1,650,000.00'); cast to REAL in staging
    guaranteed_comp  TEXT, -- Held as sourced ('$2,332,000.00'); cast to REAL in staging
    release_label    TEXT, -- Which release of the season this row came from
    source_url       TEXT, -- The MLSPA file the row was parsed out of
    load_datetime    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_raw_MLSPA_salaries__season ON raw_MLSPA_mls_players_salaries (season);
