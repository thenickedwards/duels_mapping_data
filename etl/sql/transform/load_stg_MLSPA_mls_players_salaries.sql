DELETE FROM stg_MLSPA_mls_players_salaries WHERE season = {year};

INSERT INTO stg_MLSPA_mls_players_salaries (
    salary_key,
    season,
    player_name,
    player_first_name,
    player_last_name,
    mlspa_club,
    squad,
    mlspa_position,
    base_salary,
    guaranteed_comp,
    release_label,
    load_datetime
)
-- The MLSPA publishes no player id, so a key is built the same way the Schmetzer
-- Score id is: lowercased name with whitespace removed, plus season and club.
SELECT
    LOWER(REPLACE(TRIM(COALESCE(raw.first_name, '') || ' ' || raw.last_name), ' ', ''))
        || '-' || raw.season
        || '-' || LOWER(REPLACE(COALESCE(raw.club, 'unknown_club'), ' ', '')) AS salary_key,
    raw.season,
    TRIM(COALESCE(raw.first_name, '') || ' ' || raw.last_name) AS player_name,
    raw.first_name,
    raw.last_name,
    raw.club,
    crosswalk.squad,
    raw.position,
    -- Amounts arrive as '$1,650,000.00'; strip the currency formatting before casting
    CAST(REPLACE(REPLACE(raw.base_salary, '$', ''), ',', '') AS REAL) AS base_salary,
    CAST(REPLACE(REPLACE(raw.guaranteed_comp, '$', ''), ',', '') AS REAL) AS guaranteed_comp,
    raw.release_label,
    CURRENT_TIMESTAMP
FROM raw_MLSPA_mls_players_salaries raw
LEFT JOIN dim_mls_club_crosswalk crosswalk
       ON crosswalk.club_alias = raw.club
      AND crosswalk.source = 'mlspa'
WHERE raw.season = {year}
GROUP BY salary_key;
